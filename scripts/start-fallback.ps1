[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8769,

    [switch]$CpuOnly,

    [ValidateRange(60, 900)]
    [int]$StartupTimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'

$runtimeRoot = 'C:\Dev\Tools\LocalVoiceAgent\runtimes\llama.cpp-b10092'
$serverPath = Join-Path $runtimeRoot 'llama-server.exe'
$runtimeManifestPath = Join-Path $runtimeRoot 'installed-manifest.json'
$modelPath = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\12b\fallback-gguf\d72ee27227da2ba16c725180ddd507ee96208d23\gemma-4-12B-it-Q4_0.gguf'
$modelSize = 7219673216
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\fallback-server.json'
$logRoot = 'E:\Data\LocalVoiceAgent\runtime\logs'

if (-not $env:LVA_FALLBACK_API_KEY -or $env:LVA_FALLBACK_API_KEY.Length -lt 32) {
    throw 'Set LVA_FALLBACK_API_KEY to a secret of at least 32 characters.'
}
if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) {
    throw "Pinned llama.cpp runtime is unavailable: $serverPath"
}
if (-not (Test-Path -LiteralPath $runtimeManifestPath -PathType Leaf)) {
    throw "llama.cpp installation manifest is unavailable: $runtimeManifestPath"
}
if (-not (Test-Path -LiteralPath $modelPath -PathType Leaf)) {
    throw "Pinned fallback model is unavailable: $modelPath"
}
if ((Get-Item -LiteralPath $modelPath).Length -ne $modelSize) {
    throw 'Pinned fallback model size does not match its manifest.'
}

if (-not $CpuOnly) {
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
    if ($freeMemory -lt 12000) {
        throw (
            "GPU fallback requires 12000 MiB free; observed $freeMemory MiB. " +
            'Use -CpuOnly or wait for the concurrent workload.'
        )
    }
}

if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
    $existingStatus = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$existingStatus.pid)" -ErrorAction SilentlyContinue
    if ($existingProcess -and $existingProcess.ExecutablePath -eq $serverPath) {
        throw "The registered fallback server is already running with PID $($existingStatus.pid)."
    }
}

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
try {
    $listener.Start()
}
catch {
    throw "Fallback server port 127.0.0.1:$Port is unavailable."
}
finally {
    $listener.Stop()
}

New-Item -ItemType Directory -Path (Split-Path -Parent $statusPath), $logRoot -Force | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stdoutPath = Join-Path $logRoot "fallback-$stamp.stdout.log"
$stderrPath = Join-Path $logRoot "fallback-$stamp.stderr.log"

$environmentNames = @(
    'LVA_FALLBACK_API_KEY',
    'LLAMA_API_KEY',
    'LLAMA_ARG_MODEL',
    'LLAMA_ARG_HOST',
    'LLAMA_ARG_PORT',
    'LLAMA_ARG_ALIAS',
    'LLAMA_ARG_CTX_SIZE',
    'LLAMA_ARG_N_PARALLEL',
    'LLAMA_ARG_N_GPU_LAYERS',
    'LLAMA_ARG_JINJA',
    'LLAMA_ARG_FLASH_ATTN',
    'LLAMA_ARG_ENDPOINT_METRICS'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    $apiKey = $env:LVA_FALLBACK_API_KEY
    Remove-Item Env:LVA_FALLBACK_API_KEY
    $env:LLAMA_API_KEY = $apiKey
    $env:LLAMA_ARG_MODEL = $modelPath
    $env:LLAMA_ARG_HOST = '127.0.0.1'
    $env:LLAMA_ARG_PORT = [string]$Port
    $env:LLAMA_ARG_ALIAS = 'gemma4-12b-fallback'
    $env:LLAMA_ARG_CTX_SIZE = '4096'
    $env:LLAMA_ARG_N_PARALLEL = '1'
    $env:LLAMA_ARG_N_GPU_LAYERS = if ($CpuOnly) { '0' } else { '999' }
    $env:LLAMA_ARG_JINJA = 'true'
    $env:LLAMA_ARG_FLASH_ATTN = 'auto'
    $env:LLAMA_ARG_ENDPOINT_METRICS = '1'

    $process = Start-Process `
        -FilePath $serverPath `
        -WorkingDirectory $runtimeRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    $healthy = $false
    $headers = @{ Authorization = "Bearer $apiKey" }
    for ($elapsed = 0; $elapsed -lt $StartupTimeoutSeconds; $elapsed++) {
        if ($process.HasExited) {
            break
        }
        try {
            $response = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$Port/health" `
                -Headers $headers `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        }
        catch {
            # The bounded loop handles cold-load connection failures.
        }
        Start-Sleep -Seconds 1
    }
    if (-not $healthy) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
        throw "Fallback server failed health; inspect $stderrPath"
    }

    $status = [ordered]@{
        schema_version = '1.0'
        runtime = 'llama.cpp'
        version = 'b10092'
        pid = $process.Id
        executable = $serverPath
        host = '127.0.0.1'
        port = $Port
        model = 'gemma4-12b-fallback'
        model_path = $modelPath
        cpu_only = [bool]$CpuOnly
        stdout = $stdoutPath
        stderr = $stderrPath
        started_at = (Get-Date).ToUniversalTime().ToString('o')
    }
    $status |
        ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $statusPath -Encoding UTF8
    Write-Output "Fallback server ready: pid=$($process.Id) port=$Port cpu_only=$([bool]$CpuOnly)"
}
finally {
    foreach ($name in $environmentNames) {
        if ($null -eq $previousEnvironment[$name]) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable(
                $name,
                [string]$previousEnvironment[$name],
                'Process'
            )
        }
    }
}
