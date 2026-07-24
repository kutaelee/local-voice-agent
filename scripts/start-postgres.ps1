[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$dataDirectory = 'E:\Data\DB\Active\LocalVoiceAgent'
$secretDirectory = 'E:\Data\LocalVoiceAgent\secrets'
$passwordFile = Join-Path $secretDirectory 'postgres-password'
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\postgres.json'

if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop CLI is unavailable.'
}
if (-not (Test-Path -LiteralPath $repoRoot -PathType Container)) {
    throw "Repository is unavailable: $repoRoot"
}
if (-not (Test-Path -LiteralPath $dataDirectory -PathType Container)) {
    throw "Approved PostgreSQL data directory is unavailable: $dataDirectory"
}
$existingData = @(Get-ChildItem -LiteralPath $dataDirectory -Force)
if (
    $existingData.Count -gt 0 -and
    -not (Test-Path -LiteralPath (Join-Path $dataDirectory '18\docker\PG_VERSION'))
) {
    throw 'PostgreSQL data directory is non-empty but not a registered PostgreSQL 18 cluster.'
}

New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
    $random = [byte[]]::new(48)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($random)
        $password = [Convert]::ToBase64String($random).TrimEnd('=')
        [System.IO.File]::WriteAllText(
            $passwordFile,
            $password,
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    finally {
        if ($null -ne $generator) {
            $generator.Dispose()
        }
        $password = $null
        [Array]::Clear($random, 0, $random.Length)
    }
}
$passwordInfo = Get-Item -LiteralPath $passwordFile
if ($passwordInfo.Length -lt 48 -or $passwordInfo.Length -gt 128) {
    throw 'PostgreSQL password file has an invalid size.'
}

$env:LVA_POSTGRES_DATA_DIR = $dataDirectory
$env:LVA_POSTGRES_PASSWORD_FILE = $passwordFile
try {
    docker compose `
        --project-directory $repoRoot `
        -f (Join-Path $repoRoot 'compose.yaml') `
        up -d --wait postgres
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL compose startup failed with exit code $LASTEXITCODE."
    }

    $containerId = docker compose `
        --project-directory $repoRoot `
        -f (Join-Path $repoRoot 'compose.yaml') `
        ps -q postgres
    if (-not $containerId) {
        throw 'PostgreSQL container ID is unavailable after startup.'
    }
}
finally {
    Remove-Item Env:LVA_POSTGRES_DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:LVA_POSTGRES_PASSWORD_FILE -ErrorAction SilentlyContinue
}

$health = docker inspect $containerId --format '{{.State.Health.Status}}'
$image = docker inspect $containerId --format '{{.Config.Image}}'
if ($health -ne 'healthy') {
    throw "PostgreSQL health is not healthy: $health"
}

New-Item -ItemType Directory -Path (Split-Path -Parent $statusPath) -Force |
    Out-Null
[ordered]@{
    schema_version = '1.0'
    component = 'postgres'
    state = 'running'
    container_id = $containerId
    image = $image
    host = '127.0.0.1'
    port = 46324
    database = 'local_voice_agent'
    user = 'local_voice_agent'
    data_directory = $dataDirectory
    password_file = $passwordFile
    started_at = (Get-Date).ToUniversalTime().ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8

Get-Content -LiteralPath $statusPath -Raw
