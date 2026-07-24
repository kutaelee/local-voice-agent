[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$keyPath = 'E:\Data\LocalVoiceAgent\secrets\vllm-api-key'
$started = $false
$previousKey = $env:LVA_VLLM_API_KEY
$previousWslEnv = $env:WSLENV

try {
    if (-not $env:LVA_VLLM_API_KEY) {
        if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf)) {
            throw "vLLM secret file is unavailable: $keyPath"
        }
        $env:LVA_VLLM_API_KEY = [System.IO.File]::ReadAllText($keyPath).Trim()
    }
    if ($env:LVA_VLLM_API_KEY.Length -lt 32) {
        throw 'The vLLM API key must contain at least 32 characters.'
    }

    & "$repoRoot\scripts\start-vllm.ps1" `
        -ModelSize 12b `
        -MtpMode off `
        -Port 46322 `
        -StartupTimeoutSeconds 600
    $started = $true

    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss.fffffffZ')
    $env:LVA_SALON_SMOKE_OUTPUT = (
        "/mnt/e/Data/LocalVoiceAgent/runtime/evidence/salon/" +
        "salon-llm-smoke-$stamp.json"
    )
    $entries = @(
        $previousWslEnv -split ':' |
            Where-Object {
                $_ -and
                $_ -notmatch '^LVA_VLLM_API_KEY' -and
                $_ -notmatch '^LVA_SALON_SMOKE_OUTPUT'
            }
    )
    $env:WSLENV = (
        @('LVA_VLLM_API_KEY/u', 'LVA_SALON_SMOKE_OUTPUT/u') + $entries
    ) -join ':'

    & wsl.exe -d Ubuntu -- bash -lc (
        'cd /mnt/c/Dev/Repos/local-voice-agent && ' +
        'PYTHONPATH=/mnt/c/Dev/Repos/local-voice-agent/apps/pc-server/src ' +
        '/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv/bin/python ' +
        'scripts/smoke-salon-llm.py --output "$LVA_SALON_SMOKE_OUTPUT"'
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Salon LLM smoke failed with exit code $LASTEXITCODE."
    }
    Write-Output "Salon LLM evidence: $env:LVA_SALON_SMOKE_OUTPUT"
}
finally {
    if ($started) {
        & wsl.exe -d Ubuntu -- bash `
            /mnt/c/Dev/Repos/local-voice-agent/scripts/stop-vllm.sh
    }
    if ($null -eq $previousKey) {
        Remove-Item Env:LVA_VLLM_API_KEY -ErrorAction SilentlyContinue
    }
    else {
        $env:LVA_VLLM_API_KEY = $previousKey
    }
    Remove-Item Env:LVA_SALON_SMOKE_OUTPUT -ErrorAction SilentlyContinue
    $env:WSLENV = $previousWslEnv
}
