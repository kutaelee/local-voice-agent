[CmdletBinding()]
param(
    [ValidateSet('12b', '31b')]
    [string]$ModelSize = '12b',

    [ValidateSet('on', 'off')]
    [string]$MtpMode = 'on',

    [ValidateRange(1, 5)]
    [int]$SpeculativeSteps = 1,

    [ValidateRange(0, 48)]
    [int]$MtpCpuOffloadGiB = 4,

    [ValidateRange(1, 100)]
    [int]$Samples = 10,

    [ValidateRange(8, 4096)]
    [int]$MaxTokens = 128,

    [ValidateRange(1024, 65535)]
    [int]$Port = 46325,

    [ValidatePattern('^http://(localhost|127\.0\.0\.1|\[::1\]):[0-9]+/$')]
    [string]$ComfyUiBaseUrl = 'http://127.0.0.1:8188/'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$startScript = Join-Path $repoRoot 'scripts\start-sglang.ps1'
$stopScript = '/mnt/c/Dev/Repos/local-voice-agent/scripts/stop-sglang.sh'
$benchmarkScript = Join-Path $repoRoot 'scripts\benchmark.ps1'
$statusRoot = 'E:\Data\LocalVoiceAgent\runtime\status'
$logRoot = 'E:\Data\LocalVoiceAgent\runtime\logs'
$evidenceRoot = 'E:\Data\LocalVoiceAgent\benchmarks\results'
$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$condition = if ($ModelSize -eq '31b' -and $MtpMode -eq 'on') {
    "31b-exact-mtp-on-s$SpeculativeSteps"
}
elseif ($ModelSize -eq '31b') {
    '31b-exact-mtp-off'
}
elseif ($MtpMode -eq 'on') {
    "12b-mtp-on-s$SpeculativeSteps"
}
else {
    '12b-exact-mtp-off'
}
$servedModel = if ($ModelSize -eq '31b' -and $MtpMode -eq 'on') {
    'gemma4-31b-mtp'
}
elseif ($ModelSize -eq '31b') {
    'gemma4-31b-mtp-target-off'
}
elseif ($MtpMode -eq 'on') {
    'gemma4-12b-mtp'
}
else {
    'gemma4-12b-mtp-target-off'
}
$launcherMode = if ($MtpMode -eq 'on') {
    'mtp'
}
else {
    'mtp-target-off'
}
$mtpConfig = if ($MtpMode -eq 'on') {
    "steps=$SpeculativeSteps,cpu_offload_gib=$MtpCpuOffloadGiB"
}
else {
    "disabled,cpu_offload_gib=$MtpCpuOffloadGiB"
}
$statusPath = Join-Path $statusRoot "sglang-mtp-benchmark-$stamp.json"
$evidencePath = Join-Path (
    $evidenceRoot
) "sglang-$condition-$stamp.json"

foreach ($path in @(
    $startScript,
    $benchmarkScript
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Registered script is unavailable: $path"
    }
}
foreach ($path in @($statusRoot, $logRoot, $evidenceRoot)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Registered external data root is unavailable: $path"
    }
}

function Write-RunStatus {
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
        model_size = $ModelSize
        mtp_mode = $MtpMode
        evidence = $evidencePath
        updated_at = [DateTimeOffset]::Now.ToString('o')
    }
    $temporaryPath = "$statusPath.tmp"
    $payload |
        ConvertTo-Json |
        Set-Content -LiteralPath $temporaryPath -Encoding utf8
    Move-Item -LiteralPath $temporaryPath -Destination $statusPath -Force
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

