[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8766,

    [ValidatePattern('^http://(localhost|127\.0\.0\.1|\[::1\]):[0-9]+/$')]
    [string]$ComfyUiBaseUrl = 'http://127.0.0.1:8188/'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$startScript = Join-Path $repoRoot 'scripts\start-vllm.ps1'
$stopScript = Join-Path $repoRoot 'scripts\stop-vllm.ps1'
$statusRoot = 'E:\Data\LocalVoiceAgent\runtime\status'
$evidenceRoot = (
    'E:\Data\LocalVoiceAgent\runtime\evidence\model-switch'
)
$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$statusPath = Join-Path $statusRoot "live-model-switch-$stamp.json"
$evidencePath = Join-Path $evidenceRoot "live-model-switch-$stamp.json"
$script:events = @()
$script:ownedModel = $null

foreach ($path in @($startScript, $stopScript)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Registered script is unavailable: $path"
    }
}
if (-not (Test-Path -LiteralPath $evidenceRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $evidenceRoot | Out-Null
}

function Add-SwitchEvent {
    param(
        [Parameter(Mandatory)]
        [string]$Phase,

        [Parameter(Mandatory)]
        [string]$Model,

        [Parameter(Mandatory)]
        [string]$Result,

        [Parameter(Mandatory)]
        [long]$LatencyMs
    )

    $script:events += [ordered]@{
        phase = $Phase
        model = $Model
        result = $Result
        latency_ms = $LatencyMs
        timestamp = [DateTimeOffset]::Now.ToString('o')
    }
}

function Write-Status {
    param(
        [Parameter(Mandatory)]
        [string]$Phase,

        [Parameter(Mandatory)]
        [string]$Result,

        [Parameter(Mandatory)]
        [string]$Detail
    )

    $payload = [ordered]@{
        schema_version = '1.0'
        stamp = $stamp
        phase = $Phase
        result = $Result
        detail = $Detail
        evidence = $evidencePath
        updated_at = [DateTimeOffset]::Now.ToString('o')
    }
    $temporary = "$statusPath.tmp"
    $payload |
        ConvertTo-Json |
        Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $statusPath -Force
}

function Get-ComfyUiQueueState {
    $queueUri = [Uri]::new([Uri]$ComfyUiBaseUrl, 'queue')
    $processCount = @(
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
            Where-Object {
                $_.CommandLine -and
                $_.CommandLine -match (
                    '(?i)[\\/]AI[\\/]Apps[\\/]ComfyUI[\\/]main\.py'
                )
            }
    ).Count
    try {
        $queue = Invoke-RestMethod -Uri $queueUri -TimeoutSec 2
    }
    catch {
        return [pscustomobject]@{
            reachable = $false
            process_count = $processCount
            running = 0
            pending = 0
            busy = $processCount -gt 0
        }
    }
    $running = @($queue.queue_running).Count
    $pending = @($queue.queue_pending).Count
    return [pscustomobject]@{
        reachable = $true
        process_count = $processCount
        running = $running
        pending = $pending
        busy = ($running + $pending) -gt 0
    }
}

function Get-FreeGpuMemoryMiB {
    $value = (
        nvidia-smi `
            --query-gpu=memory.free `
            --format=csv,noheader,nounits |
            Select-Object -First 1
    ).Trim()
    $memory = 0
    if (-not [int]::TryParse($value, [ref]$memory)) {
        throw 'Unable to measure free GPU memory.'
    }
    return $memory
}

function Stop-OwnedModel {
    if ($null -eq $script:ownedModel) {
        return
    }
    $model = [string]$script:ownedModel
    $watch = [Diagnostics.Stopwatch]::StartNew()
    & powershell.exe `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $stopScript `
        -ExpectedModelSize $model |
        Out-Null
    $stopExitCode = $LASTEXITCODE
    $watch.Stop()
    if ($stopExitCode -ne 0) {
        throw "Registered $model stop exited $stopExitCode."
    }
    Add-SwitchEvent `
        -Phase 'unload' `
        -Model $model `
        -Result 'passed' `
        -LatencyMs $watch.ElapsedMilliseconds
    $script:ownedModel = $null
}

function Wait-ChildOrYield {
    param(
        [Parameter(Mandatory)]
        [Diagnostics.Process]$Process,

        [Parameter(Mandatory)]
        [string]$Phase
    )

    while (-not $Process.HasExited) {
        $queue = Get-ComfyUiQueueState
        if ($queue.busy) {
            try {
                Stop-OwnedModel
            }
            finally {
                $Process.Refresh()
                if (-not $Process.HasExited) {
                    $Process.Kill()
                }
            }
            Write-Status `
                -Phase 'yielded' `
                -Result 'yielded' `
                -Detail (
                    "ComfyUI became active during $Phase; stopped only " +
                    'the owned vLLM runtime.'
                )
            return $false
        }
        Start-Sleep -Seconds 2
        $Process.Refresh()
    }
    $Process.WaitForExit()
    return $true
}

function Assert-ModelIdentity {
    param(
        [Parameter(Mandatory)]
        [string]$ModelSize,

        [Parameter(Mandatory)]
        [string]$ApiKey
    )

    $expected = "gemma4-$ModelSize"
    Invoke-RestMethod `
        -Uri "http://127.0.0.1:$Port/health" `
        -TimeoutSec 5 |
        Out-Null
    $models = Invoke-RestMethod `
        -Uri "http://127.0.0.1:$Port/v1/models" `
        -Headers @{ Authorization = "Bearer $ApiKey" } `
        -TimeoutSec 5
    $identifiers = @($models.data | ForEach-Object { $_.id })
    if ($identifiers.Count -ne 1 -or $identifiers[0] -ne $expected) {
        throw (
            "Runtime model identity mismatch: expected=$expected, " +
            "observed=$($identifiers -join ',')."
        )
    }
}

function Start-And-VerifyModel {
    param(
        [Parameter(Mandatory)]
        [ValidateSet('12b', '31b')]
        [string]$ModelSize,

        [Parameter(Mandatory)]
        [string]$ApiKey
    )

    $watch = [Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process `
        -FilePath 'powershell.exe' `
        -ArgumentList @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-File', $startScript,
            '-ModelSize', $ModelSize,
            '-MtpMode', 'off',
            '-Port', [string]$Port,
            '-StartupTimeoutSeconds', '900'
        ) `
        -WindowStyle Hidden `
        -PassThru
    $script:ownedModel = $ModelSize
    if (-not (Wait-ChildOrYield -Process $process -Phase "$ModelSize load")) {
        return $false
    }
    $process.WaitForExit()
    $exitCode = $process.ExitCode
    if ($null -eq $exitCode) {
        try {
            Assert-ModelIdentity -ModelSize $ModelSize -ApiKey $ApiKey
            $exitCode = 0
        }
        catch {
            throw (
                "$ModelSize launcher exit code unavailable and identity " +
                'verification failed.'
            )
        }
    }
    if ($exitCode -ne 0) {
        throw "Registered $ModelSize startup exited $exitCode."
    }
    Assert-ModelIdentity -ModelSize $ModelSize -ApiKey $ApiKey
    $watch.Stop()
    Add-SwitchEvent `
        -Phase 'ready' `
        -Model $ModelSize `
        -Result 'passed' `
        -LatencyMs $watch.ElapsedMilliseconds
    return $true
}

$previousVllmKey = $env:LVA_VLLM_API_KEY
$apiKey = (
    [Guid]::NewGuid().ToString('N') +
    [Guid]::NewGuid().ToString('N')
)

try {
    for ($sample = 1; $sample -le 2; $sample += 1) {
        $queue = Get-ComfyUiQueueState
        $freeMemory = Get-FreeGpuMemoryMiB
        if ($queue.busy -or $freeMemory -lt 28500) {
            Write-Status `
                -Phase 'yielded' `
                -Result 'yielded' `
                -Detail (
                    "Shared GPU unavailable: ComfyUI running=" +
                    "$($queue.running), pending=$($queue.pending), " +
                    "free_vram_mib=$freeMemory. No vLLM process was started."
                )
            exit 20
        }
        if ($sample -eq 1) {
            Start-Sleep -Seconds 3
        }
    }

    $env:LVA_VLLM_API_KEY = $apiKey
    Write-Status `
        -Phase 'switching' `
        -Result 'running' `
        -Detail 'Verifying live 12B -> 31B -> 12B transition.'

    if (-not (Start-And-VerifyModel -ModelSize '12b' -ApiKey $apiKey)) {
        exit 21
    }
    Stop-OwnedModel
    if (-not (Start-And-VerifyModel -ModelSize '31b' -ApiKey $apiKey)) {
        exit 22
    }
    Stop-OwnedModel
    if (-not (Start-And-VerifyModel -ModelSize '12b' -ApiKey $apiKey)) {
        exit 23
    }
    Stop-OwnedModel

    $payload = [ordered]@{
        schema_version = '1.0'
        result = 'passed'
        sequence = @('12b', '31b', '12b')
        events = $script:events
        final_runtime_state = 'stopped_after_verified_12b_return'
        created_at = [DateTimeOffset]::Now.ToString('o')
    }
    $temporary = "$evidencePath.tmp"
    $payload |
        ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $evidencePath
    $hash = (
        Get-FileHash -LiteralPath $evidencePath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    Write-Status `
        -Phase 'completed' `
        -Result 'passed' `
        -Detail "Live switch passed; sha256=$hash"
    Write-Output "switch_status=$statusPath"
    Write-Output "switch_evidence=$evidencePath"
    Write-Output "switch_evidence_sha256=$hash"
}
catch {
    try {
        Stop-OwnedModel
    }
    catch {
        # Preserve the original failure.
    }
    Write-Status `
        -Phase 'failed' `
        -Result 'failed' `
        -Detail $_.Exception.Message
    throw
}
finally {
    $env:LVA_VLLM_API_KEY = $previousVllmKey
}
