[CmdletBinding(DefaultParameterSetName = 'Plan')]
param(
    [Parameter(ParameterSetName = 'Plan')]
    [switch]$PlanOnly,
    [Parameter(ParameterSetName = 'Execute')]
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$wslScript = (Join-Path $repoRoot 'scripts\download-models.sh').
    Replace('\', '/').
    Replace('C:', '/mnt/c')

if ($Execute) {
    & wsl.exe -d Ubuntu -- bash $wslScript --execute
    exit $LASTEXITCODE
}

& wsl.exe -d Ubuntu -- bash $wslScript --plan-only
exit $LASTEXITCODE
