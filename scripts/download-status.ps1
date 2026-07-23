[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        'default_target_12b',
        'mtp_assistant_12b',
        'mtp_target_12b',
        'escalation_target_31b',
        'mtp_assistant_31b',
        'mtp_target_31b'
    )]
    [string]$Role
)

$ErrorActionPreference = 'Stop'
$stateRoot = 'E:\Cache\LocalVoiceAgent\download-state'
$modelRoot = 'E:\AI\Models\Standalone\LocalVoiceAgent\gemma4'

$specs = @{
    default_target_12b = @{
        Model = 'google/gemma-4-12B-it-qat-w4a16-ct'
        Revision = '1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee'
        Directory = Join-Path $modelRoot '12b\target\1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee'
        Files = @(@{ Name = 'model.safetensors'; Bytes = 10264229896 })
    }
    mtp_assistant_12b = @{
        Model = 'google/gemma-4-12B-it-qat-q4_0-unquantized-assistant'
        Revision = '18934064dd4c5c6cc3621f6381e7d377fc8cb7bd'
        Directory = Join-Path $modelRoot '12b\mtp-assistant\18934064dd4c5c6cc3621f6381e7d377fc8cb7bd'
        Files = @(@{ Name = 'model.safetensors'; Bytes = 845719296 })
    }
    mtp_target_12b = @{
        Model = 'google/gemma-4-12B-it-qat-q4_0-unquantized'
        Revision = 'b6ed86275a6a5735884e208bfed95b445a684ca2'
        Directory = Join-Path $modelRoot '12b\mtp-target\b6ed86275a6a5735884e208bfed95b445a684ca2'
        Files = @(@{ Name = 'model.safetensors'; Bytes = 23919549408 })
    }
    escalation_target_31b = @{
        Model = 'google/gemma-4-31B-it-qat-w4a16-ct'
        Revision = '52f3f65bc7a02d555763bc923bd1d9094898219d'
        Directory = Join-Path $modelRoot '31b\target\52f3f65bc7a02d555763bc923bd1d9094898219d'
        Files = @(@{ Name = 'model.safetensors'; Bytes = 23265352448 })
    }
    mtp_assistant_31b = @{
        Model = 'google/gemma-4-31B-it-qat-q4_0-unquantized-assistant'
        Revision = '96d4c8ca3cb38c107a8478587878124895d1e844'
        Directory = Join-Path $modelRoot '31b\mtp-assistant\96d4c8ca3cb38c107a8478587878124895d1e844'
        Files = @(@{ Name = 'model.safetensors'; Bytes = 939042560 })
    }
    mtp_target_31b = @{
        Model = 'google/gemma-4-31B-it-qat-q4_0-unquantized'
        Revision = '1e4d8beecacb8b7590c1d8bedd7335f687bf311f'
        Directory = Join-Path $modelRoot '31b\mtp-target\1e4d8beecacb8b7590c1d8bedd7335f687bf311f'
        Files = @(
            @{ Name = 'model-00001-of-00002.safetensors'; Bytes = 49784788364 },
            @{ Name = 'model-00002-of-00002.safetensors'; Bytes = 12761549884 }
        )
    }
}

$spec = $specs[$Role]
$totalBytes = [int64]0
$completedBytes = [int64]0
$files = @()
$statePrefix = $spec.Model.Replace('/', '--') + '-' + $spec.Revision

foreach ($fileSpec in $spec.Files) {
    $expectedBytes = [int64]$fileSpec.Bytes
    $totalBytes += $expectedBytes
    $finalPath = Join-Path $spec.Directory $fileSpec.Name
    $partialPath = $finalPath + '.partial'
    $statePath = Join-Path $stateRoot ($statePrefix + '-' + $fileSpec.Name + '.ranges.json')
    $finalized = $false
    $fileCompleted = [int64]0
    $chunksDone = 0
    $chunksTotal = 0

    if (Test-Path -LiteralPath $finalPath) {
        $length = (Get-Item -LiteralPath $finalPath).Length
        if ($length -eq $expectedBytes) {
            $finalized = $true
            $fileCompleted = $expectedBytes
        }
    } elseif (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $chunksDone = @($state.completed).Count
        $chunksTotal = [int]$state.chunks
        $fileCompleted = [Math]::Min(
            $expectedBytes,
            [int64]$chunksDone * [int64]$state.chunk_size
        )
    }

    $completedBytes += $fileCompleted
    $files += [ordered]@{
        name = $fileSpec.Name
        expected_bytes = $expectedBytes
        completed_bytes = $fileCompleted
        chunks_completed = $chunksDone
        chunks_total = $chunksTotal
        finalized = $finalized
        partial_present = Test-Path -LiteralPath $partialPath
        state_path = $statePath
    }
}

$processes = @(
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains("MODEL_DOWNLOAD_ONLY=$Role")
        } |
        Select-Object ProcessId, Name
)

[ordered]@{
    schema_version = '1.0'
    role = $Role
    model_id = $spec.Model
    revision = $spec.Revision
    total_bytes = $totalBytes
    completed_bytes = $completedBytes
    remaining_bytes = $totalBytes - $completedBytes
    percent = [Math]::Round(100 * $completedBytes / $totalBytes, 2)
    process_running = $processes.Count -gt 0
    process_ids = @($processes | ForEach-Object ProcessId)
    files = $files
    observed_at = (Get-Date).ToUniversalTime().ToString('o')
} | ConvertTo-Json -Depth 6
