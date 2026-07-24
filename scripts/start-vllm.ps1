[CmdletBinding()]
param(
    [ValidateSet('12b', '31b')]
    [string]$ModelSize = '12b',

    [ValidateSet('off', 'exact-off', 'on')]
    [string]$MtpMode = 'off',

    [ValidateRange(1024, 65535)]
    [int]$Port = 46322,

    [ValidateRange(60, 900)]
    [int]$StartupTimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'

if (-not $env:LVA_VLLM_API_KEY) {
    $keyFile = 'E:\Data\LocalVoiceAgent\secrets\vllm-api-key'
    if (Test-Path -LiteralPath $keyFile -PathType Leaf) {
        $env:LVA_VLLM_API_KEY = [System.IO.File]::ReadAllText($keyFile).Trim()
    }
}
if (-not $env:LVA_VLLM_API_KEY -or $env:LVA_VLLM_API_KEY.Length -lt 32) {
    throw 'Set LVA_VLLM_API_KEY to a secret of at least 32 characters.'
}
if ($ModelSize -eq '31b' -and $MtpMode -eq 'on') {
    throw '31B MTP is disabled until its runtime validation gate passes.'
}

$scriptPath = 'C:\Dev\Repos\local-voice-agent\scripts\start-vllm.sh'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "vLLM start script is unavailable: $scriptPath"
}

$freeMemoryText = (
    nvidia-smi `
        --query-gpu=memory.free `
        --format=csv,noheader,nounits |
        Select-Object -First 1
).Trim()
$freeMemory = 0
if (-not [int]::TryParse($freeMemoryText, [ref]$freeMemory)) {
    throw 'Unable to measure free GPU memory.'
}
$minimumFreeMemory = if (
    $ModelSize -eq '31b' -or
    $MtpMode -in @('exact-off', 'on')
) {
    if ($ModelSize -eq '31b') { 27000 } else { 28500 }
}
else {
    22000
}
if ($freeMemory -lt $minimumFreeMemory) {
    throw (
        "GPU reservation declined: vLLM $ModelSize MTP=$MtpMode requires " +
        "$minimumFreeMemory MiB free; " +
        "observed $freeMemory MiB. The concurrent workload was preserved."
    )
}

$bridgeNames = @(
    'LVA_VLLM_API_KEY',
    'LVA_VLLM_MODEL_SIZE',
    'LVA_VLLM_MTP_MODE',
    'LVA_VLLM_PORT',
    'LVA_VLLM_STARTUP_TIMEOUT_SECONDS'
)
$previousValues = @{}
foreach ($name in $bridgeNames) {
    $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$previousWslEnv = $env:WSLENV

try {
    $env:LVA_VLLM_MODEL_SIZE = $ModelSize
    $env:LVA_VLLM_MTP_MODE = $MtpMode
    $env:LVA_VLLM_PORT = [string]$Port
    $env:LVA_VLLM_STARTUP_TIMEOUT_SECONDS = [string]$StartupTimeoutSeconds
    $existingBridgeEntries = @(
        $previousWslEnv -split ':' |
            Where-Object { $_ -and $_ -notmatch '^LVA_VLLM_' }
    )
    $env:WSLENV = (@($bridgeNames | ForEach-Object { "$_/u" }) + $existingBridgeEntries) -join ':'

    & wsl.exe -d Ubuntu -- bash /mnt/c/Dev/Repos/local-voice-agent/scripts/start-vllm.sh
    if ($LASTEXITCODE -ne 0) {
        throw "vLLM startup failed with exit code $LASTEXITCODE."
    }
}
finally {
    foreach ($name in $bridgeNames) {
        if ($null -eq $previousValues[$name]) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable(
                $name,
                [string]$previousValues[$name],
                'Process'
            )
        }
    }
    $env:WSLENV = $previousWslEnv
}
