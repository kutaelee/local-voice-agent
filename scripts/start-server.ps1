[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$runtimeRoot = 'E:\Data\LocalVoiceAgent\runtime'
$statusPath = Join-Path $runtimeRoot 'status\pc-server.json'
$logDirectory = Join-Path $runtimeRoot 'logs'
$passwordFile = 'E:\Data\LocalVoiceAgent\secrets\postgres-password'
$wslPython = '/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv/bin/python'
$wslAppRoot = '/mnt/c/Dev/Repos/local-voice-agent/apps/pc-server'

if (-not (Test-Path -LiteralPath $repoRoot -PathType Container)) {
    throw "Repository is unavailable: $repoRoot"
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

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $Port
)
try {
    $listener.Start()
}
catch {
    throw "Loopback PC server port 127.0.0.1`:$Port is unavailable."
}
finally {
    $listener.Stop()
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
$linuxCommand = (
    "cd $wslAppRoot && exec $wslPython -m uvicorn " +
    'local_voice_agent_server.api:create_app_from_environment --factory ' +
    "--host 127.0.0.1 --port $Port --no-access-log"
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
            $response = Invoke-RestMethod -Uri "http://127.0.0.1`:$Port/health" -TimeoutSec 1
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
        host = '127.0.0.1'
        port = $Port
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
