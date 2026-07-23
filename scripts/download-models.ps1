[CmdletBinding(DefaultParameterSetName = 'Plan')]
param(
    [Parameter(ParameterSetName = 'Plan')]
    [switch]$PlanOnly,
    [Parameter(ParameterSetName = 'Execute')]
    [switch]$Execute,
    [ValidateSet(
        'default_target_12b',
        'mtp_assistant_12b',
        'mtp_target_12b',
        'escalation_target_31b',
        'mtp_assistant_31b',
        'mtp_target_31b'
    )]
    [string]$Only
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$wslScript = (Join-Path $repoRoot 'scripts\download-models.sh').
    Replace('\', '/').
    Replace('C:', '/mnt/c')

$mode = if ($Execute) { '--execute' } else { '--plan-only' }
$wslArgs = @('-d', 'Ubuntu', '--')
if ($Only) {
    $wslArgs += @('env', "MODEL_DOWNLOAD_ONLY=$Only")
}
$wslArgs += @('bash', $wslScript, $mode)

& wsl.exe @wslArgs
exit $LASTEXITCODE
