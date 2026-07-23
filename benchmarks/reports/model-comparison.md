# Model comparison

Status: `PARTIAL`

The vLLM/SGLang W4A16 MTP-OFF baselines and the SGLang exact-pair MTP-ON row
completed. Exact-target MTP-OFF, vLLM MTP-ON, and 31B rows remain open; no
cross-condition speedup or final model selection is claimed.

## Required fixed conditions

- exact target and assistant revisions and hashes;
- runtime/version/runner and quantization;
- max context, prompt, tool schema, sampling, and output-token cap;
- background processes and GPU power/resource state;
- warm/cold classification and repetition count.

## Result matrix

| Model condition | TTFT p50/p95 | TPOT p50/p95 | tok/s | MTP acceptance | Peak VRAM | Tool selection | Argument validity | Completion | OOM/crash |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Gemma 4 12B MTP OFF | 48.034 / 547.537 ms | 7.980 / 8.190 ms | 126.223 mean | N/A | >=25,337 MiB endpoint snapshot | Passed separate smoke | Valid `{}` in separate smoke | 10/10 latency samples | 0/0 |
| Gemma 4 12B MTP ON (SGLang exact pair) | 447.962 / 523.587 ms | 106.929 / 113.024 ms | 9.441 mean | 0.7687 mean over 16 periodic log observations | >=28,728 MiB endpoint snapshot | Passed separate smoke | Valid `{}` in separate smoke | 10/10 latency samples | 0/0 |
| Gemma 4 31B MTP OFF | NOT_RUN | NOT_RUN | NOT_RUN | N/A | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Gemma 4 31B MTP ON | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

Selection remains pending. Raw measurements will be stored in
`benchmarks/results/raw-results.json` with evidence references.
