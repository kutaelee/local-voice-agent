[CmdletBinding()]
param(
    [string]$ListenHost,
    [ValidateRange(1024, 49151)]
    [int]$Port = 46321,
    [string]$TargetHost
)

$ErrorActionPreference = 'Stop'
$python = 'C:\Users\kutae\AppData\Local\Programs\Python\Python313\python.exe'
$relayScript = 'C:\Dev\Repos\local-voice-agent\scripts\private-network-tcp-relay.py'
$runtimeRoot = 'E:\Data\LocalVoiceAgent\runtime'
$statusPath = Join-Path $runtimeRoot 'status\lan-relay.json'
$logRoot = Join-Path $runtimeRoot 'logs'

foreach ($candidate in @($ListenHost, $TargetHost)) {
    $address = $null
    if (-not [Net.IPAddress]::TryParse($candidate, [ref]$address)) {
        throw 'Relay endpoints must be numeric IP addresses.'
    }
    $bytes = $address.GetAddressBytes()
    if (
        $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        -not (
            $bytes[0] -eq 10 -or
            ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
            ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
        )
    ) {
        throw 'Relay endpoints must be private IPv4 addresses.'
    }
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python runtime is unavailable: $python"
}
if (-not (Test-Path -LiteralPath $relayScript -PathType Leaf)) {
    throw "Relay implementation is unavailable: $relayScript"
}
if (Get-NetTCPConnection -State Listen -LocalAddress $ListenHost -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "Relay endpoint $ListenHost`:$Port is already in use."
}

New-Item -ItemType Directory -Path (Split-Path $statusPath), $logRoot -Force |
    Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stdoutPath = Join-Path $logRoot "lan-relay-$stamp.stdout.log"
$stderrPath = Join-Path $logRoot "lan-relay-$stamp.stderr.log"
$process = Start-Process `
    -FilePath $python `
    -ArgumentList @(
        $relayScript,
        '--listen-host', $ListenHost,
        '--listen-port', "$Port",
        '--target-host', $TargetHost,
        '--target-port', "$Port"
    ) `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if ($process.HasExited) { break }
    $listener = Get-NetTCPConnection `
        -State Listen `
        -LocalAddress $ListenHost `
        -LocalPort $Port `
        -ErrorAction SilentlyContinue
    if ($listener -and $listener.OwningProcess -eq $process.Id) { break }
    Start-Sleep -Milliseconds 250
}
if (-not $listener -or $listener.OwningProcess -ne $process.Id) {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id }
    throw "LAN relay failed to listen; inspect $stderrPath."
}

[ordered]@{
    schema_version = '1.0'
    component = 'private-network-relay'
    state = 'running'
    pid = $process.Id
    listen_host = $ListenHost
    listen_port = $Port
    target_host = $TargetHost
    target_port = $Port
    started_at = (Get-Date).ToUniversalTime().ToString('o')
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
} | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8

Get-Content -LiteralPath $statusPath -Raw
