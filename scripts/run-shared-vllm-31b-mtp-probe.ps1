[CmdletBinding()]
param(
    [ValidateSet('on', 'off')]
    [string]$MtpMode = 'on',

    [ValidateRange(28, 48)]
    [int]$CpuOffloadGiB = 36,

    [ValidateRange(1024, 65535)]
    [int]$Port = 46326,

    [switch]$RunBenchmark,

    [ValidateRange(1, 10)]
    [int]$Samples = 3,

    [ValidateRange(8, 64)]
    [int]$MaxTokens = 16,

    [ValidatePattern('^http://(localhost|127\.0\.0\.1|\[::1\]):[0-9]+/$')]
    [string]$ComfyUiBaseUrl = 'http://127.0.0.1:8188/'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$startScript = (
    '/mnt/c/Dev/Repos/local-voice-agent/scripts/' +
    'start-vllm-31b-mtp-probe.sh'
)
$stopScript = Join-Path $repoRoot 'scripts\stop-vllm.ps1'
$smokeScript = Join-Path $repoRoot 'scripts\smoke-openai-api.py'
$benchmarkScript = Join-Path $repoRoot 'scripts\benchmark.ps1'
$python = (
    'C:\Dev\Tools\LocalVoiceAgent\runtimes\' +
    'tool-executor\.venv\Scripts\python.exe'
)
$statusRoot = 'E:\Data\LocalVoiceAgent\runtime\status'
$logRoot = 'E:\Data\LocalVoiceAgent\runtime\logs'
$evidenceRoot = 'E:\Data\LocalVoiceAgent\runtime\evidence'
$benchmarkRoot = 'E:\Data\LocalVoiceAgent\benchmarks\results'
$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$runStatus = Join-Path $statusRoot "vllm-31b-mtp-probe-$stamp.json"
$condition = if ($MtpMode -eq 'on') {
    '31b-exact-mtp-on-s1'
}
else {
    '31b-exact-mtp-off'
}
$launcherMode = if ($MtpMode -eq 'on') { 'on' } else { 'exact-off' }
$servedModel = if ($MtpMode -eq 'on') {
    'gemma4-31b-mtp'
}
else {
    'gemma4-31b-mtp-target-off'
}
$mtpConfig = if ($MtpMode -eq 'on') {
    "tokens=1,cpu_offload_gib=$CpuOffloadGiB"
}
else {
    "disabled,cpu_offload_gib=$CpuOffloadGiB"
}
$evidence = Join-Path $evidenceRoot "vllm-$condition-functional-$stamp.json"
$benchmarkEvidence = Join-Path (
    $benchmarkRoot
) "vllm-$condition-$stamp.json"

foreach ($path in @(
    $stopScript,
    $smokeScript,
    $benchmarkScript,
    $python
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Registered probe dependency is unavailable: $path"
    }
}

function Write-ProbeStatus {
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
        cpu_offload_gib = $CpuOffloadGiB
        evidence = $evidence
        benchmark_evidence = if ($RunBenchmark) {
            $benchmarkEvidence
        }
        else {
            $null
        }
        updated_at = [DateTimeOffset]::Now.ToString('o')
    }
    $temporary = "$runStatus.tmp"
    $payload |
        ConvertTo-Json |
        Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $runStatus -Force
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

function Stop-OwnedProbe {
    & powershell.exe `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $stopScript `
        -ExpectedModelSize 31b |
        Out-Null
    $stopExitCode = $LASTEXITCODE
    if ($stopExitCode -eq 0) {
        return
    }

    # A large offloaded process can cross the stop script's 30-second
    # boundary while still completing its requested TERM shutdown. Confirm
    # both ownership state and listener closure before treating that race as
    # a stop failure.
    $pidPath = (
        '/home/kutae/.local/share/local-voice-agent/run/vllm.pid'
    )
    for ($attempt = 1; $attempt -le 30; $attempt += 1) {
        & wsl.exe -d Ubuntu -- test -f $pidPath
        $pidExists = $LASTEXITCODE -eq 0
        $healthy = $false
        try {
            Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/health" `
                -TimeoutSec 1 |
                Out-Null
            $healthy = $true
        }
        catch {
            $healthy = $false
        }
        if (-not $pidExists -and -not $healthy) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Registered vLLM stop exited $stopExitCode and remained active."
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
                Stop-OwnedProbe
            }
            finally {
                $Process.Refresh()
                if (-not $Process.HasExited) {
                    $Process.Kill()
                }
            }
            Write-ProbeStatus `
                -Phase 'yielded' `
                -Result 'yielded' `
                -Detail (
                    "ComfyUI became active during $Phase " +
                    "(running=$($queue.running), pending=$($queue.pending)); " +
                    'stopped only owned 31B vLLM.'
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
$previousProbePort = $env:LVA_VLLM_PROBE_PORT
$previousOffload = $env:LVA_VLLM_PROBE_CPU_OFFLOAD_GB
$previousMtpMode = $env:LVA_VLLM_PROBE_MTP_MODE
$previousTimeout = $env:LVA_VLLM_PROBE_STARTUP_TIMEOUT_SECONDS
$previousWslEnv = $env:WSLENV
$apiKey = (
    [Guid]::NewGuid().ToString('N') +
    [Guid]::NewGuid().ToString('N')
)

try {
    for ($sample = 1; $sample -le 2; $sample += 1) {
        $queue = Get-ComfyUiQueueState
        $freeMemory = Get-FreeGpuMemoryMiB
        if ($queue.busy -or $freeMemory -lt 28500) {
            Write-ProbeStatus `
                -Phase 'yielded' `
                -Result 'yielded' `
                -Detail (
                    "Shared GPU unavailable: ComfyUI running=" +
                    "$($queue.running), pending=$($queue.pending), " +
                    "processes=$($queue.process_count), " +
                    "free_vram_mib=$freeMemory. No vLLM process was started."
                )
            exit 20
        }
        if ($sample -eq 1) {
            Start-Sleep -Seconds 3
        }
    }

    $env:LVA_VLLM_API_KEY = $apiKey
    $env:LVA_RUNTIME_API_KEY = $apiKey
    $env:LVA_VLLM_PROBE_PORT = [string]$Port
    $env:LVA_VLLM_PROBE_CPU_OFFLOAD_GB = [string]$CpuOffloadGiB
    $env:LVA_VLLM_PROBE_MTP_MODE = $launcherMode
    $env:LVA_VLLM_PROBE_STARTUP_TIMEOUT_SECONDS = '1200'
    $bridgeNames = @(
        'LVA_VLLM_API_KEY',
        'LVA_VLLM_PROBE_PORT',
        'LVA_VLLM_PROBE_CPU_OFFLOAD_GB',
        'LVA_VLLM_PROBE_MTP_MODE',
        'LVA_VLLM_PROBE_STARTUP_TIMEOUT_SECONDS'
    )
    $existingBridge = @(
        $previousWslEnv -split ':' |
            Where-Object { $_ -and $_ -notmatch '^LVA_VLLM_' }
    )
    $env:WSLENV = (
        @($bridgeNames | ForEach-Object { "$_/u" }) + $existingBridge
    ) -join ':'

    Write-ProbeStatus `
        -Phase 'starting' `
        -Result 'running' `
        -Detail "Starting exact 31B MTP=$MtpMode feasibility probe."
    $startOutput = Join-Path $logRoot "vllm-31b-probe-$stamp.stdout.log"
    $startError = Join-Path $logRoot "vllm-31b-probe-$stamp.stderr.log"
    $start = Start-Process `
        -FilePath 'wsl.exe' `
        -ArgumentList @('-d', 'Ubuntu', '--', 'bash', $startScript) `
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
                '31B exact launcher exit code was unavailable and the ' +
                'independent health probe failed.'
            )
        }
    }
    if ($startExitCode -ne 0) {
        throw "31B exact startup exited $startExitCode."
    }

    Write-ProbeStatus `
        -Phase 'smoke' `
        -Result 'running' `
        -Detail 'Runtime is healthy; validating text, tool, schema, and stream.'
    $smokeOutput = Join-Path $logRoot "vllm-31b-smoke-$stamp.stdout.log"
    $smokeError = Join-Path $logRoot "vllm-31b-smoke-$stamp.stderr.log"
    $smokeArguments = @(
        $smokeScript,
        '--base-url', "http://127.0.0.1:$Port",
        '--model', $servedModel,
        '--timeout', '600',
        '--skip-thinking',
        '--disable-thinking',
        '--output', $evidence,
        '--api-key-env', 'LVA_RUNTIME_API_KEY'
    )
    $smoke = Start-Process `
        -FilePath $python `
        -ArgumentList $smokeArguments `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $smokeOutput `
        -RedirectStandardError $smokeError
    if (-not (Wait-ChildOrYield -Process $smoke -Phase 'smoke')) {
        exit 22
    }
    $smoke.WaitForExit()
    $smokeExitCode = $smoke.ExitCode
    if (
        $null -eq $smokeExitCode -and
        (Test-Path -LiteralPath $evidence -PathType Leaf)
    ) {
        $smokeExitCode = 0
    }
    if ($smokeExitCode -ne 0) {
        throw "31B exact smoke exited $smokeExitCode."
    }

    if ($RunBenchmark) {
        Write-ProbeStatus `
            -Phase 'benchmarking' `
            -Result 'running' `
            -Detail 'Functional gate passed; running bounded 31B samples.'
        $benchmarkArguments = @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-File', $benchmarkScript,
            '-Runtime', 'vllm',
            '-Condition', $condition,
            '-BaseUrl', "http://127.0.0.1:$Port/",
            '-Model', $servedModel,
            '-ModelRevision', '1e4d8beecacb8b7590c1d8bedd7335f687bf311f',
            '-Samples', [string]$Samples,
            '-MaxTokens', [string]$MaxTokens,
            '-MtpConfig',
            $mtpConfig,
            '-OutputPath', $benchmarkEvidence
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
                Join-Path $logRoot "vllm-31b-bench-$stamp.stdout.log"
            ) `
            -RedirectStandardError (
                Join-Path $logRoot "vllm-31b-bench-$stamp.stderr.log"
            )
        if (-not (
            Wait-ChildOrYield -Process $benchmark -Phase 'benchmark'
        )) {
            exit 23
        }
        $benchmark.WaitForExit()
        $benchmarkExitCode = $benchmark.ExitCode
        if (
            $null -eq $benchmarkExitCode -and
            (Test-Path -LiteralPath $benchmarkEvidence -PathType Leaf)
        ) {
            $benchmarkExitCode = 0
        }
        if ($benchmarkExitCode -ne 0) {
            throw "31B benchmark exited $benchmarkExitCode."
        }
    }

    Stop-OwnedProbe
    $hash = (
        Get-FileHash -LiteralPath $evidence -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    Write-ProbeStatus `
        -Phase 'completed' `
        -Result 'passed' `
        -Detail "31B exact probe completed; sha256=$hash"
    Write-Output "probe_status=$runStatus"
    Write-Output "probe_evidence=$evidence"
    Write-Output "probe_evidence_sha256=$hash"
    if ($RunBenchmark) {
        $benchmarkHash = (
            Get-FileHash -LiteralPath $benchmarkEvidence -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        Write-Output "benchmark_evidence=$benchmarkEvidence"
        Write-Output "benchmark_evidence_sha256=$benchmarkHash"
    }
}
catch {
    try {
        Stop-OwnedProbe
    }
    catch {
        # Preserve the original probe failure.
    }
    Write-ProbeStatus `
        -Phase 'failed' `
        -Result 'failed' `
        -Detail $_.Exception.Message
    throw
}
finally {
    $env:LVA_VLLM_API_KEY = $previousVllmKey
    $env:LVA_RUNTIME_API_KEY = $previousRuntimeKey
    $env:LVA_VLLM_PROBE_PORT = $previousProbePort
    $env:LVA_VLLM_PROBE_CPU_OFFLOAD_GB = $previousOffload
    $env:LVA_VLLM_PROBE_MTP_MODE = $previousMtpMode
    $env:LVA_VLLM_PROBE_STARTUP_TIMEOUT_SECONDS = $previousTimeout
    $env:WSLENV = $previousWslEnv
}
