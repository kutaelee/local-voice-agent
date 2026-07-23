[CmdletBinding(DefaultParameterSetName = 'Plan')]
param(
    [Parameter(ParameterSetName = 'Plan')]
    [switch]$PlanOnly,

    [Parameter(Mandatory, ParameterSetName = 'Validate')]
    [switch]$ValidatePrerequisites,

    [Parameter(Mandatory, ParameterSetName = 'Environments')]
    [switch]$InstallProjectEnvironments,

    [Parameter(Mandatory, ParameterSetName = 'Android')]
    [switch]$BuildAndroid,

    [Parameter(Mandatory, ParameterSetName = 'All')]
    [switch]$InstallAndBuild
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$toolEnvironment = (
    'C:\Dev\Tools\LocalVoiceAgent\runtimes\tool-executor\.venv'
)
$browserRoot = (
    'C:\Dev\Tools\LocalVoiceAgent\browsers\playwright-1.61.0'
)
$androidSdk = 'C:\Dev\SDK\Android'
$jdk = 'C:\Dev\Java\jdk17'
$gradleCache = 'E:\Cache\LocalVoiceAgent\gradle'
$dataRoots = @(
    'C:\Dev\Tools\LocalVoiceAgent\runtimes',
    'C:\Dev\Tools\LocalVoiceAgent\browsers',
    'E:\Cache\LocalVoiceAgent',
    'E:\Data\LocalVoiceAgent'
)

function Assert-CanonicalRepository {
    $actual = [IO.Path]::GetFullPath(
        (Get-Location).Path
    ).TrimEnd('\')
    if (
        -not $actual.Equals(
            $repoRoot,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Run this script from the canonical repository: $repoRoot"
    }
    if (-not (Test-Path -LiteralPath '.git' -PathType Container)) {
        throw 'The canonical repository Git metadata is unavailable.'
    }
}

function Get-PrerequisiteReport {
    $commands = [ordered]@{
        git = [bool](Get-Command git.exe -ErrorAction SilentlyContinue)
        git_lfs = $false
        uv = [bool](Get-Command uv.exe -ErrorAction SilentlyContinue)
        wsl = [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue)
        docker = [bool](Get-Command docker.exe -ErrorAction SilentlyContinue)
    }
    if ($commands.git) {
        & git.exe lfs version *> $null
        $commands.git_lfs = $LASTEXITCODE -eq 0
    }

    $ubuntu = $false
    $wslUv = $false
    if ($commands.wsl) {
        $distributions = @(
            & wsl.exe --list --quiet 2>$null |
                ForEach-Object { $_.Trim([char]0).Trim() } |
                Where-Object { $_ }
        )
        $ubuntu = $distributions -contains 'Ubuntu'
        if ($ubuntu) {
            & wsl.exe -d Ubuntu -- bash -lc (
                'command -v uv >/dev/null || test -x "${HOME}/.local/bin/uv"'
            )
            $wslUv = $LASTEXITCODE -eq 0
        }
    }

    $paths = [ordered]@{
        repository = Test-Path -LiteralPath $repoRoot -PathType Container
        jdk_17 = Test-Path -LiteralPath (
            Join-Path $jdk 'bin\java.exe'
        ) -PathType Leaf
        android_sdk = Test-Path -LiteralPath (
            Join-Path $androidSdk 'cmdline-tools\latest\bin\sdkmanager.bat'
        ) -PathType Leaf
        android_platform_37 = (
            (
                Test-Path -LiteralPath (
                    Join-Path $androidSdk 'platforms\android-37.0'
                ) -PathType Container
            ) -or (
                Test-Path -LiteralPath (
                    Join-Path $androidSdk 'platforms\android-37'
                ) -PathType Container
            )
        )
    }

    [pscustomobject]@{
        schema_version = '1.0'
        commands = $commands
        wsl = [ordered]@{
            ubuntu = $ubuntu
            uv = $wslUv
        }
        paths = $paths
        ready_for_project_environments = (
            $commands.git -and
            $commands.git_lfs -and
            $commands.uv -and
            $commands.wsl -and
            $ubuntu -and
            $wslUv -and
            $paths.repository
        )
        ready_for_android_build = (
            $paths.jdk_17 -and
            $paths.android_sdk -and
            $paths.android_platform_37
        )
    }
}

function Assert-ProjectEnvironmentPrerequisites {
    $report = Get-PrerequisiteReport
    if (-not $report.ready_for_project_environments) {
        $report | ConvertTo-Json -Depth 5
        throw (
            'Project-environment prerequisites are incomplete. ' +
            'No system package was installed.'
        )
    }
}

function Install-ProjectEnvironments {
    Assert-CanonicalRepository
    Assert-ProjectEnvironmentPrerequisites

    foreach ($path in $dataRoots) {
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            New-Item -ItemType Directory -Path $path | Out-Null
        }
    }

    $previousUvEnvironment = $env:UV_PROJECT_ENVIRONMENT
    $previousBrowserPath = $env:PLAYWRIGHT_BROWSERS_PATH
    try {
        $env:UV_PROJECT_ENVIRONMENT = $toolEnvironment
        & uv.exe sync `
            --project apps/tool-executor `
            --locked `
            --extra test
        if ($LASTEXITCODE -ne 0) {
            throw "Tool Executor environment sync exited $LASTEXITCODE."
        }

        $env:PLAYWRIGHT_BROWSERS_PATH = $browserRoot
        $toolPython = Join-Path $toolEnvironment 'Scripts\python.exe'
        & $toolPython -m playwright install chromium
        if ($LASTEXITCODE -ne 0) {
            throw "Playwright browser installation exited $LASTEXITCODE."
        }
    }
    finally {
        $env:UV_PROJECT_ENVIRONMENT = $previousUvEnvironment
        $env:PLAYWRIGHT_BROWSERS_PATH = $previousBrowserPath
    }

    & wsl.exe -d Ubuntu -- bash (
        '/mnt/c/Dev/Repos/local-voice-agent/scripts/' +
        'install-project-environments.sh'
    )
    if ($LASTEXITCODE -ne 0) {
        throw "WSL project-environment sync exited $LASTEXITCODE."
    }

    Write-Output 'project_environments=installed_and_locked'
    Write-Output "tool_executor_environment=$toolEnvironment"
    Write-Output (
        'pc_server_environment=' +
        '/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv'
    )
}

function Invoke-AndroidBuild {
    Assert-CanonicalRepository
    $report = Get-PrerequisiteReport
    if (-not $report.ready_for_android_build) {
        $report | ConvertTo-Json -Depth 5
        throw 'Android build prerequisites are incomplete.'
    }
    if (-not (Test-Path -LiteralPath $gradleCache -PathType Container)) {
        New-Item -ItemType Directory -Path $gradleCache | Out-Null
    }

    $previousJavaHome = $env:JAVA_HOME
    $previousAndroidHome = $env:ANDROID_HOME
    $previousAndroidSdkRoot = $env:ANDROID_SDK_ROOT
    $previousGradleHome = $env:GRADLE_USER_HOME
    try {
        $env:JAVA_HOME = $jdk
        $env:ANDROID_HOME = $androidSdk
        $env:ANDROID_SDK_ROOT = $androidSdk
        $env:GRADLE_USER_HOME = $gradleCache
        Push-Location (Join-Path $repoRoot 'apps\android-client')
        try {
            & .\gradlew.bat `
                --no-daemon `
                --non-interactive `
                clean `
                testDebugUnitTest `
                lintDebug `
                assembleDebug `
                assembleRelease
            if ($LASTEXITCODE -ne 0) {
                throw "Android build exited $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }
    finally {
        $env:JAVA_HOME = $previousJavaHome
        $env:ANDROID_HOME = $previousAndroidHome
        $env:ANDROID_SDK_ROOT = $previousAndroidSdkRoot
        $env:GRADLE_USER_HOME = $previousGradleHome
    }
    Write-Output 'android_build=passed'
}

if ($PSCmdlet.ParameterSetName -eq 'Plan') {
    @'
Local Voice Agent non-administrator installation plan

Prerequisites validated but not installed by this script:
- Git + Git LFS, uv, WSL2 Ubuntu, Docker Desktop
- JDK 17 and Android command-line SDK/API 37

Project-local actions:
1. -ValidatePrerequisites reports readiness without mutation.
2. -InstallProjectEnvironments synchronizes hash/lock-bound Tool Executor,
   PC-server, TLS tools, and Playwright browser assets into registered external
   runtime/cache paths. It never uses global pip or modifies system PATH.
3. .\scripts\install-wsl.sh installs selected GPU/STT/VAD/TTS isolates.
4. .\scripts\download-models.ps1 validates and downloads pinned model roles.
5. -BuildAndroid runs clean unit tests, lint, debug, and unsigned release builds.
6. -InstallAndBuild performs steps 2 and 5.

Administrator, driver, WSL feature, firewall, registry, system PATH, full
Android Studio, and public-listener changes remain manual approval gates.
'@
    exit 0
}

if ($ValidatePrerequisites) {
    Assert-CanonicalRepository
    Get-PrerequisiteReport | ConvertTo-Json -Depth 5
    exit 0
}
if ($InstallProjectEnvironments -or $InstallAndBuild) {
    Install-ProjectEnvironments
}
if ($BuildAndroid -or $InstallAndBuild) {
    Invoke-AndroidBuild
}
