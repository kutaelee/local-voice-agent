# Model comparison

Status: `NOT_RUN`

No fixed-condition 12B/31B or MTP ON/OFF benchmark has completed. Preliminary
single-request observations belong in `docs/performance-report.md` and are not
copied into this comparison.

## Required fixed conditions

- exact target and assistant revisions and hashes;
- runtime/version/runner and quantization;
- max context, prompt, tool schema, sampling, and output-token cap;
- background processes and GPU power/resource state;
- warm/cold classification and repetition count.

## Result matrix

| Model condition | TTFT p50/p95 | TPOT p50/p95 | tok/s | MTP acceptance | Peak VRAM | Tool selection | Argument validity | Completion | OOM/crash |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Gemma 4 12B MTP OFF | NOT_RUN | NOT_RUN | NOT_RUN | N/A | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Gemma 4 12B MTP ON | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Gemma 4 31B MTP OFF | NOT_RUN | NOT_RUN | NOT_RUN | N/A | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Gemma 4 31B MTP ON | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

Selection remains pending. Raw measurements will be stored in
`benchmarks/results/raw-results.json` with evidence references.
