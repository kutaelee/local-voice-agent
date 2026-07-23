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
    Stop-Process -Id $process.Id -Force
    $process.WaitForExit(5000) | Out-Null
}

[ordered]@{
    schema_version = '1.0'
    component = 'tool-executor'
    state = 'stopped'
    pid = [int]$status.pid
    host = $status.host
    port = [int]$status.port
    executable = $status.executable
    started_at = $status.started_at
    stopped_at = (Get-Date).ToUniversalTime().ToString('o')
    stdout_path = $status.stdout_path
    stderr_path = $status.stderr_path
} | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8

Get-Content -LiteralPath $statusPath -Raw
