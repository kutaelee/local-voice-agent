[CmdletBinding()]
param(
    [ValidateSet('any', '12b', '31b')]
    [string]$ExpectedModelSize = 'any'
)

$ErrorActionPreference = 'Stop'

$scriptPath = 'C:\Dev\Repos\local-voice-agent\scripts\stop-vllm.sh'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "vLLM stop script is unavailable: $scriptPath"
}

$previousExpected = $env:LVA_VLLM_EXPECTED_MODEL_SIZE
$previousWslEnv = $env:WSLENV
try {
    if ($ExpectedModelSize -eq 'any') {
        Remove-Item Env:LVA_VLLM_EXPECTED_MODEL_SIZE -ErrorAction SilentlyContinue
    }
    else {
        $env:LVA_VLLM_EXPECTED_MODEL_SIZE = $ExpectedModelSize
    }
    $existingBridgeEntries = @(
        $previousWslEnv -split ':' |
            Where-Object {
                $_ -and $_ -notmatch '^LVA_VLLM_EXPECTED_MODEL_SIZE'
            }
    )
    $env:WSLENV = (
        @('LVA_VLLM_EXPECTED_MODEL_SIZE/u') + $existingBridgeEntries
    ) -join ':'

    & wsl.exe -d Ubuntu -- bash `
        /mnt/c/Dev/Repos/local-voice-agent/scripts/stop-vllm.sh
    if ($LASTEXITCODE -ne 0) {
        throw "vLLM stop failed with exit code $LASTEXITCODE."
    }
}
finally {
    if ($null -eq $previousExpected) {
        Remove-Item Env:LVA_VLLM_EXPECTED_MODEL_SIZE -ErrorAction SilentlyContinue
    }
    else {
        $env:LVA_VLLM_EXPECTED_MODEL_SIZE = $previousExpected
    }
    $env:WSLENV = $previousWslEnv
}
