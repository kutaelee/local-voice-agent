[CmdletBinding()]
param(
    [ValidateRange(28, 48)]
    [int]$CpuOffloadGiB = 36,

    [ValidateRange(1024, 65535)]
    [int]$Port = 8767
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
$python = (
    'C:\Dev\Tools\LocalVoiceAgent\runtimes\' +
    'tool-executor\.venv\Scripts\python.exe'
)
$statusRoot = 'E:\Data\LocalVoiceAgent\runtime\status'
$logRoot = 'E:\Data\LocalVoiceAgent\runtime\logs'
$evidenceRoot = 'E:\Data\LocalVoiceAgent\runtime\evidence'
$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$runStatus = Join-Path $statusRoot "vllm-31b-mtp-probe-$stamp.json"
$evidence = Join-Path $evidenceRoot "vllm-31b-mtp-probe-$stamp.json"

foreach ($path in @($stopScript, $smokeScript, $python)) {
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
        cpu_offload_gib = $CpuOffloadGiB
        evidence = $evidence
        updated_at = [DateTimeOffset]::Now.ToString('o')
    }
    $temporary = "$runStatus.tmp"
    $payload |
        ConvertTo-Json |
        Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $runStatus -Force
}

function Get-ComfyUiProcessCount {
    return @(
        Get-CimInstance Win32_Process |
            Where-Object {
                $_.CommandLine -and
                $_.CommandLine -match (
                    '(?i)[\\/]AI[\\/]Apps[\\/]ComfyUI[\\/]main\.py'
                )
            }
    ).Count
}

function Stop-OwnedProbe {
    & powershell.exe `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $stopScript `
        -ExpectedModelSize 31b |
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
        $comfyCount = Get-ComfyUiProcessCount
        if ($comfyCount -gt 0) {
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
                    "ComfyUI appeared during $Phase " +
                    "(processes=$comfyCount); stopped only owned 31B vLLM."
                )
            return $false
        }
        Start-Sleep -Seconds 2
        $Process.Refresh()
    }
    return $true
}

$previousVllmKey = $env:LVA_VLLM_API_KEY
$previousRuntimeKey = $env:LVA_RUNTIME_API_KEY
$previousProbePort = $env:LVA_VLLM_PROBE_PORT
$previousOffload = $env:LVA_VLLM_PROBE_CPU_OFFLOAD_GB
$previousTimeout = $env:LVA_VLLM_PROBE_STARTUP_TIMEOUT_SECONDS
$previousWslEnv = $env:WSLENV
$apiKey = (
    [Guid]::NewGuid().ToString('N') +
    [Guid]::NewGuid().ToString('N')
)

try {
    for ($sample = 1; $sample -le 2; $sample += 1) {
        $comfyCount = Get-ComfyUiProcessCount
        if ($comfyCount -gt 0) {
            Write-ProbeStatus `
                -Phase 'yielded' `
                -Result 'yielded' `
                -Detail (
                    "ComfyUI is present (processes=$comfyCount); no vLLM " +
                    'process was started.'
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
    $env:LVA_VLLM_PROBE_STARTUP_TIMEOUT_SECONDS = '1200'
    $bridgeNames = @(
        'LVA_VLLM_API_KEY',
        'LVA_VLLM_PROBE_PORT',
        'LVA_VLLM_PROBE_CPU_OFFLOAD_GB',
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
        -Detail 'Starting exact 31B target/assistant feasibility probe.'
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
    if ($start.ExitCode -ne 0) {
        throw "31B MTP startup exited $($start.ExitCode)."
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
        '--model', 'gemma4-31b-mtp',
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
    if ($smoke.ExitCode -ne 0) {
        throw "31B MTP smoke exited $($smoke.ExitCode)."
    }

    Stop-OwnedProbe
    $hash = (
        Get-FileHash -LiteralPath $evidence -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    Write-ProbeStatus `
        -Phase 'completed' `
        -Result 'passed' `
        -Detail "31B MTP probe completed; sha256=$hash"
    Write-Output "probe_status=$runStatus"
    Write-Output "probe_evidence=$evidence"
    Write-Output "probe_evidence_sha256=$hash"
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
    $env:LVA_VLLM_PROBE_STARTUP_TIMEOUT_SECONDS = $previousTimeout
    $env:WSLENV = $previousWslEnv
}
