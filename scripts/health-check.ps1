[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'

$gpu = & nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version,compute_cap --format=csv,noheader,nounits 2>&1
$wsl = & wsl.exe -d Ubuntu -- bash -lc 'uname -r; nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits' 2>&1
$paths = @(
    'C:\Dev\Repos\local-voice-agent',
    'E:\AI\Models\Standalone\LocalVoiceAgent',
    'E:\Cache\LocalVoiceAgent',
    'E:\Data\LocalVoiceAgent',
    'E:\Data\DB\Active\LocalVoiceAgent'
)

$runtimeDefinitions = @(
    [pscustomobject]@{
        id = 'vllm-0.25.1'
        python = '/home/kutae/.local/share/local-voice-agent/runtimes/vllm-0.25.1/.venv/bin/python'
    },
    [pscustomobject]@{
        id = 'vllm-b2b8f679d058-cu130'
        python = '/home/kutae/.local/share/local-voice-agent/runtimes/vllm-b2b8f679d058-cu130/.venv/bin/python'
    }
)
$runtimes = @($runtimeDefinitions | ForEach-Object {
    $definition = $_
    & wsl.exe -d Ubuntu -- test -x $definition.python 2>$null
    $installed = $LASTEXITCODE -eq 0
    $version = $null
    if ($installed) {
        $versionOutput = & wsl.exe -d Ubuntu -- $definition.python -c "import importlib.metadata as m; print(m.version('vllm'))" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $version = ($versionOutput | Select-Object -First 1)
        }
    }
    [pscustomobject]@{
        id = $definition.id
        installed = $installed
        version = $version
    }
})

$modelDefinitions = @(
    [pscustomobject]@{
        role = 'default_target'
        final = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\12b\target\1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee\model.safetensors'
    },
    [pscustomobject]@{
        role = 'default_mtp_assistant'
        final = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\12b\mtp-assistant\18934064dd4c5c6cc3621f6381e7d377fc8cb7bd\model.safetensors'
    },
    [pscustomobject]@{
        role = 'mtp_target_12b'
        final = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\12b\mtp-target\b6ed86275a6a5735884e208bfed95b445a684ca2\model.safetensors'
    }
)
$models = @($modelDefinitions | ForEach-Object {
    $partial = "$($_.final).partial"
    [pscustomobject]@{
        role = $_.role
        finalized = Test-Path -LiteralPath $_.final -PathType Leaf
        partial_present = Test-Path -LiteralPath $partial -PathType Leaf
    }
})

$server = [ordered]@{
    host = '127.0.0.1'
    port = 8765
    listening = $false
    health = 'not_running'
}
$client = [System.Net.Sockets.TcpClient]::new()
try {
    $connect = $client.ConnectAsync($server.host, $server.port)
    if ($connect.Wait(500) -and $client.Connected) {
        $server.listening = $true
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://$($server.host):$($server.port)/health" -TimeoutSec 2
            $server.health = "http_$($response.StatusCode)"
        }
        catch {
            $server.health = 'port_open_health_failed'
        }
    }
}
catch {
    $server.health = 'not_running'
}
finally {
    $client.Dispose()
}

[pscustomobject]@{
    schema_version = '1.0'
    timestamp = (Get-Date).ToString('o')
    gpu = ($gpu -join "`n")
    wsl = ($wsl -join "`n")
    paths = @($paths | ForEach-Object {
        [pscustomobject]@{ path = $_; exists = Test-Path -LiteralPath $_ }
    })
    runtimes = $runtimes
    models = $models
    server = [pscustomobject]$server
} | ConvertTo-Json -Depth 5
