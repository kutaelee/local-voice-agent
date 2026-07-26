[CmdletBinding()]
param(
    [ValidateRange(0, 100)]
    [int]$Priority = 60,

    [ValidateRange(600, 86400)]
    [int]$MaxRuntimeSeconds = 14400
)

$ErrorActionPreference = 'Stop'
$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$gpuq = 'C:\Dev\Tools\CodexCLI\gpuq.cmd'
$runner = '/mnt/c/Dev/Repos/local-voice-agent/scripts/run-vllm-omni-tts.sh'
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\vllm-omni-tts.json'

if (-not (Test-Path -LiteralPath $gpuq -PathType Leaf)) {
    throw "gpuq is unavailable: $gpuq"
}
if (-not (Test-Path -LiteralPath "$repoRoot\scripts\run-vllm-omni-tts.sh" -PathType Leaf)) {
    throw 'vLLM-Omni TTS runner is unavailable.'
}

$scheduler = & $gpuq status | ConvertFrom-Json
if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
    $registered = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $jobId = [Guid]::Empty
    if (
        $registered.component -eq 'vllm-omni-tts' -and
        [Guid]::TryParse([string]$registered.gpuq_job_id, [ref]$jobId)
    ) {
        $pending = @($scheduler.jobs.queued) + @($scheduler.jobs.active)
        if (@($pending | Where-Object { $_.id -eq $jobId.ToString() }).Count -eq 1) {
            Write-Output $jobId.ToString()
            exit 0
        }
    }
}

$jobIdText = (
    & $gpuq run `
        --vram 20000 `
        --eta 1800 `
        --priority $Priority `
        --max-runtime $MaxRuntimeSeconds `
        --agent local-voice-agent `
        --workload local-voice-agent-vllm-omni-tts-poc `
        --cwd $repoRoot `
        -- `
        wsl.exe -d Ubuntu -- bash $runner
).Trim()
$parsedJobId = [Guid]::Empty
if (-not [Guid]::TryParse($jobIdText, [ref]$parsedJobId)) {
    throw 'gpuq did not return a valid job identifier.'
}

New-Item -ItemType Directory -Path (Split-Path -Parent $statusPath) -Force |
    Out-Null
[ordered]@{
    schema_version = '1.0'
    component = 'vllm-omni-tts'
    state = 'submitted'
    gpuq_job_id = $jobIdText
    workload = 'local-voice-agent-vllm-omni-tts-poc'
    port = 46329
    requested_vram_mib = 20000
    priority = $Priority
    max_runtime_seconds = $MaxRuntimeSeconds
    submitted_at = (Get-Date).ToUniversalTime().ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8

Write-Output $jobIdText
