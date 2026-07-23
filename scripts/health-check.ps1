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
        files = @([pscustomobject]@{
            path = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\12b\target\1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee\model.safetensors'
            expected_bytes = [int64]10264229896
        })
    },
    [pscustomobject]@{
        role = 'default_mtp_assistant'
        files = @([pscustomobject]@{
            path = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\12b\mtp-assistant\18934064dd4c5c6cc3621f6381e7d377fc8cb7bd\model.safetensors'
            expected_bytes = [int64]845719296
        })
    },
    [pscustomobject]@{
        role = 'mtp_target_12b'
        files = @([pscustomobject]@{
            path = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\12b\mtp-target\b6ed86275a6a5735884e208bfed95b445a684ca2\model.safetensors'
            expected_bytes = [int64]23919549408
        })
    },
    [pscustomobject]@{
        role = 'escalation_target'
        files = @([pscustomobject]@{
            path = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\31b\target\52f3f65bc7a02d555763bc923bd1d9094898219d\model.safetensors'
            expected_bytes = [int64]23265352448
        })
    },
    [pscustomobject]@{
        role = 'escalation_mtp_assistant'
        files = @([pscustomobject]@{
            path = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\31b\mtp-assistant\96d4c8ca3cb38c107a8478587878124895d1e844\model.safetensors'
            expected_bytes = [int64]939042560
        })
    },
    [pscustomobject]@{
        role = 'mtp_target_31b'
        files = @(
            [pscustomobject]@{
                path = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\31b\mtp-target\1e4d8beecacb8b7590c1d8bedd7335f687bf311f\model-00001-of-00002.safetensors'
                expected_bytes = [int64]49784788364
            },
            [pscustomobject]@{
                path = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4\31b\mtp-target\1e4d8beecacb8b7590c1d8bedd7335f687bf311f\model-00002-of-00002.safetensors'
                expected_bytes = [int64]12761549884
            }
        )
    }
)
$models = @($modelDefinitions | ForEach-Object {
    $definition = $_
    $files = @($definition.files | ForEach-Object {
        $file = $_
        $exists = Test-Path -LiteralPath $file.path -PathType Leaf
        $actualBytes = if ($exists) { (Get-Item -LiteralPath $file.path).Length } else { [int64]0 }
        [pscustomobject]@{
            path = $file.path
            expected_bytes = $file.expected_bytes
            actual_bytes = $actualBytes
            finalized = $exists -and $actualBytes -eq $file.expected_bytes
            partial_present = Test-Path -LiteralPath "$($file.path).partial" -PathType Leaf
        }
    })
    [pscustomobject]@{
        role = $definition.role
        finalized = @($files | Where-Object { -not $_.finalized }).Count -eq 0
        partial_present = @($files | Where-Object partial_present).Count -gt 0
        files = $files
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
