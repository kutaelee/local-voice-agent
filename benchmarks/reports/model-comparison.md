# Model comparison

Status: `PARTIAL`

The vLLM/SGLang W4A16 MTP-OFF baselines and controlled exact-target MTP
ON/OFF pairs completed. The 31B rows remain open; no final runtime or model
selection is claimed.

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
| Gemma 4 12B exact target MTP OFF (vLLM) | 54.916 / 59.106 ms | 16.998 / 17.357 ms | 59.278 mean | N/A | >=28,276 MiB endpoint snapshot | Passed same-run functional gate | Valid `{}` in same-run functional gate | 10/10 latency samples | 0/0 |
| Gemma 4 12B MTP ON (vLLM exact pair) | 61.227 / 74.725 ms | 11.938 / 12.583 ms | 85.260 mean | 0.772 final cumulative metric | >=28,310 MiB endpoint snapshot | Passed same-run functional gate | Valid `{}` in same-run functional gate | 10/10 latency samples | 0/0 |
| Gemma 4 12B exact target MTP OFF (SGLang) | 427.834 / 502.049 ms | 171.786 / 172.388 ms | 5.885 mean | N/A | >=28,907 MiB endpoint snapshot | NOT_RUN on exact-off endpoint | NOT_RUN on exact-off endpoint | 10/10 latency samples | 0/0 |
| Gemma 4 12B MTP ON (SGLang exact pair) | 447.962 / 523.587 ms | 106.929 / 113.024 ms | 9.441 mean | 0.7687 mean over 16 periodic log observations | >=28,728 MiB endpoint snapshot | Passed separate smoke | Valid `{}` in separate smoke | 10/10 latency samples | 0/0 |
| Gemma 4 31B MTP OFF | NOT_RUN | NOT_RUN | NOT_RUN | N/A | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Gemma 4 31B MTP ON | Functional probe only | Functional probe only | NOT_RUN | Periodic logs observed; not aggregated | >=29,715 MiB polled during load | Passed separate probe | Valid `{}` in separate probe | 4/4 functional requests | 0/0 |

Selection remains pending. Raw measurements will be stored in
`benchmarks/results/raw-results.json` with evidence references.
