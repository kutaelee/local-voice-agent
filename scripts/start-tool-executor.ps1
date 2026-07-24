[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 46323,

    [switch]$EnableWslNatBinding
)

$ErrorActionPreference = 'Stop'

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$defaultPython = 'C:\Dev\Tools\LocalVoiceAgent\runtimes\tool-executor\.venv\Scripts\python.exe'
$python = if ($env:LVA_TOOL_EXECUTOR_PYTHON) {
    $env:LVA_TOOL_EXECUTOR_PYTHON
}
else {
    $defaultPython
}
$runtimeRoot = 'E:\Data\LocalVoiceAgent\runtime'
$secretDirectory = 'E:\Data\LocalVoiceAgent\secrets'
$tokenFile = Join-Path $secretDirectory 'tool-executor-token'
$statusPath = Join-Path $runtimeRoot 'status\tool-executor.json'
$auditPath = Join-Path $runtimeRoot 'audit\tool-executor.jsonl'
$evidencePath = Join-Path $runtimeRoot 'evidence\tool-executor'
$backupPath = Join-Path $runtimeRoot 'backups\tool-executor'
$logDirectory = Join-Path $runtimeRoot 'logs'
$playwrightBrowsers = 'C:\Dev\Tools\LocalVoiceAgent\browsers\playwright-1.61.0'

function Set-RestrictedSecretAcl {
    param([Parameter(Mandatory)][string]$LiteralPath)

    $userSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
    $acl = Get-Acl -LiteralPath $LiteralPath
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) {
        [void]$acl.RemoveAccessRuleSpecific($rule)
    }
    foreach ($sid in @($userSid, $systemSid)) {
        [void]$acl.AddAccessRule(
            [System.Security.AccessControl.FileSystemAccessRule]::new(
                $sid,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                [System.Security.AccessControl.InheritanceFlags]::None,
                [System.Security.AccessControl.PropagationFlags]::None,
                [System.Security.AccessControl.AccessControlType]::Allow
            )
        )
    }
    Set-Acl -LiteralPath $LiteralPath -AclObject $acl
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Tool Executor Python is unavailable: $python"
}
if (-not (Test-Path -LiteralPath $repoRoot -PathType Container)) {
    throw "Repository is unavailable: $repoRoot"
}
New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $tokenFile -PathType Leaf)) {
    $random = [byte[]]::new(48)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($random)
        [System.IO.File]::WriteAllText(
            $tokenFile,
            [Convert]::ToBase64String($random).TrimEnd('='),
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    finally {
        $generator.Dispose()
        [Array]::Clear($random, 0, $random.Length)
    }
}
Set-RestrictedSecretAcl -LiteralPath $tokenFile
$env:LVA_TOOL_EXECUTOR_TOKEN = [System.IO.File]::ReadAllText($tokenFile).Trim()
if ($env:LVA_TOOL_EXECUTOR_TOKEN.Length -lt 32) {
    throw 'The Tool Executor token file is invalid.'
}
if (-not (Test-Path -LiteralPath $playwrightBrowsers -PathType Container)) {
    throw "Playwright browser runtime is unavailable: $playwrightBrowsers"
}

$bindAddress = '127.0.0.1'
$interfaceAlias = $null
if ($EnableWslNatBinding) {
    $wslAddresses = @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.InterfaceAlias -like 'vEthernet*WSL*' -and
                $_.IPAddress -notlike '169.254.*'
            }
    )
    if ($wslAddresses.Count -ne 1) {
        throw "Expected one WSL Hyper-V IPv4 address, found $($wslAddresses.Count)."
    }
    $candidate = [System.Net.IPAddress]::Parse($wslAddresses[0].IPAddress)
    $bytes = $candidate.GetAddressBytes()
    $isPrivate = (
        $bytes[0] -eq 10 -or
        ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
        ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
    )
    if (-not $isPrivate) {
        throw 'The WSL Hyper-V adapter does not have an RFC1918 private address.'
    }
    $bindAddress = $candidate.ToString()
    $interfaceAlias = $wslAddresses[0].InterfaceAlias
}

