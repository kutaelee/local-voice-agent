[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$tokenPath = 'E:\Data\LocalVoiceAgent\secrets\pairing-token'
$tokenDirectory = Split-Path -Parent $tokenPath

if (-not (Test-Path -LiteralPath $tokenDirectory -PathType Container)) {
    throw "Canonical secret directory is unavailable: $tokenDirectory"
}

$random = [byte[]]::new(48)
$generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $generator.GetBytes($random)
    $token = [Convert]::ToBase64String($random).
        TrimEnd('=').
        Replace('+', '-').
        Replace('/', '_')
    [System.IO.File]::WriteAllText(
        $tokenPath,
        $token,
        [System.Text.UTF8Encoding]::new($false)
    )
}
finally {
    if ($token) {
        $token = $null
    }
    [Array]::Clear($random, 0, $random.Length)
    $generator.Dispose()
}

$userSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$systemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$result = & icacls.exe `
    $tokenPath `
    '/inheritance:r' `
    '/grant:r' `
    "*$($userSid.Value):(F)" `
    "*$($systemSid.Value):(F)" 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Pairing token was rotated but its ACL could not be restricted: $result"
}

Write-Output 'Pairing token rotated; restart every PC-server instance.'
