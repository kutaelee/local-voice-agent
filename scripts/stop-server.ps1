[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\pc-server.json'
if (-not (Test-Path -LiteralPath $statusPath)) {
    Write-Output 'No registered Local Voice Agent server status file exists; nothing was stopped.'
    exit 0
}

throw 'A status file exists, but safe registered-process shutdown is not implemented yet.'
