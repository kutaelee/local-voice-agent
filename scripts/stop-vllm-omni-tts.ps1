[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$gpuq = 'C:\Dev\Tools\CodexCLI\gpuq.cmd'
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\vllm-omni-tts.json'

if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
    Write-Output 'No registered vLLM-Omni TTS reservation exists.'
    exit 0
}
$registered = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
$jobId = [Guid]::Empty
if (
    $registered.component -ne 'vllm-omni-tts' -or
    -not [Guid]::TryParse([string]$registered.gpuq_job_id, [ref]$jobId)
) {
    throw 'Registered vLLM-Omni TTS status is invalid.'
}

$scheduler = & $gpuq status | ConvertFrom-Json
$pending = @($scheduler.jobs.queued) + @($scheduler.jobs.active)
$matching = @($pending | Where-Object { $_.id -eq $jobId.ToString() })
if ($matching.Count -eq 0) {
    Write-Output 'Registered vLLM-Omni TTS reservation is already inactive.'
    exit 0
}
if ($matching.Count -ne 1) {
    throw 'vLLM-Omni TTS reservation identity is ambiguous.'
}
& $gpuq cancel $jobId.ToString() | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'vLLM-Omni TTS reservation cancellation failed.'
}
$registered.state = 'cancel_requested'
$registered | Add-Member `
    -NotePropertyName stop_requested_at `
    -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o') `
    -Force
$registered | ConvertTo-Json |
    Set-Content -LiteralPath $statusPath -Encoding utf8
Write-Output 'vLLM-Omni TTS reservation cancellation requested.'
