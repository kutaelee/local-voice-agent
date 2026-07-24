[CmdletBinding()]
param(
    [ValidateSet('preflight', 'install', 'initialize', 'set-case', 'finalize')]
    [string]$Action = 'preflight',

    [ValidatePattern('^[A-Za-z0-9._:-]{1,128}$')]
    [string]$DeviceSerial,

    [string]$EvidencePath,

    [ValidateSet(
        'invalid_pairing_token',
        'microphone_permission',
        'twenty_sequential_turns',
        'speaker',
        'earpiece',
        'bluetooth',
        'barge_in',
        'background_foreground',
        'rotation',
        'network_loss',
        'replay_expiry',
        'approval_denial',
        'server_switch',
        'voice_profile_selection',
        'voice_similarity',
        'playback_speed'
    )]
    [string]$Case,

    [ValidateSet('passed', 'failed')]
    [string]$Outcome,

    [ValidateRange(0, 60000)]
    [int]$MeasuredLatencyMs = 0
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$adb = 'C:\Dev\SDK\Android\platform-tools\adb.exe'
$apk = (
    'E:\Data\LocalVoiceAgent\artifacts\android\0.6.5-api37\' +
    'local-voice-agent-0.6.5-debug.apk'
)
$expectedApkHash = (
    'ce91990cbc0126084d8dfd12e668d17eff3fc4c02e0100acef7a25229cd5428b'
)
$packageName = 'dev.localvoiceagent.android'
$evidenceRoot = (
    'E:\Data\LocalVoiceAgent\runtime\evidence\android\physical'
)
$caseNames = @(
    'invalid_pairing_token',
    'microphone_permission',
    'twenty_sequential_turns',
    'speaker',
    'earpiece',
    'bluetooth',
    'barge_in',
    'background_foreground',
    'rotation',
    'network_loss',
    'replay_expiry',
    'approval_denial',
    'server_switch',
    'voice_profile_selection',
    'voice_similarity',
    'playback_speed'
)

function Invoke-Adb {
    param([string[]]$Arguments)

    $output = @(& $adb @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw (
            "ADB exited $LASTEXITCODE for the registered QA operation: " +
            (($output | ForEach-Object { $_.ToString() }) -join ' ')
        )
    }
    return @($output | ForEach-Object { $_.ToString() })
}

function Get-PhysicalDeviceSerial {
    if (-not (Test-Path -LiteralPath $adb -PathType Leaf)) {
        throw "Registered ADB is unavailable: $adb"
    }
    $devices = @()
    foreach ($line in (Invoke-Adb -Arguments @('devices'))) {
        if ($line -match '^(\S+)\s+device$') {
            $devices += $Matches[1]
        }
    }
    $physical = @($devices | Where-Object { $_ -notmatch '^emulator-' })
    if ($DeviceSerial) {
        if ($DeviceSerial -match '^emulator-') {
            throw 'Physical QA refuses emulator devices.'
        }
        if ($DeviceSerial -notin $physical) {
            throw 'The selected physical Android device is not connected.'
        }
        return $DeviceSerial
    }
    if ($physical.Count -ne 1) {
        throw (
            'Connect exactly one authorized physical Android device or pass ' +
            '-DeviceSerial. Emulators cannot close physical QA.'
        )
    }
    return $physical[0]
}

function Get-VerifiedApkHash {
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) {
        throw "Registered debug APK is unavailable: $apk"
    }
    $hash = (
        Get-FileHash -LiteralPath $apk -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($hash -ne $expectedApkHash) {
        throw "Debug APK hash mismatch: observed=$hash"
    }
    return $hash
}

function Get-DeviceMetadata {
    param([string]$Serial)

    $model = (
        Invoke-Adb -Arguments @(
            '-s', $Serial, 'shell', 'getprop', 'ro.product.model'
        )
    ) -join ''
    $api = (
        Invoke-Adb -Arguments @(
            '-s', $Serial, 'shell', 'getprop', 'ro.build.version.sdk'
        )
    ) -join ''
    $android = (
        Invoke-Adb -Arguments @(
            '-s', $Serial, 'shell', 'getprop', 'ro.build.version.release'
        )
    ) -join ''
    if (
        $model.Length -gt 160 -or
        $api -notmatch '^\d{1,3}$' -or
        $android.Length -gt 40
    ) {
        throw 'Android device metadata is invalid.'
    }

    $packageOutput = (
        Invoke-Adb -Arguments @(
            '-s', $Serial, 'shell', 'dumpsys', 'package', $packageName
        )
    ) -join "`n"
    $versionCode = $null
    $versionName = $null
    if ($packageOutput -match '(?m)^\s*versionCode=(\d+)') {
        $versionCode = [int]$Matches[1]
    }
    if ($packageOutput -match '(?m)^\s*versionName=([^\s]+)') {
        $versionName = $Matches[1]
    }
    return [ordered]@{
        model = $model.Trim()
        android_release = $android.Trim()
        api_level = [int]$api
        app_package = $packageName
        app_version_code = $versionCode
        app_version_name = $versionName
    }
}

function Resolve-EvidencePath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw '-EvidencePath is required for this action.'
    }
    $root = [IO.Path]::GetFullPath($evidenceRoot).TrimEnd('\')
    $full = [IO.Path]::GetFullPath($Path)
    if (
        -not $full.StartsWith(
            "$root\",
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [IO.Path]::GetExtension($full) -ne '.json'
    ) {
        throw "EvidencePath must be a JSON file beneath $root."
    }
    return $full
}

function Write-EvidenceAtomically {
    param(
        [string]$Path,
        [object]$Value
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }
    $temporary = Join-Path (
        $directory
    ) (".physical-android-qa-$([guid]::NewGuid().ToString('N')).tmp")
    try {
        $Value |
            ConvertTo-Json -Depth 8 |
            Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Read-Evidence {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Physical QA evidence is unavailable: $Path"
    }
    $value = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($value.schema_version -ne '1.0') {
        throw 'Physical QA evidence schema version differs.'
    }
    $actualCases = @($value.cases | ForEach-Object { $_.name })
    if (
        $actualCases.Count -ne $caseNames.Count -or
        (Compare-Object $actualCases $caseNames).Count -ne 0
    ) {
        throw 'Physical QA evidence case catalog differs.'
    }
    return $value
}

$serial = $null
if ($Action -in @('preflight', 'install', 'initialize', 'finalize')) {
    $serial = Get-PhysicalDeviceSerial
}

switch ($Action) {
    'preflight' {
        $hash = Get-VerifiedApkHash
        [ordered]@{
            schema_version = '1.0'
            status = 'ready'
            physical_device_connected = true
            apk_sha256 = $hash
            device = Get-DeviceMetadata -Serial $serial
            pairing_token_collected = false
            raw_audio_collected = false
        } | ConvertTo-Json -Depth 5
    }
    'install' {
        Get-VerifiedApkHash | Out-Null
        Invoke-Adb -Arguments @('-s', $serial, 'install', '-r', $apk) |
            Out-Null
        $metadata = Get-DeviceMetadata -Serial $serial
        if (
            $metadata.app_version_code -ne 13 -or
            $metadata.app_version_name -ne '0.6.5'
        ) {
            throw 'Installed Android package version does not match 0.6.5.'
        }
        [ordered]@{
            status = 'installed'
            package = $packageName
            version_code = $metadata.app_version_code
            version_name = $metadata.app_version_name
        } | ConvertTo-Json
    }
    'initialize' {
        $hash = Get-VerifiedApkHash
        $metadata = Get-DeviceMetadata -Serial $serial
        if (
            $metadata.app_version_code -ne 13 -or
            $metadata.app_version_name -ne '0.6.5'
        ) {
            throw 'Install the verified 0.6.5 debug APK before QA.'
        }
        if ([string]::IsNullOrWhiteSpace($EvidencePath)) {
            $stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
            $EvidencePath = Join-Path (
                $evidenceRoot
            ) "physical-android-qa-$stamp.json"
        }
        $full = Resolve-EvidencePath -Path $EvidencePath
        if (Test-Path -LiteralPath $full) {
            throw "Refusing to overwrite existing QA evidence: $full"
        }
        $evidence = [ordered]@{
            schema_version = '1.0'
            result = 'in_progress'
            created_at = [DateTimeOffset]::Now.ToString('o')
            updated_at = [DateTimeOffset]::Now.ToString('o')
            completed_at = $null
            device = $metadata
            apk_sha256 = $hash
            cases = @(
                $caseNames | ForEach-Object {
                    [ordered]@{
                        name = $_
                        status = 'not_run'
                        measured_latency_ms = $null
                    }
                }
            )
            privacy = [ordered]@{
                pairing_token_retained = false
                raw_audio_retained = false
                full_transcript_retained = false
                unrelated_device_logs_retained = false
            }
        }
        Write-EvidenceAtomically -Path $full -Value $evidence
        Write-Output "physical_qa_evidence=$full"
    }
    'set-case' {
        if (-not $Case -or -not $Outcome) {
            throw '-Case and -Outcome are required for set-case.'
        }
        $full = Resolve-EvidencePath -Path $EvidencePath
        $evidence = Read-Evidence -Path $full
        if ($evidence.result -ne 'in_progress') {
            throw 'Only in-progress evidence can be updated.'
        }
        $item = @($evidence.cases | Where-Object { $_.name -eq $Case })
        if ($item.Count -ne 1) {
            throw 'The requested physical QA case is unavailable.'
        }
        $item[0].status = $Outcome
        if ($MeasuredLatencyMs -gt 0) {
            $item[0].measured_latency_ms = $MeasuredLatencyMs
        }
        $evidence.updated_at = [DateTimeOffset]::Now.ToString('o')
        Write-EvidenceAtomically -Path $full -Value $evidence
        Write-Output "physical_qa_case=$Case outcome=$Outcome"
    }
    'finalize' {
        $full = Resolve-EvidencePath -Path $EvidencePath
        $evidence = Read-Evidence -Path $full
        $pending = @(
            $evidence.cases |
                Where-Object { $_.status -eq 'not_run' }
        )
        if ($pending.Count -gt 0) {
            throw 'Every physical QA case must have a terminal outcome.'
        }
        $current = Get-DeviceMetadata -Serial $serial
        if (
            $current.model -ne $evidence.device.model -or
            $current.api_level -ne $evidence.device.api_level -or
            $current.app_version_code -ne $evidence.device.app_version_code
        ) {
            throw 'Connected device or installed app differs from QA start.'
        }
        $failed = @(
            $evidence.cases |
                Where-Object { $_.status -eq 'failed' }
        )
        $evidence.result = if ($failed.Count -eq 0) {
            'passed'
        }
        else {
            'failed'
        }
        $evidence.updated_at = [DateTimeOffset]::Now.ToString('o')
        $evidence.completed_at = [DateTimeOffset]::Now.ToString('o')
        Write-EvidenceAtomically -Path $full -Value $evidence
        $hash = (
            Get-FileHash -LiteralPath $full -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        Write-Output "physical_qa_result=$($evidence.result)"
        Write-Output "physical_qa_evidence=$full"
        Write-Output "physical_qa_evidence_sha256=$hash"
    }
}
