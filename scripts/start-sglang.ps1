[CmdletBinding()]
param(
    [ValidateSet('12b', '31b')]
    [string]$ModelSize = '12b',

    [ValidateSet('base', 'mtp', 'mtp-target-off')]
    [string]$Mode = 'base',

    [ValidateRange(1, 5)]
    [int]$SpeculativeSteps = 1,

    [ValidateRange(0, 48)]
    [int]$MtpCpuOffloadGiB = 4,

    [ValidateRange(1024, 65535)]
    [int]$Port = 8768,

    [ValidateRange(60, 900)]
    [int]$StartupTimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'

if (-not $env:LVA_SGLANG_API_KEY -or $env:LVA_SGLANG_API_KEY.Length -lt 32) {
    throw 'Set LVA_SGLANG_API_KEY to a secret of at least 32 characters.'
}
if ($ModelSize -eq '31b' -and $Mode -eq 'base') {
    throw (
        'SGLang 0.5.15.post1 cannot repack the pinned Gemma 4 31B W4A16 ' +
        'checkpoint: output width 8608 is not divisible by the Marlin tile ' +
        'width 64. Use the registered vLLM 31B profile.'
    )
}

$scriptPath = 'C:\Dev\Repos\local-voice-agent\scripts\start-sglang.sh'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "SGLang start script is unavailable: $scriptPath"
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
$minimumFreeMemory = if ($ModelSize -eq '31b' -or $Mode -ne 'base') {
    28500
}
else {
    22000
}
if ($freeMemory -lt $minimumFreeMemory) {
    throw (
        "GPU reservation declined: mode=$Mode requires $minimumFreeMemory MiB free; " +
        "observed $freeMemory MiB. The concurrent workload was preserved."
    )
}

$bridgeNames = @(
    'LVA_SGLANG_API_KEY',
    'LVA_SGLANG_MODEL_SIZE',
    'LVA_SGLANG_MODE',
    'LVA_SGLANG_SPECULATIVE_STEPS',
    'LVA_SGLANG_MTP_CPU_OFFLOAD_GIB',
    'LVA_SGLANG_PORT',
    'LVA_SGLANG_STARTUP_TIMEOUT_SECONDS'
)
$previousValues = @{}
foreach ($name in $bridgeNames) {
    $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$previousWslEnv = $env:WSLENV

try {
    $env:LVA_SGLANG_MODEL_SIZE = $ModelSize
    $env:LVA_SGLANG_MODE = $Mode
    $env:LVA_SGLANG_SPECULATIVE_STEPS = [string]$SpeculativeSteps
    $env:LVA_SGLANG_MTP_CPU_OFFLOAD_GIB = [string]$MtpCpuOffloadGiB
    $env:LVA_SGLANG_PORT = [string]$Port
    $env:LVA_SGLANG_STARTUP_TIMEOUT_SECONDS = [string]$StartupTimeoutSeconds
    $existingBridgeEntries = @(
        $previousWslEnv -split ':' |
            Where-Object { $_ -and $_ -notmatch '^LVA_SGLANG_' }
    )
    $env:WSLENV = (@($bridgeNames | ForEach-Object { "$_/u" }) + $existingBridgeEntries) -join ':'

    & wsl.exe -d Ubuntu -- bash /mnt/c/Dev/Repos/local-voice-agent/scripts/start-sglang.sh
    if ($LASTEXITCODE -ne 0) {
        throw "SGLang startup failed with exit code $LASTEXITCODE."
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
