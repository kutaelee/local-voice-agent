[CmdletBinding()]
param(
    [ValidateSet('e4b', '12b')]
    [string]$ModelSize = 'e4b',

    [ValidateSet('0.6b', '1.7b')]
    [string]$TtsSize = '1.7b',

    [ValidateRange(0, 100)]
    [int]$Priority = 80,

    [ValidateRange(600, 86400)]
    [int]$MaxRuntimeSeconds = 43200
)

$ErrorActionPreference = 'Stop'
$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$gpuq = 'C:\Dev\Tools\CodexCLI\gpuq.cmd'
$supervisor = '/mnt/c/Dev/Repos/local-voice-agent/scripts/run-gpu-voice-stack.sh'
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\gpu-voice-stack.json'
$requestedVramMiB = if ($ModelSize -eq 'e4b') {
    if ($TtsSize -eq '1.7b') { 21000 } else { 17000 }
}
else {
    if ($TtsSize -eq '1.7b') { 29000 } else { 25000 }
}

if (-not (Test-Path -LiteralPath $gpuq -PathType Leaf)) {
    throw "gpuq is unavailable: $gpuq"
}
if (-not (Test-Path -LiteralPath "$repoRoot\scripts\run-gpu-voice-stack.sh" -PathType Leaf)) {
    throw 'GPU voice supervisor is unavailable.'
}

if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
    try {
        $registered = Get-Content -LiteralPath $statusPath -Raw |
            ConvertFrom-Json
        $registeredJobId = [Guid]::Empty
        if (
            $registered.component -eq 'gpu-voice-stack' -and
            [Guid]::TryParse(
                [string]$registered.gpuq_job_id,
                [ref]$registeredJobId
            )
        ) {
            $scheduler = & $gpuq status | ConvertFrom-Json
            $pending = @($scheduler.jobs.queued) + @($scheduler.jobs.active)
            $matching = @(
                $pending |
                    Where-Object {
                        $_.id -eq $registeredJobId.ToString()
                    }
            )
            if ($matching.Count -eq 1) {
                Write-Output $registeredJobId.ToString()
                exit 0
            }
        }
    }
    catch {
        throw 'Registered GPU voice stack status is invalid.'
    }
}

$existing = @(
    wsl.exe -d Ubuntu -- pgrep -f "^bash $supervisor$"
)
if ($LASTEXITCODE -eq 0 -and $existing.Count -gt 0) {
    throw 'The registered GPU voice supervisor is already running.'
}

$jobId = (
    & $gpuq run `
        --vram $requestedVramMiB `
        --eta 3600 `
        --priority $Priority `
        --max-runtime $MaxRuntimeSeconds `
        --agent local-voice-agent `
        --workload local-voice-agent-interactive-qa `
        --cwd $repoRoot `
        -- `
        wsl.exe -d Ubuntu -- env `
            "LVA_VOICE_LLM_SIZE=$ModelSize" `
            "LVA_QWEN3_TTS_SIZE=$TtsSize" `
            bash $supervisor
).Trim()
$parsedJobId = [Guid]::Empty
if (-not [Guid]::TryParse($jobId, [ref]$parsedJobId)) {
    throw 'gpuq did not return a valid job identifier.'
}

New-Item -ItemType Directory -Path (Split-Path -Parent $statusPath) -Force |
    Out-Null
[ordered]@{
    schema_version = '1.0'
    component = 'gpu-voice-stack'
    state = 'submitted'
    gpuq_job_id = $jobId
    workload = 'local-voice-agent-interactive-qa'
    model_size = $ModelSize
    tts_size = $TtsSize
    requested_vram_mib = $requestedVramMiB
    priority = $Priority
    max_runtime_seconds = $MaxRuntimeSeconds
    submitted_at = (Get-Date).ToUniversalTime().ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8

Write-Output $jobId
