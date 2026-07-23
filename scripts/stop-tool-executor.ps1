[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\tool-executor.json'
if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
    Write-Output 'No registered Tool Executor status file exists; nothing was stopped.'
    exit 0
}

$status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
if (
    $status.schema_version -ne '1.0' -or
    $status.component -ne 'tool-executor' -or
    -not $status.pid -or
    -not $status.executable
) {
    throw 'The Tool Executor status file is invalid; no process was stopped.'
}

$process = Get-Process -Id ([int]$status.pid) -ErrorAction SilentlyContinue
if ($process) {
    $expectedExecutable = (Resolve-Path -LiteralPath $status.executable).Path
    if ($process.Path -ne $expectedExecutable) {
        throw 'The registered PID belongs to a different executable; no process was stopped.'
    }
    $processDetails = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId = $($process.Id)"
    if (
        $processDetails.CommandLine -notmatch
            'local_voice_agent_tool_executor\.bootstrap:create_app_from_environment' -or
        $processDetails.CommandLine -notmatch "--port $([int]$status.port)"
    ) {
        throw 'The registered process command line is invalid; no process was stopped.'
    }
    Stop-Process -Id $process.Id -Force
    $process.WaitForExit(5000) | Out-Null
}

$launcher = $null
if ($status.launcher_pid -and [int]$status.launcher_pid -ne [int]$status.pid) {
    $launcher = Get-Process `
        -Id ([int]$status.launcher_pid) `
        -ErrorAction SilentlyContinue
}
if ($launcher) {
    $expectedLauncher = (Resolve-Path `
        -LiteralPath $status.launcher_executable).Path
    $launcherDetails = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId = $($launcher.Id)"
    if (
        $launcher.Path -ne $expectedLauncher -or
        $launcherDetails.CommandLine -notmatch
            'local_voice_agent_tool_executor\.bootstrap:create_app_from_environment' -or
        $launcherDetails.CommandLine -notmatch "--port $([int]$status.port)"
    ) {
        throw 'The registered launcher identity is invalid; it was not stopped.'
    }
    Stop-Process -Id $launcher.Id -Force
    $launcher.WaitForExit(5000) | Out-Null
}

[ordered]@{
    schema_version = '1.0'
    component = 'tool-executor'
    state = 'stopped'
    pid = [int]$status.pid
    host = $status.host
    port = [int]$status.port
    executable = $status.executable
    launcher_pid = $status.launcher_pid
    launcher_executable = $status.launcher_executable
    started_at = $status.started_at
    stopped_at = (Get-Date).ToUniversalTime().ToString('o')
    stdout_path = $status.stdout_path
    stderr_path = $status.stderr_path
} | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8

Get-Content -LiteralPath $statusPath -Raw
