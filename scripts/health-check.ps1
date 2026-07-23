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

[pscustomobject]@{
    timestamp = (Get-Date).ToString('o')
    gpu = ($gpu -join "`n")
    wsl = ($wsl -join "`n")
    paths = @($paths | ForEach-Object {
        [pscustomobject]@{ path = $_; exists = Test-Path -LiteralPath $_ }
    })
    server = 'not_implemented'
    model_runtime = 'not_installed'
} | ConvertTo-Json -Depth 5
