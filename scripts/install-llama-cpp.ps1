[CmdletBinding()]
param(
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'

$version = 'b10092'
$runtimeRoot = "C:\Dev\Tools\LocalVoiceAgent\runtimes\llama.cpp-$version"
$cacheRoot = 'E:\Cache\LocalVoiceAgent\downloads'
$extractRoot = "E:\Cache\LocalVoiceAgent\extract\llama.cpp-$version-$([guid]::NewGuid())"
$binaryArchive = Join-Path $cacheRoot 'llama-b10092-bin-win-cuda-13.3-x64.zip'
$cudaArchive = Join-Path $cacheRoot 'cudart-llama-bin-win-cuda-13.3-x64.zip'
$archives = @(
    @{
        Path = $binaryArchive
        Size = 145857793
        Sha256 = '6f3375d5029b677ea2049963439ee7f2b970626da42f56da34d1d203b1833875'
    },
    @{
        Path = $cudaArchive
        Size = 390970417
        Sha256 = '1462a050eb4c684921ba51dcc4cc488a036674c3e73e9945ee705b854808d03e'
    }
)

$plan = [ordered]@{
    version = $version
    source = 'https://github.com/ggml-org/llama.cpp/releases/tag/b10092'
    commit = '3ce7da2c852c538c4c5f9806da27029cf8c9cc4a'
    destination = $runtimeRoot
    archives = @($archives | ForEach-Object { $_.Path })
    administrator_required = $false
    rollback = 'Stop the owned fallback server, then move only this versioned runtime to C:\WorkstationTrash.'
}
if (-not $Execute) {
    $plan | ConvertTo-Json -Depth 4
    return
}

if (Test-Path -LiteralPath $runtimeRoot) {
    throw "Versioned llama.cpp runtime already exists; refusing overwrite: $runtimeRoot"
}
foreach ($archive in $archives) {
    if (-not (Test-Path -LiteralPath $archive.Path -PathType Leaf)) {
        throw "Pinned archive is unavailable: $($archive.Path)"
    }
    $item = Get-Item -LiteralPath $archive.Path
    if ($item.Length -ne $archive.Size) {
        throw "Archive size mismatch: $($archive.Path)"
    }
    $actualHash = (Get-FileHash -LiteralPath $archive.Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $archive.Sha256) {
        throw "Archive hash mismatch: $($archive.Path)"
    }
}

$stagingRoot = "$runtimeRoot.staging-$([guid]::NewGuid())"
New-Item -ItemType Directory -Path $extractRoot, $stagingRoot -Force | Out-Null
try {
    $binaryExtract = Join-Path $extractRoot 'binary'
    $cudaExtract = Join-Path $extractRoot 'cuda'
    Expand-Archive -LiteralPath $binaryArchive -DestinationPath $binaryExtract
    Expand-Archive -LiteralPath $cudaArchive -DestinationPath $cudaExtract

    $server = Get-ChildItem -LiteralPath $binaryExtract -Recurse -File -Filter 'llama-server.exe' |
        Select-Object -First 1
    if (-not $server) {
        throw 'The pinned binary archive does not contain llama-server.exe.'
    }
    Copy-Item -Path (Join-Path $server.Directory.FullName '*') -Destination $stagingRoot -Recurse -Force

    $cudaFiles = Get-ChildItem -LiteralPath $cudaExtract -Recurse -File
    if (-not $cudaFiles) {
        throw 'The pinned CUDA archive contains no runtime files.'
    }
    foreach ($file in $cudaFiles) {
        Copy-Item -LiteralPath $file.FullName -Destination $stagingRoot -Force
    }

    $stagedServer = Join-Path $stagingRoot 'llama-server.exe'
    if (-not (Test-Path -LiteralPath $stagedServer -PathType Leaf)) {
        throw 'Staged llama-server.exe is unavailable.'
    }
    $versionStdout = Join-Path $extractRoot 'version.stdout.log'
    $versionStderr = Join-Path $extractRoot 'version.stderr.log'
    $versionProcess = Start-Process `
        -FilePath $stagedServer `
        -ArgumentList @('--version') `
        -WorkingDirectory $stagingRoot `
        -RedirectStandardOutput $versionStdout `
        -RedirectStandardError $versionStderr `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    $versionOutput = @(
        Get-Content -LiteralPath $versionStdout -ErrorAction SilentlyContinue
        Get-Content -LiteralPath $versionStderr -ErrorAction SilentlyContinue
    )
    if (
        $versionProcess.ExitCode -ne 0 -or
        ($versionOutput -join "`n") -notmatch '(?:version|build):\s+10092'
    ) {
        throw "Unexpected llama.cpp version output: $($versionOutput -join ' ')"
    }

    $manifest = [ordered]@{
        schema_version = '1.0'
        runtime = 'llama.cpp'
        version = $version
        commit = '3ce7da2c852c538c4c5f9806da27029cf8c9cc4a'
        installed_at = (Get-Date).ToUniversalTime().ToString('o')
        executable = 'llama-server.exe'
        executable_sha256 = (Get-FileHash -LiteralPath $stagedServer -Algorithm SHA256).Hash.ToLowerInvariant()
        archives = @($archives | ForEach-Object {
            [ordered]@{
                file = Split-Path -Leaf $_.Path
                size_bytes = $_.Size
                sha256 = $_.Sha256
            }
        })
    }
    $manifest |
        ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath (Join-Path $stagingRoot 'installed-manifest.json') -Encoding UTF8

    Move-Item -LiteralPath $stagingRoot -Destination $runtimeRoot
    Write-Output "Installed pinned llama.cpp runtime: $runtimeRoot"
}
finally {
    if (
        (Test-Path -LiteralPath $stagingRoot) -and
        $stagingRoot.StartsWith('C:\Dev\Tools\LocalVoiceAgent\runtimes\llama.cpp-', [StringComparison]::OrdinalIgnoreCase)
    ) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
    if (
        (Test-Path -LiteralPath $extractRoot) -and
        $extractRoot.StartsWith('E:\Cache\LocalVoiceAgent\extract\llama.cpp-', [StringComparison]::OrdinalIgnoreCase)
    ) {
        Remove-Item -LiteralPath $extractRoot -Recurse -Force
    }
}
