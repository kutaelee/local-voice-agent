[CmdletBinding()]
param(
    [switch]$PlanOnly
)

if (-not $PlanOnly) {
    throw 'Benchmark harness is not implemented in Slice 0. Use -PlanOnly.'
}

@'
Planned fixed-condition comparisons:
- Gemma 4 12B/31B, MTP off/on
- num_speculative_tokens: 1, 2, 3, runtime auto
- vLLM 0.25.1 vs SGLang 0.5.15.post1
- same revision, context, prompts, sampling, output tokens, tools and GPU state
- TTFT, TPOT, tok/s, voice latency, MTP acceptance, VRAM, OOM, tool/JSON accuracy
'@
