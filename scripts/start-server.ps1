[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,

    [string]$ListenAddress = '127.0.0.1',

    [string]$TlsCertificatePath,

    [string]$TlsPrivateKeyPath,

    [switch]$EnablePrivateNetwork
)

$ErrorActionPreference = 'Stop'

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$runtimeRoot = 'E:\Data\LocalVoiceAgent\runtime'
$statusPath = Join-Path $runtimeRoot 'status\pc-server.json'
$logDirectory = Join-Path $runtimeRoot 'logs'
$passwordFile = 'E:\Data\LocalVoiceAgent\secrets\postgres-password'
$wslPython = '/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv/bin/python'
$wslAppRoot = '/mnt/c/Dev/Repos/local-voice-agent/apps/pc-server'

function Test-PrivateNetworkAddress {
    param([System.Net.IPAddress]$Address)

    if ($Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
        $bytes = $Address.GetAddressBytes()
        return $bytes[0] -eq 10 -or
            ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
            ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
    }

    # IPv6 Unique Local Addresses are fc00::/7. Link-local and public IPv6
    # addresses remain intentionally unsupported by this launcher.
    if ($Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetworkV6) {
        return (($Address.GetAddressBytes())[0] -band 0xFE) -eq 0xFC
    }

    return $false
}

function ConvertTo-BashLiteral {
    param([string]$Value)
    $embeddedSingleQuote = [string]::Concat([char]39, [char]34, [char]39, [char]34, [char]39)
    return "'" + $Value.Replace("'", $embeddedSingleQuote) + "'"
}

function ConvertTo-WslDrivePath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $fullPath = [System.IO.Path]::GetFullPath($WindowsPath)
    if ($fullPath -notmatch '^([A-Za-z]):\\(.+)$') {
        throw "Only absolute Windows drive paths can be translated for WSL: $WindowsPath"
    }
    $drive = $matches[1].ToLowerInvariant()
    $relativePath = $matches[2].Replace('\', '/')
    return "/mnt/$drive/$relativePath"
}

if (-not (Test-Path -LiteralPath $repoRoot -PathType Container)) {
    throw "Repository is unavailable: $repoRoot"
}

$parsedAddress = $null
if (-not [System.Net.IPAddress]::TryParse($ListenAddress, [ref]$parsedAddress)) {
    throw 'ListenAddress must be a numeric IP address; hostnames and wildcard bindings are rejected.'
}
$isLoopback = [System.Net.IPAddress]::IsLoopback($parsedAddress)
$tlsEnabled = -not [string]::IsNullOrWhiteSpace($TlsCertificatePath) -or
    -not [string]::IsNullOrWhiteSpace($TlsPrivateKeyPath)
if ($tlsEnabled -and ([string]::IsNullOrWhiteSpace($TlsCertificatePath) -or [string]::IsNullOrWhiteSpace($TlsPrivateKeyPath))) {
    throw 'TLS requires both -TlsCertificatePath and -TlsPrivateKeyPath.'
}
if (-not $isLoopback) {
    if (-not $EnablePrivateNetwork) {
        throw 'Non-loopback binding requires the explicit -EnablePrivateNetwork switch.'
    }
    if (-not (Test-PrivateNetworkAddress $parsedAddress)) {
        throw 'Only RFC1918 IPv4 or IPv6 ULA addresses may be used for a private-network listener.'
    }
    if (-not $tlsEnabled) {
        throw 'A private-network listener requires TLS certificate and key files.'
    }
}
if ($tlsEnabled) {
    if (-not (Test-Path -LiteralPath $TlsCertificatePath -PathType Leaf)) {
        throw "TLS certificate file is unavailable: $TlsCertificatePath"
    }
    if (-not (Test-Path -LiteralPath $TlsPrivateKeyPath -PathType Leaf)) {
        throw "TLS private-key file is unavailable: $TlsPrivateKeyPath"
    }
    $TlsCertificatePath = (Resolve-Path -LiteralPath $TlsCertificatePath).Path
    $TlsPrivateKeyPath = (Resolve-Path -LiteralPath $TlsPrivateKeyPath).Path
}
if (-not $env:LVA_PAIRING_TOKEN -or $env:LVA_PAIRING_TOKEN.Length -lt 32 -or $env:LVA_PAIRING_TOKEN -eq 'CHANGE_ME') {
    throw 'Set LVA_PAIRING_TOKEN to a non-placeholder secret of at least 32 characters.'
}
if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
    throw 'PostgreSQL password file is unavailable. Run start-postgres.ps1 first.'
}
$wslPythonCheck = wsl.exe -d Ubuntu -- bash -lc "test -x $wslPython"
if ($LASTEXITCODE -ne 0) {
    throw "PC-server Python environment is unavailable: $wslPython"
}

if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
    $previous = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    if ($previous.launcher_pid) {
        $existing = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $([int]$previous.launcher_pid)" -ErrorAction SilentlyContinue
        if ($existing) {
            throw "A registered PC server process is already running with launcher PID $($previous.launcher_pid)."
        }
    }
}

$windowsOwnsAddress = [bool](Get-NetIPAddress -IPAddress $ListenAddress -ErrorAction SilentlyContinue)
if ($isLoopback -or $windowsOwnsAddress) {
    $listener = [System.Net.Sockets.TcpListener]::new($parsedAddress, $Port)
    try {
        $listener.Start()
    }
    catch {
        throw "PC server port $ListenAddress`:$Port is unavailable."
    }
    finally {
        $listener.Stop()
    }
}
else {
    $wslAddressOutput = @(wsl.exe -d Ubuntu -- ip -o addr show)
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not inspect WSL network addresses.'
    }
    $wslOwnsAddress = [bool]($wslAddressOutput | Where-Object {
        $fields = $_ -split '\s+'
        $fields.Count -ge 4 -and ($fields[3] -split '/')[0] -eq $ListenAddress
    })
    if (-not $wslOwnsAddress) {
        throw "ListenAddress is not assigned to Windows or WSL Ubuntu: $ListenAddress"
    }
}

