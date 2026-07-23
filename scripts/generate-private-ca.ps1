[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')]
    [string]$DeploymentName,

    [string[]]$DnsName = @(),

    [string[]]$IpAddress = @()
)

$ErrorActionPreference = 'Stop'

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$tlsRoot = 'E:\Data\LocalVoiceAgent\tls'
$destination = Join-Path $tlsRoot $DeploymentName
$wslPython = '/home/kutae/.local/share/local-voice-agent/runtimes/tls-tools-49.0.0/.venv/bin/python'
$wslGenerator = '/mnt/c/Dev/Repos/local-voice-agent/scripts/generate-private-ca.py'
$wslDestination = "/mnt/e/Data/LocalVoiceAgent/tls/$DeploymentName"

function Set-RestrictedTlsAcl {
    param([Parameter(Mandatory)][string]$LiteralPath)

    $userSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
    $items = @((Get-ChildItem -LiteralPath $LiteralPath -Recurse -Force)) +
        @(Get-Item -LiteralPath $LiteralPath -Force)

    foreach ($item in $items) {
        $acl = Get-Acl -LiteralPath $item.FullName
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($rule in @($acl.Access)) {
            [void]$acl.RemoveAccessRuleSpecific($rule)
        }
        $inheritance = if ($item.PSIsContainer) {
            [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
        }
        else {
            [System.Security.AccessControl.InheritanceFlags]::None
        }
        $propagation = [System.Security.AccessControl.PropagationFlags]::None
        $allow = [System.Security.AccessControl.AccessControlType]::Allow
        [void]$acl.AddAccessRule(
            ([System.Security.AccessControl.FileSystemAccessRule]::new(
                $userSid,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                $inheritance,
                $propagation,
                $allow
            ))
        )
        [void]$acl.AddAccessRule(
            ([System.Security.AccessControl.FileSystemAccessRule]::new(
                $systemSid,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                $inheritance,
                $propagation,
                $allow
            ))
        )
        Set-Acl -LiteralPath $item.FullName -AclObject $acl
    }

    foreach ($item in $items) {
        $acl = Get-Acl -LiteralPath $item.FullName
        foreach ($rule in $acl.Access) {
            $sid = $rule.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value
            if (
                $rule.IsInherited -or
                $sid -notin @($userSid.Value, $systemSid.Value) -or
                $rule.AccessControlType -ne
                    [System.Security.AccessControl.AccessControlType]::Allow
            ) {
                throw "TLS ACL verification failed for $($item.FullName)."
            }
        }
    }
}

if ($DnsName.Count -eq 0 -and $IpAddress.Count -eq 0) {
    throw 'At least one -DnsName or -IpAddress is required.'
}
if (
    -not $env:LVA_CA_KEY_PASSWORD -or
    $env:LVA_CA_KEY_PASSWORD.Length -lt 20
) {
    throw 'Set LVA_CA_KEY_PASSWORD to at least 20 characters in this process.'
}
if (-not (Test-Path -LiteralPath $repoRoot -PathType Container)) {
    throw "Repository is unavailable: $repoRoot"
}
if (Test-Path -LiteralPath $destination) {
    throw "Refusing to overwrite existing deployment: $destination"
}
wsl.exe -d Ubuntu -- test -x $wslPython
if ($LASTEXITCODE -ne 0) {
    throw "TLS tools environment is unavailable: $wslPython"
}

$arguments = @(
    '-d',
    'Ubuntu',
    '--',
    $wslPython,
    $wslGenerator,
    '--deployment-name',
    $DeploymentName,
    '--output-dir',
    $wslDestination
)
foreach ($name in $DnsName) {
    $arguments += @('--dns-name', $name)
}
foreach ($address in $IpAddress) {
    $arguments += @('--ip-address', $address)
}

$previousWslEnv = $env:WSLENV
$env:WSLENV = if ($previousWslEnv) {
    "LVA_CA_KEY_PASSWORD:$previousWslEnv"
}
else {
    'LVA_CA_KEY_PASSWORD'
}

try {
    $generatorOutput = & wsl.exe @arguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Private CA generator failed.'
    }
    if (-not (Test-Path -LiteralPath $destination -PathType Container)) {
        throw "Generator did not create the expected deployment: $destination"
    }
    Set-RestrictedTlsAcl -LiteralPath $destination

    $manifest = Get-Content -LiteralPath (Join-Path $destination 'manifest.json') -Raw |
        ConvertFrom-Json
    if (
        $manifest.deployment_name -ne $DeploymentName -or
        $manifest.private_key_protection -ne 'windows_acl_wrapper_required'
    ) {
        throw 'Generated TLS manifest failed validation.'
    }
    $manifest | Add-Member -NotePropertyName windows_acl_status `
        -NotePropertyValue 'current_user_and_local_system_only' -Force
    $manifest | ConvertTo-Json -Depth 8
}
catch {
    if (Test-Path -LiteralPath $destination -PathType Container) {
        Set-RestrictedTlsAcl -LiteralPath $destination
    }
    throw
}
finally {
    $generatorOutput = $null
    if ($null -eq $previousWslEnv) {
        Remove-Item Env:WSLENV -ErrorAction SilentlyContinue
    }
    else {
        $env:WSLENV = $previousWslEnv
    }
}
