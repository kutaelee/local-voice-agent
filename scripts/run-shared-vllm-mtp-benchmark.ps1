[CmdletBinding()]
param(
    [ValidateSet('on', 'off')]
    [string]$MtpMode = 'on',

    [ValidateRange(1, 3)]
    [int]$SpeculativeTokens = 1,

    [ValidateRange(1, 100)]
    [int]$Samples = 10,

    [ValidateRange(8, 4096)]
    [int]$MaxTokens = 128,

    [ValidateRange(1024, 65535)]
    [int]$Port = 46328,

    [ValidatePattern('^http://(localhost|127\.0\.0\.1|\[::1\]):[0-9]+/$')]
    [string]$ComfyUiBaseUrl = 'http://127.0.0.1:8188/'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$startScript = Join-Path $repoRoot 'scripts\start-vllm.ps1'
$stopScript = Join-Path $repoRoot 'scripts\stop-vllm.ps1'
$smokeScript = Join-Path $repoRoot 'scripts\smoke-openai-api.py'
$benchmarkScript = Join-Path $repoRoot 'scripts\benchmark.ps1'
$python = (
    'C:\Dev\Tools\LocalVoiceAgent\runtimes\' +
    'tool-executor\.venv\Scripts\python.exe'
)
$statusRoot = 'E:\Data\LocalVoiceAgent\runtime\status'
$logRoot = 'E:\Data\LocalVoiceAgent\runtime\logs'
$functionalRoot = 'E:\Data\LocalVoiceAgent\runtime\evidence'
$benchmarkRoot = 'E:\Data\LocalVoiceAgent\benchmarks\results'
$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$condition = if ($MtpMode -eq 'on') {
    "12b-exact-mtp-on-s$SpeculativeTokens"
}
else {
    '12b-exact-mtp-off'
}
$launcherMode = if ($MtpMode -eq 'on') { 'on' } else { 'exact-off' }
$servedModel = if ($MtpMode -eq 'on') {
    'gemma4-12b-mtp'
}
else {
    'gemma4-12b-mtp-target-off'
}
$mtpConfig = if ($MtpMode -eq 'on') {
    "tokens=$SpeculativeTokens"
}
else {
    'disabled'
}
$statusPath = Join-Path $statusRoot "vllm-mtp-benchmark-$stamp.json"
$functionalPath = Join-Path (
    $functionalRoot
) "vllm-$condition-functional-$stamp.json"
$benchmarkPath = Join-Path (
    $benchmarkRoot
) "vllm-$condition-$stamp.json"

foreach ($path in @(
    $startScript,
    $stopScript,
    $smokeScript,
    $benchmarkScript,
    $python
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Registered script is unavailable: $path"
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
        mtp_mode = $MtpMode
        functional_evidence = $functionalPath
        benchmark_evidence = $benchmarkPath
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

function Stop-OwnedVllm {
    & powershell.exe `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $stopScript `
        -ExpectedModelSize 12b |
        Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Registered vLLM stop exited $LASTEXITCODE."
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
                Stop-OwnedVllm
            }
            finally {
                $Process.Refresh()
                if (-not $Process.HasExited) {
                    $Process.Kill()
                }
            }
            Write-RunStatus `
                -Phase 'yielded' `
                -Result 'yielded' `
                -Detail (
                    "ComfyUI became active during $Phase; stopped only " +
                    'the owned 12B vLLM process.'
                )
            return $false
        }
        Start-Sleep -Seconds 2
        $Process.Refresh()
    }
    $Process.WaitForExit()
    return $true
}

$previousVllmKey = $env:LVA_VLLM_API_KEY
$previousRuntimeKey = $env:LVA_RUNTIME_API_KEY
$previousSpeculativeTokens = $env:VLLM_SMOKE_SPECULATIVE_TOKENS
$apiKey = (
    [Guid]::NewGuid().ToString('N') +
    [Guid]::NewGuid().ToString('N')
)

try {
    for ($sample = 1; $sample -le 2; $sample += 1) {
        $queue = Get-ComfyUiQueueState
        $freeMemory = Get-FreeGpuMemoryMiB
        if ($queue.busy -or $freeMemory -lt 28500) {
            Write-RunStatus `
                -Phase 'yielded' `
                -Result 'yielded' `
                -Detail (
                    "Shared GPU unavailable: ComfyUI running=$($queue.running), " +
                    "pending=$($queue.pending), processes=" +
                    "$($queue.process_count), free_vram_mib=$freeMemory. " +
                    'No vLLM process was started.'
                )
            exit 20
        }
        if ($sample -eq 1) {
            Start-Sleep -Seconds 3
        }
    }

    $env:LVA_VLLM_API_KEY = $apiKey
    $env:LVA_RUNTIME_API_KEY = $apiKey
    $env:VLLM_SMOKE_SPECULATIVE_TOKENS = [string]$SpeculativeTokens
    Write-RunStatus `
        -Phase 'starting' `
        -Result 'running' `
        -Detail "Starting exact-target vLLM MTP=$MtpMode."

    $startOutput = Join-Path $logRoot "vllm-mtp-start-$stamp.stdout.log"
    $startError = Join-Path $logRoot "vllm-mtp-start-$stamp.stderr.log"
    $start = Start-Process `
        -FilePath 'powershell.exe' `
        -ArgumentList @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-File', $startScript,
            '-ModelSize', '12b',
            '-MtpMode', $launcherMode,
            '-Port', [string]$Port,
            '-StartupTimeoutSeconds', '900'
        ) `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $startOutput `
        -RedirectStandardError $startError
    if (-not (Wait-ChildOrYield -Process $start -Phase 'startup')) {
        exit 21
    }
    $start.WaitForExit()
    $startExitCode = $start.ExitCode
    if ($null -eq $startExitCode) {
        try {
            Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/health" `
                -TimeoutSec 3 |
                Out-Null
            $startExitCode = 0
        }
        catch {
            throw (
                'vLLM launcher exit code was unavailable and the ' +
                'independent health probe failed.'
            )
        }
    }
    if ($startExitCode -ne 0) {
        throw "Registered vLLM startup exited $startExitCode."
    }

    Write-RunStatus `
        -Phase 'functional' `
        -Result 'running' `
        -Detail 'Validating text, tool, schema, and streaming behavior.'
    $smoke = Start-Process `
        -FilePath $python `
        -ArgumentList @(
            $smokeScript,
            '--base-url', "http://127.0.0.1:$Port",
            '--model', $servedModel,
            '--timeout', '300',
            '--skip-thinking',
            '--disable-thinking',
            '--output', $functionalPath,
            '--api-key-env', 'LVA_RUNTIME_API_KEY'
        ) `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput (
            Join-Path $logRoot "vllm-mtp-smoke-$stamp.stdout.log"
        ) `
        -RedirectStandardError (
            Join-Path $logRoot "vllm-mtp-smoke-$stamp.stderr.log"
        )
    if (-not (Wait-ChildOrYield -Process $smoke -Phase 'functional smoke')) {
        exit 22
    }
    $smoke.WaitForExit()
    $smokeExitCode = $smoke.ExitCode
    if (
        $null -eq $smokeExitCode -and
        (Test-Path -LiteralPath $functionalPath -PathType Leaf)
    ) {
        $smokeExitCode = 0
    }
    if ($smokeExitCode -ne 0) {
        throw "Functional smoke exited $smokeExitCode."
    }

    Write-RunStatus `
        -Phase 'benchmarking' `
        -Result 'running' `
        -Detail 'Functional gate passed; running fixed-condition samples.'
    $benchmarkArguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $benchmarkScript,
        '-Runtime', 'vllm',
        '-Condition', $condition,
        '-BaseUrl', "http://127.0.0.1:$Port/",
        '-Model', $servedModel,
        '-ModelRevision', 'b6ed86275a6a5735884e208bfed95b445a684ca2',
        '-Samples', [string]$Samples,
        '-MaxTokens', [string]$MaxTokens,
        '-MtpConfig', $mtpConfig,
        '-OutputPath', $benchmarkPath
    )
    if ($MtpMode -eq 'on') {
        $benchmarkArguments += '-MtpEnabled'
    }
    $benchmark = Start-Process `
        -FilePath 'powershell.exe' `
        -ArgumentList $benchmarkArguments `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput (
            Join-Path $logRoot "vllm-mtp-bench-$stamp.stdout.log"
        ) `
        -RedirectStandardError (
            Join-Path $logRoot "vllm-mtp-bench-$stamp.stderr.log"
        )
    if (-not (Wait-ChildOrYield -Process $benchmark -Phase 'benchmark')) {
        exit 23
    }
    $benchmark.WaitForExit()
    $benchmarkExitCode = $benchmark.ExitCode
    if (
        $null -eq $benchmarkExitCode -and
        (Test-Path -LiteralPath $benchmarkPath -PathType Leaf)
    ) {
        $benchmarkExitCode = 0
    }
    if ($benchmarkExitCode -ne 0) {
        throw "Registered benchmark exited $benchmarkExitCode."
    }

    Stop-OwnedVllm
    $functionalHash = (
        Get-FileHash -LiteralPath $functionalPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $benchmarkHash = (
        Get-FileHash -LiteralPath $benchmarkPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    Write-RunStatus `
        -Phase 'completed' `
        -Result 'passed' `
        -Detail (
            "Functional sha256=$functionalHash; " +
            "benchmark sha256=$benchmarkHash"
        )
    Write-Output "benchmark_status=$statusPath"
    Write-Output "functional_evidence=$functionalPath"
    Write-Output "functional_evidence_sha256=$functionalHash"
    Write-Output "benchmark_evidence=$benchmarkPath"
    Write-Output "benchmark_evidence_sha256=$benchmarkHash"
}
catch {
    try {
        Stop-OwnedVllm
    }
    catch {
        # Preserve the original failure.
    }
    Write-RunStatus `
        -Phase 'failed' `
        -Result 'failed' `
        -Detail $_.Exception.Message
    throw
}
finally {
    $env:LVA_VLLM_API_KEY = $previousVllmKey
    $env:LVA_RUNTIME_API_KEY = $previousRuntimeKey
    $env:VLLM_SMOKE_SPECULATIVE_TOKENS = $previousSpeculativeTokens
}
