[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [Parameter(ParameterSetName = 'Plan')]
    [switch]$PlanOnly,

    [Parameter(ParameterSetName = 'Validate')]
    [switch]$ValidateCatalog,

    [Parameter(Mandatory, ParameterSetName = 'Run')]
    [ValidateSet('vllm', 'sglang', 'windows-fallback')]
    [string]$Runtime,

    [Parameter(Mandatory, ParameterSetName = 'Run')]
    [ValidatePattern('^[a-z0-9][a-z0-9._-]{1,79}$')]
    [string]$Condition,

    [Parameter(Mandatory, ParameterSetName = 'Run')]
    [string]$BaseUrl,

    [Parameter(Mandatory, ParameterSetName = 'Run')]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._/-]{1,199}$')]
    [string]$Model,

    [Parameter(Mandatory, ParameterSetName = 'Run')]
    [ValidatePattern('^[a-f0-9]{40}$')]
    [string]$ModelRevision,

    [Parameter(ParameterSetName = 'Run')]
    [ValidatePattern('^[A-Z][A-Z0-9_]{2,63}$')]
    [string]$ApiKeyEnvironment = 'LVA_RUNTIME_API_KEY',

    [Parameter(ParameterSetName = 'Run')]
    [ValidateRange(1, 100)]
    [int]$Samples = 10,

    [Parameter(ParameterSetName = 'Run')]
    [ValidateRange(8, 4096)]
    [int]$MaxTokens = 128,

    [Parameter(ParameterSetName = 'Run')]
    [switch]$MtpEnabled,

    [Parameter(ParameterSetName = 'Run')]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._=,+-]{1,127}$')]
    [string]$MtpConfig = 'disabled',

    [Parameter(ParameterSetName = 'Run')]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = 'C:\Dev\Repos\local-voice-agent'
$benchmarkScript = Join-Path $repoRoot 'scripts\benchmark-openai-latency.py'
$python = (
    'C:\Dev\Tools\LocalVoiceAgent\runtimes\' +
    'tool-executor\.venv\Scripts\python.exe'
)
$evidenceRoot = 'E:\Data\LocalVoiceAgent\benchmarks\results'

if ($ValidateCatalog) {
    & $python (Join-Path $repoRoot 'scripts\validate-benchmark-catalog.py')
    exit $LASTEXITCODE
}

if ($PlanOnly) {
    @'
Fixed-condition comparison runner:
- Connects only to an already-running loopback OpenAI-compatible endpoint.
- Never starts, stops, unloads, or reconfigures a model runtime.
- Uses 10 concurrency-1 streaming samples unless explicitly overridden.
- Records target revision, MTP condition, latency, token usage, and endpoint
  GPU snapshots in a new external evidence file.
- Tool/schema, multimodal, voice, model-switch, and MTP acceptance evidence
  remain separate gates and must be joined in the comparison report.
'@
    exit 0
}

if (
    -not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $benchmarkScript -PathType Leaf)
) {
    throw 'Registered benchmark runtime or script is unavailable.'
}

$uri = $null
if (
    -not [Uri]::TryCreate($BaseUrl, [UriKind]::Absolute, [ref]$uri) -or
    $uri.Scheme -ne 'http' -or
    $uri.DnsSafeHost -notin @('localhost', '127.0.0.1', '::1') -or
    $uri.AbsolutePath -ne '/' -or
    -not [string]::IsNullOrEmpty($uri.UserInfo) -or
    -not [string]::IsNullOrEmpty($uri.Query) -or
    -not [string]::IsNullOrEmpty($uri.Fragment)
) {
    throw 'BaseUrl must be a loopback HTTP origin without a path.'
}

$apiKey = [Environment]::GetEnvironmentVariable(
    $ApiKeyEnvironment,
    'Process'
)
if ([string]::IsNullOrEmpty($apiKey) -or $apiKey.Length -lt 32) {
    throw (
        "Set $ApiKeyEnvironment to the already-running runtime's " +
        'API key (at least 32 characters).'
    )
}

if ([string]::IsNullOrEmpty($OutputPath)) {
    $stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
    $OutputPath = Join-Path (
        $evidenceRoot
    ) "$Runtime-$Condition-$stamp.json"
}
$fullOutput = [IO.Path]::GetFullPath($OutputPath)
$fullEvidenceRoot = [IO.Path]::GetFullPath($evidenceRoot).TrimEnd('\')
if (
    -not $fullOutput.StartsWith(
        "$fullEvidenceRoot\",
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    [IO.Path]::GetExtension($fullOutput) -ne '.json'
) {
    throw "OutputPath must be a JSON file beneath $evidenceRoot."
}
if (Test-Path -LiteralPath $fullOutput) {
    throw "Refusing to overwrite benchmark evidence: $fullOutput"
}

$arguments = @(
    $benchmarkScript,
    '--base-url', $uri.GetLeftPart([UriPartial]::Authority),
    '--model', $Model,
    '--runtime', $Runtime,
    '--condition', $Condition,
    '--model-revision', $ModelRevision,
    '--samples', [string]$Samples,
    '--max-tokens', [string]$MaxTokens,
    '--api-key-env', $ApiKeyEnvironment,
    '--mtp-config', $MtpConfig,
    '--output', $fullOutput
)
if ($MtpEnabled) {
    $arguments += '--mtp-enabled'
}

& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Benchmark failed with exit code $LASTEXITCODE."
}
$hash = (Get-FileHash -LiteralPath $fullOutput -Algorithm SHA256).
    Hash.
    ToLowerInvariant()
Write-Output "benchmark_evidence=$fullOutput"
Write-Output "benchmark_evidence_sha256=$hash"
