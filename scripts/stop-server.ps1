[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\pc-server.json'

if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
    Write-Output 'No registered Local Voice Agent server status file exists; nothing was stopped.'
    exit 0
}

$status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
$statusAddress = $null
$validHost = [System.Net.IPAddress]::TryParse([string]$status.host, [ref]$statusAddress) -and (
    [System.Net.IPAddress]::IsLoopback($statusAddress) -or
    (
        $statusAddress.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and (
            ($statusAddress.GetAddressBytes())[0] -eq 10 -or
            (($statusAddress.GetAddressBytes())[0] -eq 172 -and ($statusAddress.GetAddressBytes())[1] -ge 16 -and ($statusAddress.GetAddressBytes())[1] -le 31) -or
            (($statusAddress.GetAddressBytes())[0] -eq 192 -and ($statusAddress.GetAddressBytes())[1] -eq 168)
        )
    ) -or
    (
        $statusAddress.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetworkV6 -and
        ((($statusAddress.GetAddressBytes())[0] -band 0xFE) -eq 0xFC)
    )
)
if ($status.component -ne 'pc-server' -or -not $validHost -or -not $status.port -or -not $status.launcher_pid -or -not $status.linux_pid) {
    throw 'Registered PC server status is invalid; refusing to stop a process.'
}
$launcher = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $([int]$status.launcher_pid)" -ErrorAction SilentlyContinue
if (-not $launcher) {
    Write-Output 'Registered PC server launcher is no longer running; no process was stopped.'
    exit 0
}
if ($launcher.CommandLine -notmatch 'local_voice_agent_server\.api:create_app_from_environment' -or $launcher.CommandLine -notmatch "--port $($status.port)") {
    throw 'Registered launcher command line no longer matches the PC server; refusing to stop it.'
}

$linuxCommand = wsl.exe -d Ubuntu -- bash -lc "ps -p $([int]$status.linux_pid) -o args="
if ($LASTEXITCODE -eq 0 -and $linuxCommand -match 'local_voice_agent_server\.api:create_app_from_environment' -and $linuxCommand -match "--port $($status.port)") {
    wsl.exe -d Ubuntu -- bash -lc "kill -TERM $([int]$status.linux_pid)"
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        wsl.exe -d Ubuntu -- bash -lc "kill -0 $([int]$status.linux_pid) 2>/dev/null"
        if ($LASTEXITCODE -ne 0) {
            break
        }
    }
}

$launcherProcess = Get-Process -Id ([int]$status.launcher_pid) -ErrorAction SilentlyContinue
if ($launcherProcess -and -not $launcherProcess.HasExited) {
    Stop-Process -Id $launcherProcess.Id -Force
}
Write-Output "Stopped registered PC server launcher PID $($status.launcher_pid). Status file retained as evidence."
