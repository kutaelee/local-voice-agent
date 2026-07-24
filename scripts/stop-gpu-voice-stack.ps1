[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$supervisor = '/mnt/c/Dev/Repos/local-voice-agent/scripts/run-gpu-voice-stack.sh'
$pids = @(
    @(
        wsl.exe -d Ubuntu -- pgrep -f "^bash $supervisor$"
    ) | Where-Object { $_ -match '^\d+$' }
)

if ($pids.Count -eq 0) {
    Write-Output 'No registered GPU voice supervisor is running.'
    exit 0
}
if ($pids.Count -ne 1) {
    throw "Expected one GPU voice supervisor, found $($pids.Count)."
}

$pidValue = [int]$pids[0]
$command = wsl.exe -d Ubuntu -- ps -p $pidValue -o args=
if (
    $LASTEXITCODE -ne 0 -or
    $command.Trim() -ne "bash $supervisor"
) {
    throw 'GPU voice supervisor identity changed; refusing to signal it.'
}

wsl.exe -d Ubuntu -- kill -TERM $pidValue
if ($LASTEXITCODE -ne 0) {
    throw 'GPU voice supervisor did not accept SIGTERM.'
}
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    Start-Sleep -Milliseconds 500
    wsl.exe -d Ubuntu -- bash -lc "kill -0 $pidValue 2>/dev/null"
    if ($LASTEXITCODE -ne 0) {
        Write-Output 'GPU voice supervisor stopped gracefully.'
        exit 0
    }
}
throw 'GPU voice supervisor did not stop within 60 seconds.'
