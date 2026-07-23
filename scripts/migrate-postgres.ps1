[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$serverRoot = Join-Path $repoRoot 'apps\pc-server'
$passwordFile = 'E:\Data\LocalVoiceAgent\secrets\postgres-password'
$virtualEnvironment = '/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv'

if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
    throw 'PostgreSQL password file is unavailable. Run start-postgres.ps1 first.'
}
$password = [System.IO.File]::ReadAllText($passwordFile).Trim()
if ($password.Length -lt 48) {
    throw 'PostgreSQL password file has an invalid size.'
}
$encodedPassword = [Uri]::EscapeDataString($password)
$env:LVA_DATABASE_URL = (
    "postgresql+asyncpg://local_voice_agent:{0}@127.0.0.1:55432/local_voice_agent" `
        -f $encodedPassword
)
$previousWslEnv = $env:WSLENV
$env:WSLENV = if ($previousWslEnv) {
    "LVA_DATABASE_URL:$previousWslEnv"
}
else {
    'LVA_DATABASE_URL'
}
try {
wsl.exe -d Ubuntu -- bash -lc @'
set -euo pipefail
export VIRTUAL_ENV=/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv
cd /mnt/c/Dev/Repos/local-voice-agent/apps/pc-server
/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv/bin/alembic upgrade head
/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv/bin/alembic current
'@
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic migration failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:LVA_DATABASE_URL = $null
    $password = $null
    $encodedPassword = $null
    if ($null -eq $previousWslEnv) {
        Remove-Item Env:WSLENV -ErrorAction SilentlyContinue
    }
    else {
        $env:WSLENV = $previousWslEnv
    }
}
