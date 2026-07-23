[CmdletBinding()]
param(
    [string[]]$CaseId,

    [string]$EvidenceRoot = (
        'E:\Data\LocalVoiceAgent\runtime\evidence\required-tests'
    )
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$catalogPath = Join-Path $repoRoot 'tests\required-cases.json'
$toolEnvironment = (
    'C:\Dev\Tools\LocalVoiceAgent\runtimes\tool-executor\.venv'
)
$playwrightBrowsers = (
    'C:\Dev\Tools\LocalVoiceAgent\browsers\playwright-1.61.0'
)
$androidSdk = 'C:\Dev\SDK\Android'
$javaHome = 'C:\Dev\Java\jdk17'
$pcEnvironment = (
    '/home/kutae/.local/share/local-voice-agent/' +
    'runtimes/pc-server/.venv'
)

if (-not (Test-Path -LiteralPath $catalogPath -PathType Leaf)) {
    throw "Required-case catalog is unavailable: $catalogPath"
}
$catalog = Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json
$cases = @($catalog.cases)
if ($null -ne $CaseId -and $CaseId.Count -gt 0) {
    $unknown = @($CaseId | Where-Object { $_ -notin $cases.id })
    if ($unknown.Count -gt 0) {
        throw "Unknown required-case id: $($unknown -join ', ')"
    }
    $cases = @($cases | Where-Object { $_.id -in $CaseId })
}
if ($cases.Count -eq 0) {
    throw 'No required cases were selected.'
}

foreach ($path in @(
    $toolEnvironment,
    $playwrightBrowsers,
    $androidSdk,
    $javaHome
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Registered test dependency is unavailable: $path"
    }
}

function Invoke-RequiredCase {
    param([Parameter(Mandatory)]$Case)

    if (
        $Case.selector -notmatch '^[A-Za-z0-9_./:\[\]-]+$' -or
        $Case.runner -notin @(
            'pc_server',
            'tool_executor',
            'repository',
            'android'
        )
    ) {
        throw "Unsafe required-case binding: $($Case.id)"
    }

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $output = @()
    $exitCode = 1
    Push-Location $repoRoot
    try {
        switch ($Case.runner) {
            'pc_server' {
                $command = (
                    "cd /mnt/c/Dev/Repos/local-voice-agent && " +
                    "export UV_PROJECT_ENVIRONMENT=$pcEnvironment && " +
                    "/home/kutae/.local/bin/uv run " +
                    "--project apps/pc-server --locked " +
                    "--extra test --extra persistence pytest " +
                    "'$($Case.selector)' -q"
                )
                $output = @(
                    & wsl.exe -d Ubuntu -- bash -lc $command 2>&1 |
                        ForEach-Object { $_.ToString() }
                )
                $exitCode = $LASTEXITCODE
            }
            'tool_executor' {
                $previousUvEnvironment = $env:UV_PROJECT_ENVIRONMENT
                $previousBrowserPath = $env:PLAYWRIGHT_BROWSERS_PATH
                try {
                    $env:UV_PROJECT_ENVIRONMENT = $toolEnvironment
                    $env:PLAYWRIGHT_BROWSERS_PATH = $playwrightBrowsers
                    $output = @(
                        & uv run `
                            --project apps/tool-executor `
                            --locked `
                            --extra test `
                            pytest $Case.selector -q 2>&1 |
                            ForEach-Object { $_.ToString() }
                    )
                    $exitCode = $LASTEXITCODE
                }
                finally {
                    $env:UV_PROJECT_ENVIRONMENT = $previousUvEnvironment
                    $env:PLAYWRIGHT_BROWSERS_PATH = $previousBrowserPath
                }
            }
            'repository' {
                $python = Join-Path $toolEnvironment 'Scripts\python.exe'
                $output = @(
                    & $python -m pytest $Case.selector -q 2>&1 |
                        ForEach-Object { $_.ToString() }
                )
                $exitCode = $LASTEXITCODE
            }
            'android' {
                $previousJavaHome = $env:JAVA_HOME
                $previousAndroidHome = $env:ANDROID_HOME
                $previousAndroidSdkRoot = $env:ANDROID_SDK_ROOT
                try {
                    $env:JAVA_HOME = $javaHome
                    $env:ANDROID_HOME = $androidSdk
                    $env:ANDROID_SDK_ROOT = $androidSdk
                    $output = @(
                        & .\apps\android-client\gradlew.bat `
                            -p .\apps\android-client `
                            --no-daemon `
                            testDebugUnitTest `
                            --tests $Case.selector 2>&1 |
                            ForEach-Object { $_.ToString() }
                    )
                    $exitCode = $LASTEXITCODE
                }
                finally {
                    $env:JAVA_HOME = $previousJavaHome
                    $env:ANDROID_HOME = $previousAndroidHome
                    $env:ANDROID_SDK_ROOT = $previousAndroidSdkRoot
                }
            }
        }
    }
    finally {
        Pop-Location
        $stopwatch.Stop()
    }

    $joinedOutput = ($output -join "`n")
    if ($joinedOutput.Length -gt 65536) {
        $joinedOutput = $joinedOutput.Substring(
            $joinedOutput.Length - 65536
        )
    }
    [ordered]@{
        case_id = [string]$Case.id
        runner = [string]$Case.runner
        selector = [string]$Case.selector
        coverage_level = if (
            $Case.PSObject.Properties['coverage_level']
        ) {
            [string]$Case.coverage_level
        }
        else {
            'automated_behavior'
        }
        status = if ($exitCode -eq 0) { 'passed' } else { 'failed' }
        exit_code = $exitCode
        duration_ms = $stopwatch.ElapsedMilliseconds
        output = $joinedOutput
    }
}

$startedAt = [DateTimeOffset]::UtcNow
$results = @()
foreach ($case in $cases) {
    Write-Host "Running required case: $($case.id)"
    $results += Invoke-RequiredCase -Case $case
}
$finishedAt = [DateTimeOffset]::UtcNow
$passed = @($results | Where-Object { $_.status -eq 'passed' }).Count
$failed = $results.Count - $passed
$runId = $startedAt.ToString('yyyyMMddTHHmmssfffZ')
$evidence = [ordered]@{
    schema_version = '1.0'
    run_id = $runId
    started_at = $startedAt.ToString('o')
    finished_at = $finishedAt.ToString('o')
    repository = $repoRoot
    git_commit = (& git -C $repoRoot rev-parse HEAD).Trim()
    catalog_status = [string]$catalog.status
    total = $results.Count
    passed = $passed
    failed = $failed
    results = $results
}

New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
$destination = Join-Path $EvidenceRoot "required-cases-$runId.json"
$temporary = "$destination.tmp-$PID"
$json = $evidence | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText(
    $temporary,
    $json,
    [System.Text.UTF8Encoding]::new($false)
)
Move-Item -LiteralPath $temporary -Destination $destination
Write-Host (
    "Required cases: $passed passed, $failed failed; " +
    "evidence=$destination"
)
if ($failed -gt 0) {
    exit 1
}
