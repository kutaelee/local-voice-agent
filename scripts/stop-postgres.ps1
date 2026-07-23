[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$dataDirectory = 'E:\Data\DB\Active\LocalVoiceAgent'
$passwordFile = 'E:\Data\LocalVoiceAgent\secrets\postgres-password'
$statusPath = 'E:\Data\LocalVoiceAgent\runtime\status\postgres.json'

if (
    -not (Test-Path -LiteralPath $dataDirectory -PathType Container) -or
    -not (Test-Path -LiteralPath $passwordFile -PathType Leaf)
) {
    throw 'Registered PostgreSQL data or secret path is unavailable.'
}
$env:LVA_POSTGRES_DATA_DIR = $dataDirectory
$env:LVA_POSTGRES_PASSWORD_FILE = $passwordFile
try {
    docker compose `
        --project-directory $repoRoot `
        -f (Join-Path $repoRoot 'compose.yaml') `
        stop postgres
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL compose stop failed with exit code $LASTEXITCODE."
    }
}
finally {
    Remove-Item Env:LVA_POSTGRES_DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:LVA_POSTGRES_PASSWORD_FILE -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
    $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $status.state = 'stopped'
    $status | Add-Member `
        -NotePropertyName stopped_at `
        -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o') `
        -Force
    $status | ConvertTo-Json | Set-Content `
        -LiteralPath $statusPath `
        -Encoding utf8
    Get-Content -LiteralPath $statusPath -Raw
}
