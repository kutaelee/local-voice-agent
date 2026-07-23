[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8790
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
$statusPath = Join-Path $runtimeRoot 'status\tool-executor.json'
$auditPath = Join-Path $runtimeRoot 'audit\tool-executor.jsonl'
$evidencePath = Join-Path $runtimeRoot 'evidence\tool-executor'
$backupPath = Join-Path $runtimeRoot 'backups\tool-executor'
$logDirectory = Join-Path $runtimeRoot 'logs'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Tool Executor Python is unavailable: $python"
}
if (-not (Test-Path -LiteralPath $repoRoot -PathType Container)) {
    throw "Repository is unavailable: $repoRoot"
}
if (-not $env:LVA_TOOL_EXECUTOR_TOKEN -or $env:LVA_TOOL_EXECUTOR_TOKEN.Length -lt 32) {
    throw 'Set LVA_TOOL_EXECUTOR_TOKEN to a secret containing at least 32 characters.'
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
    [System.Net.IPAddress]::Loopback,
    $Port
)
try {
    $listener.Start()
}
catch {
    throw "Loopback port $Port is unavailable."
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

$arguments = @(
    '-m',
    'uvicorn',
    'local_voice_agent_tool_executor.bootstrap:create_app_from_environment',
    '--factory',
    '--host',
    '127.0.0.1',
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

try {
    $healthy = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($process.HasExited) {
            break
        }
        try {
            $response = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/health" `
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

    [ordered]@{
        schema_version = '1.0'
        component = 'tool-executor'
        state = 'running'
        pid = $process.Id
        host = '127.0.0.1'
        port = $Port
        executable = (Resolve-Path -LiteralPath $python).Path
        started_at = (Get-Date).ToUniversalTime().ToString('o')
        stdout_path = $stdoutPath
        stderr_path = $stderrPath
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}
catch {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
    throw
}

Get-Content -LiteralPath $statusPath -Raw
