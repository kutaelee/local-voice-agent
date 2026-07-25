[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$supervisor = '/mnt/c/Dev/Repos/local-voice-agent/scripts/run-gpu-voice-stack.sh'
$gpuq = 'C:\Dev\Tools\CodexCLI\gpuq.cmd'
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\gpu-voice-stack.json'

function Set-RegisteredState {
    param([string]$State)

    if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
        return
    }
    $value = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    if ($value.component -ne 'gpu-voice-stack') {
        throw 'Registered GPU voice stack status is invalid.'
    }
    $value.state = $State
    $value | Add-Member `
        -NotePropertyName stopped_at `
        -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o') `
        -Force
    $temporary = "$statusPath.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        $value |
            ConvertTo-Json |
            Set-Content -LiteralPath $temporary -Encoding utf8
        Move-Item -LiteralPath $temporary -Destination $statusPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Stop-QueuedReservation {
    if (
        -not (Test-Path -LiteralPath $gpuq -PathType Leaf) -or
        -not (Test-Path -LiteralPath $statusPath -PathType Leaf)
    ) {
        return $false
    }
    $registered = Get-Content -LiteralPath $statusPath -Raw |
        ConvertFrom-Json
    $jobId = [Guid]::Empty
    if (
        $registered.component -ne 'gpu-voice-stack' -or
        -not [Guid]::TryParse(
            [string]$registered.gpuq_job_id,
            [ref]$jobId
        )
    ) {
        throw 'Registered GPU voice stack status is invalid.'
    }
    $scheduler = & $gpuq status | ConvertFrom-Json
    $pending = @($scheduler.jobs.queued) + @($scheduler.jobs.active)
    $matching = @(
        $pending |
            Where-Object { $_.id -eq $jobId.ToString() }
    )
    if ($matching.Count -eq 0) {
        return $false
    }
    if ($matching.Count -ne 1) {
        throw 'GPU voice reservation identity is ambiguous.'
    }
    & $gpuq cancel $jobId.ToString() | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'GPU voice reservation cancellation failed.'
    }
    Set-RegisteredState -State 'canceled'
    Write-Output 'GPU voice reservation canceled.'
    return $true
}

$pids = @(
    @(
        wsl.exe -d Ubuntu -- pgrep -f "^bash $supervisor$"
    ) | Where-Object { $_ -match '^\d+$' }
)

if ($pids.Count -eq 0) {
    if (Stop-QueuedReservation) {
        exit 0
    }
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
        Set-RegisteredState -State 'stopped'
        Write-Output 'GPU voice supervisor stopped gracefully.'
        exit 0
    }
}
throw 'GPU voice supervisor did not stop within 60 seconds.'
