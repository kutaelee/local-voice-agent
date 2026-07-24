[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\lan-relay.json'
if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
    Write-Output 'No registered LAN relay exists.'
    exit 0
}
$status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
$process = Get-CimInstance Win32_Process `
    -Filter "ProcessId=$([int]$status.pid)" `
    -ErrorAction SilentlyContinue
if (-not $process) {
    Write-Output 'Registered LAN relay is no longer running.'
    exit 0
}
if (
    $process.CommandLine -notmatch 'private-network-tcp-relay\.py' -or
    $process.CommandLine -notmatch "--listen-port $([int]$status.listen_port)"
) {
    throw 'Registered process identity does not match the LAN relay.'
}
Stop-Process -Id ([int]$status.pid)
Write-Output "Stopped registered LAN relay PID $($status.pid)."
