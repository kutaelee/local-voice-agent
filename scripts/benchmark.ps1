[CmdletBinding()]
param(
    [switch]$PlanOnly,
    [switch]$ValidateCatalog
)

if ($ValidateCatalog) {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $validator = (Join-Path $repoRoot 'scripts\validate-benchmark-catalog.py').
        Replace('\', '/').
        Replace('C:', '/mnt/c')
    & wsl.exe -d Ubuntu -- python3 $validator
    exit $LASTEXITCODE
}

if (-not $PlanOnly) {
    throw 'Runtime benchmark is not implemented. Use -PlanOnly or -ValidateCatalog.'
}

@'
Planned fixed-condition comparisons:
- Gemma 4 12B/31B, MTP off/on
- num_speculative_tokens: 1, 2, 3, runtime auto
- vLLM 0.25.1 vs SGLang 0.5.15.post1
- same revision, context, prompts, sampling, output tokens, tools and GPU state
- TTFT, TPOT, tok/s, voice latency, MTP acceptance, VRAM, OOM, tool/JSON accuracy
'@
