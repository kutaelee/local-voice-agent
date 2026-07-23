[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$serverPath = 'C:\Dev\Tools\LocalVoiceAgent\runtimes\llama.cpp-b10092\llama-server.exe'
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\fallback-server.json'

if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
    Write-Output 'No registered fallback server exists.'
    return
}

$status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
$pidValue = 0
if (-not [int]::TryParse([string]$status.pid, [ref]$pidValue) -or $pidValue -le 0) {
    throw 'Fallback status contains an invalid PID; refusing to signal.'
}
$processRecord = Get-CimInstance Win32_Process -Filter "ProcessId = $pidValue" -ErrorAction SilentlyContinue
if (-not $processRecord) {
    Remove-Item -LiteralPath $statusPath
    Write-Output 'Registered fallback process is already stopped.'
    return
}
if (
    $processRecord.ExecutablePath -ne $serverPath -or
    $processRecord.CommandLine -notmatch 'llama-server\.exe'
) {
    throw "PID $pidValue is not the registered llama.cpp server; refusing to signal."
}

$process = Get-Process -Id $pidValue
if ($process.MainWindowHandle -ne 0) {
    [void]$process.CloseMainWindow()
    if ($process.WaitForExit(5000)) {
        Remove-Item -LiteralPath $statusPath
        Write-Output 'Owned fallback server stopped.'
        return
    }
}

# llama-server is a headless, task-owned process with no unsaved user state.
Stop-Process -Id $pidValue -Force
$process.WaitForExit(10000)
Remove-Item -LiteralPath $statusPath
Write-Output 'Owned fallback server stopped.'