New-Item -ItemType Directory -Path (Split-Path -Parent $statusPath) -Force | Out-Null
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

$taskPassword = [System.IO.File]::ReadAllText($passwordFile).Trim()
if ($taskPassword.Length -lt 48) {
    throw 'PostgreSQL password file has an invalid size.'
}
$env:LVA_DATABASE_URL = (
    'postgresql+asyncpg://local_voice_agent:{0}@127.0.0.1:55432/local_voice_agent' -f
        [Uri]::EscapeDataString($taskPassword)
)

$bridgeNames = @(
    'LVA_PAIRING_TOKEN',
    'LVA_DATABASE_URL',
    'LVA_VOICE_ENABLED',
    'LVA_AUDIO_WORKER_TOKEN',
    'LVA_VAD_SOCKET',
    'LVA_STT_SOCKET',
    'LVA_TTS_SOCKET',
    'LVA_VLLM_API_KEY',
    'LVA_VLLM_BASE_URL',
    'LVA_VLLM_MODEL',
    'LVA_RUNTIME_SWITCH_ENABLED',
    'LVA_VLLM_RUNTIME_URL',
    'LVA_TOOLS_ENABLED',
    'LVA_TOOL_EXECUTOR_TOKEN',
    'LVA_TOOL_EXECUTOR_URL',
    'LVA_WINDOWS_HOST_IP',
    'LVA_REPO_ROOT',
    'LVA_WORKSPACE_ROOT'
)
$previousWslEnv = $env:WSLENV
$bridgeEntries = @($bridgeNames | Where-Object { Test-Path "Env:$_" })
$env:WSLENV = (($bridgeEntries + @($previousWslEnv)) -ne '' -join ':')

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stdoutPath = Join-Path $logDirectory "pc-server-$stamp.stdout.log"
$stderrPath = Join-Path $logDirectory "pc-server-$stamp.stderr.log"
$tlsArguments = ''
if ($tlsEnabled) {
    $wslCertificatePath = ConvertTo-WslDrivePath -WindowsPath $TlsCertificatePath
    $wslPrivateKeyPath = ConvertTo-WslDrivePath -WindowsPath $TlsPrivateKeyPath
    $tlsArguments = " --ssl-certfile $(ConvertTo-BashLiteral $wslCertificatePath)" +
        " --ssl-keyfile $(ConvertTo-BashLiteral $wslPrivateKeyPath)"
}
$linuxCommand = (
    "cd $wslAppRoot && exec $wslPython -m uvicorn " +
    'local_voice_agent_server.api:create_app_from_environment --factory ' +
    "--host $ListenAddress --port $Port --no-access-log$tlsArguments"
)

try {
    $process = Start-Process `
        -FilePath 'wsl.exe' `
        -ArgumentList @('-d', 'Ubuntu', '--', 'bash', '-lc', $linuxCommand) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    $healthy = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($process.HasExited) {
            break
        }
        try {
            $scheme = if ($tlsEnabled) { 'https' } else { 'http' }
            $healthUri = "${scheme}://$ListenAddress`:$Port/health"
            if ($tlsEnabled) {
                # The launcher is checking its own just-created local listener.
                # Android clients still perform normal certificate validation.
                $healthBody = & curl.exe --silent --show-error --fail --insecure --max-time 1 $healthUri 2>$null
                if ($LASTEXITCODE -ne 0) {
                    throw 'TLS health endpoint is unavailable.'
                }
                $response = $healthBody | ConvertFrom-Json
            }
            else {
                $response = Invoke-RestMethod -Uri $healthUri -TimeoutSec 1
            }
            if ($response.status -eq 'ok' -and $response.component -eq 'pc-server') {
                $healthy = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $healthy) {
        throw "PC server failed its health check. Inspect $stderrPath."
    }

    $linuxPidText = wsl.exe -d Ubuntu -- bash -lc (
        "pgrep -o -f 'local_voice_agent_server.api:create_app_from_environment.*--port $Port'"
    )
    if ($LASTEXITCODE -ne 0 -or -not ($linuxPidText -match '^\d+$')) {
        throw 'Could not identify the registered Linux PC-server process.'
    }
    $launcher = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $($process.Id)" -ErrorAction Stop
    if ($launcher.CommandLine -notmatch 'local_voice_agent_server\.api:create_app_from_environment' -or $launcher.CommandLine -notmatch "--port $Port") {
        throw 'The PC-server launcher command line is invalid.'
    }

    [ordered]@{
        schema_version = '1.0'
        component = 'pc-server'
        state = 'running'
        host = $ListenAddress
        port = $Port
        protocol = if ($tlsEnabled) { 'https' } else { 'http' }
        tls_enabled = $tlsEnabled
        launcher_pid = $process.Id
        launcher_executable = $process.Path
        linux_pid = [int]$linuxPidText.Trim()
        started_at = (Get-Date).ToUniversalTime().ToString('o')
        stdout_path = $stdoutPath
        stderr_path = $stderrPath
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
    Get-Content -LiteralPath $statusPath -Raw
}
catch {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
    throw
}
finally {
    $env:LVA_DATABASE_URL = $null
    $taskPassword = $null
    if ($null -eq $previousWslEnv) {
        Remove-Item Env:WSLENV -ErrorAction SilentlyContinue
    }
    else {
        $env:WSLENV = $previousWslEnv
    }
}