if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
    $previous = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    if ($previous.state -eq 'running' -and $previous.pid) {
        $existing = Get-Process -Id ([int]$previous.pid) -ErrorAction SilentlyContinue
        if ($existing) {
            throw "A registered Tool Executor process is already running with PID $($previous.pid)."
        }
    }
}

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Parse($bindAddress),
    $Port
)
try {
    $listener.Start()
}
catch {
    throw "Tool Executor endpoint $bindAddress`:$Port is unavailable."
}
finally {
    $listener.Stop()
}

@(
    (Split-Path -Parent $statusPath),
    (Split-Path -Parent $auditPath),
    $evidencePath,
    $backupPath,
    $logDirectory
) | ForEach-Object {
    New-Item -ItemType Directory -Path $_ -Force | Out-Null
}

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stdoutPath = Join-Path $logDirectory "tool-executor-$stamp.stdout.log"
$stderrPath = Join-Path $logDirectory "tool-executor-$stamp.stderr.log"

$env:LVA_REPO_ROOT = $repoRoot
$env:LVA_TOOL_EXECUTOR_AUDIT_LOG = $auditPath
$env:LVA_TOOL_EXECUTOR_EVIDENCE_DIR = $evidencePath
$env:LVA_TOOL_EXECUTOR_BACKUP_DIR = $backupPath
$env:PLAYWRIGHT_BROWSERS_PATH = $playwrightBrowsers

$arguments = @(
    '-m',
    'uvicorn',
    'local_voice_agent_tool_executor.bootstrap:create_app_from_environment',
    '--factory',
    '--host',
    $bindAddress,
    '--port',
    "$Port",
    '--no-access-log'
)
$process = Start-Process `
    -FilePath $python `
    -ArgumentList $arguments `
    -WorkingDirectory (Join-Path $repoRoot 'apps\tool-executor') `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

$serverProcess = $null
try {
    $healthy = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($process.HasExited) {
            break
        }
        try {
            $response = Invoke-RestMethod `
                -Uri "http://$bindAddress`:$Port/health" `
                -TimeoutSec 1
            if ($response.status -eq 'ok' -and $response.component -eq 'tool-executor') {
                $healthy = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $healthy) {
        throw "Tool Executor failed its health check. Inspect $stderrPath."
    }

    $listeners = @(
        Get-NetTCPConnection `
            -State Listen `
            -LocalAddress $bindAddress `
            -LocalPort $Port `
            -ErrorAction Stop
    )
    if ($listeners.Count -ne 1) {
        throw "Expected one Tool Executor listener, found $($listeners.Count)."
    }
    $serverProcess = Get-Process `
        -Id ([int]$listeners[0].OwningProcess) `
        -ErrorAction Stop
    $serverCim = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId = $($serverProcess.Id)"
    if (
        $serverProcess.Id -ne $process.Id -and
        [int]$serverCim.ParentProcessId -ne $process.Id
    ) {
        throw 'The Tool Executor listener is not owned by the launched process.'
    }
    if (
        $serverCim.CommandLine -notmatch
            'local_voice_agent_tool_executor\.bootstrap:create_app_from_environment' -or
        $serverCim.CommandLine -notmatch "--port $Port"
    ) {
        throw 'The Tool Executor listener command line is invalid.'
    }

    [ordered]@{
        schema_version = '1.0'
        component = 'tool-executor'
        state = 'running'
        pid = $serverProcess.Id
        host = $bindAddress
        interface_alias = $interfaceAlias
        port = $Port
        executable = $serverProcess.Path
        launcher_pid = $process.Id
        launcher_executable = $process.Path
        started_at = (Get-Date).ToUniversalTime().ToString('o')
        stdout_path = $stdoutPath
        stderr_path = $stderrPath
        token_file = $tokenFile
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}
catch {
    if (
        $serverProcess -and
        $serverProcess.Id -ne $process.Id -and
        -not $serverProcess.HasExited
    ) {
        Stop-Process -Id $serverProcess.Id -Force
    }
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
    throw
}

Get-Content -LiteralPath $statusPath -Raw
