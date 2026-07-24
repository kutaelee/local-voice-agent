[CmdletBinding()]
param(
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

if (-not (Test-Path -LiteralPath $gpuq -PathType Leaf)) {
    throw "gpuq is unavailable: $gpuq"
}
if (-not (Test-Path -LiteralPath "$repoRoot\scripts\run-gpu-voice-stack.sh" -PathType Leaf)) {
    throw 'GPU voice supervisor is unavailable.'
}

$existing = @(
    wsl.exe -d Ubuntu -- pgrep -f "^bash $supervisor$"
)
if ($LASTEXITCODE -eq 0 -and $existing.Count -gt 0) {
    throw 'The registered GPU voice supervisor is already running.'
}

$jobId = (
    & $gpuq run `
        --vram 22000 `
        --eta 3600 `
        --priority $Priority `
        --max-runtime $MaxRuntimeSeconds `
        --agent local-voice-agent `
        --workload local-voice-agent-interactive-qa `
        --cwd $repoRoot `
        -- `
        wsl.exe -d Ubuntu -- bash $supervisor
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
    requested_vram_mib = 22000
    priority = $Priority
    max_runtime_seconds = $MaxRuntimeSeconds
    submitted_at = (Get-Date).ToUniversalTime().ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8

Write-Output $jobId