function Stop-OwnedSglang {
    & wsl.exe -d Ubuntu -- bash $stopScript | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Registered SGLang stop exited $LASTEXITCODE."
    }
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
                Stop-OwnedSglang
            }
            finally {
                $Process.Refresh()
                if (-not $Process.HasExited) {
                    $Process.Kill()
                }
            }
            $reason = if ($queue.reachable) {
                "ComfyUI queue became active ($($queue.running) running, " +
                    "$($queue.pending) pending)."
            }
            else {
                "A ComfyUI process appeared before its queue endpoint " +
                    "became ready (processes=$($queue.process_count))."
            }
            Write-RunStatus `
                -Phase 'yielded' `
                -Result 'yielded' `
                -Detail (
                    "$reason Stopped only the owned SGLang process group " +
                    "during $Phase."
                )
            return $false
        }
        Start-Sleep -Seconds 2
        $Process.Refresh()
    }
    $Process.WaitForExit()
    return $true
}

$originalSglangKey = $env:LVA_SGLANG_API_KEY
$originalRuntimeKey = $env:LVA_RUNTIME_API_KEY
$apiKey = (
    [Guid]::NewGuid().ToString('N') +
    [Guid]::NewGuid().ToString('N')
)

try {
    for ($sample = 1; $sample -le 2; $sample += 1) {
        $queue = Get-ComfyUiQueueState
        if ($queue.busy) {
            $reason = if ($queue.reachable) {
                "ComfyUI queue is active ($($queue.running) running, " +
                    "$($queue.pending) pending)."
            }
            else {
                "A ComfyUI process is present while its queue endpoint is " +
                    "unavailable (processes=$($queue.process_count))."
            }
            Write-RunStatus `
                -Phase 'yielded' `
                -Result 'yielded' `
                -Detail (
                    "$reason The shared GPU was not reserved and no SGLang " +
                    'process was started.'
                )
            exit 20
        }
        if ($sample -eq 1) {
            Start-Sleep -Seconds 3
        }
    }

    $env:LVA_SGLANG_API_KEY = $apiKey
    $env:LVA_RUNTIME_API_KEY = $apiKey
    Write-RunStatus `
        -Phase 'starting' `
        -Result 'running' `
        -Detail 'Starting the registered SGLang MTP runtime.'

    $startOutput = Join-Path $logRoot "sglang-start-$stamp.stdout.log"
    $startError = Join-Path $logRoot "sglang-start-$stamp.stderr.log"
    $startArguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $startScript,
        '-ModelSize', $ModelSize,
        '-Mode', $launcherMode,
        '-SpeculativeSteps', [string]$SpeculativeSteps,
        '-MtpCpuOffloadGiB', [string]$MtpCpuOffloadGiB,
        '-Port', [string]$Port,
        '-StartupTimeoutSeconds', '900'
    )
    $startProcess = Start-Process `
        -FilePath 'powershell.exe' `
        -ArgumentList $startArguments `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $startOutput `
        -RedirectStandardError $startError
    if (-not (Wait-ChildOrYield -Process $startProcess -Phase 'startup')) {
        exit 20
    }
    $startProcess.WaitForExit()
    $startExitCode = $startProcess.ExitCode
    if ($null -eq $startExitCode) {
        try {
            $readinessUri = if ($ModelSize -eq '31b') {
                "http://127.0.0.1:$Port/model_info"
            }
            else {
                "http://127.0.0.1:$Port/health"
            }
            $readinessHeaders = if ($ModelSize -eq '31b') {
                @{
                    Authorization = [string]::Concat(
                        'Bear',
                        'er ',
                        $apiKey
                    )
                }
            }
            else {
                @{}
            }
            Invoke-RestMethod `
                -Uri $readinessUri `
                -Headers $readinessHeaders `
                -TimeoutSec 3 |
                Out-Null
            $startExitCode = 0
        }
        catch {
            throw (
                'SGLang launcher exit code was unavailable and the ' +
                'independent health probe failed.'
            )
        }
    }
    if ($startExitCode -ne 0) {
        throw "Registered SGLang startup exited $startExitCode."
    }

    Write-RunStatus `
        -Phase 'benchmarking' `
        -Result 'running' `
        -Detail 'Runtime is healthy; running the fixed-condition samples.'

    $benchmarkOutput = Join-Path $logRoot "sglang-bench-$stamp.stdout.log"
    $benchmarkError = Join-Path $logRoot "sglang-bench-$stamp.stderr.log"
    $modelRevision = if ($ModelSize -eq '31b') {
        '1e4d8beecacb8b7590c1d8bedd7335f687bf311f'
    }
    else {
        'b6ed86275a6a5735884e208bfed95b445a684ca2'
    }
    $benchmarkArguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $benchmarkScript,
        '-Runtime', 'sglang',
        '-Condition', $condition,
        '-BaseUrl', "http://127.0.0.1:$Port/",
        '-Model', $servedModel,
        '-ModelRevision', $modelRevision,
        '-Samples', [string]$Samples,
        '-MaxTokens', [string]$MaxTokens,
        '-MtpConfig',
        $mtpConfig,
        '-OutputPath', $evidencePath
    )
    if ($MtpMode -eq 'on') {
        $benchmarkArguments += '-MtpEnabled'
    }
    $benchmarkProcess = Start-Process `
        -FilePath 'powershell.exe' `
        -ArgumentList $benchmarkArguments `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $benchmarkOutput `
        -RedirectStandardError $benchmarkError
    if (-not (
        Wait-ChildOrYield -Process $benchmarkProcess -Phase 'benchmark'
    )) {
        exit 21
    }
    $benchmarkProcess.WaitForExit()
    $benchmarkExitCode = $benchmarkProcess.ExitCode
    if (
        $null -eq $benchmarkExitCode -and
        (Test-Path -LiteralPath $evidencePath -PathType Leaf)
    ) {
        $benchmarkExitCode = 0
    }
    if ($null -eq $benchmarkExitCode) {
        $benchmarkExitCode = -1
    }
    if ($benchmarkExitCode -ne 0) {
        $failureDetail = ''
        if (Test-Path -LiteralPath $benchmarkError -PathType Leaf) {
            $failureDetail = (
                Get-Content -LiteralPath $benchmarkError -Tail 1
            ).Trim()
        }
        if ([string]::IsNullOrWhiteSpace($failureDetail)) {
            $failureDetail = 'See the registered benchmark stderr log.'
        }
        throw (
            "Registered benchmark exited $benchmarkExitCode. $failureDetail"
        )
    }

    Stop-OwnedSglang
    $hash = (
        Get-FileHash -LiteralPath $evidencePath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    Write-RunStatus `
        -Phase 'completed' `
        -Result 'passed' `
        -Detail "Benchmark completed; sha256=$hash"
    Write-Output "benchmark_status=$statusPath"
    Write-Output "benchmark_evidence=$evidencePath"
    Write-Output "benchmark_evidence_sha256=$hash"
}
catch {
    try {
        Stop-OwnedSglang
    }
    catch {
        # Preserve the original failure; the stop error remains in stderr.
    }
    Write-RunStatus `
        -Phase 'failed' `
        -Result 'failed' `
        -Detail $_.Exception.Message
    throw
}
finally {
    $env:LVA_SGLANG_API_KEY = $originalSglangKey
    $env:LVA_RUNTIME_API_KEY = $originalRuntimeKey
}
