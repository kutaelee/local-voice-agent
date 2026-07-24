# Model comparison

Status: `COMPLETE_FOR_RUNTIME_SELECTION`

The vLLM/SGLang W4A16 MTP-OFF baselines and controlled exact-target MTP
ON/OFF pairs completed. A constrained 31B exact-target ON/OFF pair also
completed in vLLM. SGLang's 31B W4A16 path failed its Marlin repack gate and
its exact target exceeded the bounded first-request timeout, so those failures
are part of the selection evidence rather than missing rows.

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
| Gemma 4 31B exact target MTP OFF (vLLM) | 5,677.493 / 5,698.739 ms | 2,609.246 / 2,650.088 ms | 0.407 mean | N/A | 26,552 MiB endpoint snapshot | Passed same-run functional gate | Valid `{}` in same-run gate | 3/3 latency samples | 0/0 |
| Gemma 4 31B MTP ON (vLLM exact pair) | 5,674.851 / 5,767.266 ms | 1,286.360 / 1,316.968 ms | 0.823 mean | 0.667-1.0 interval observations; not request-weighted | 27,731 MiB endpoint snapshot | Passed same-run functional gate | Valid `{}` in same-run gate | 3/3 latency samples | 0/0 |
| Gemma 4 31B W4A16 MTP OFF (SGLang) | LOAD_FAILED | LOAD_FAILED | LOAD_FAILED | N/A | No serving endpoint | NOT_RUN | NOT_RUN | 0/0 | Marlin repack rejected width 8,608 |
| Gemma 4 31B exact target MTP OFF (SGLang) | REQUEST_TIMEOUT | REQUEST_TIMEOUT | REQUEST_TIMEOUT | N/A | 23.79 GiB model + 0.87 GiB KV reported | NOT_RUN | NOT_RUN | 0/1 | First request exceeded 120 s |

## Selection

- Default conversational model: 12B W4A16 on stable vLLM, MTP OFF.
- On-demand escalation model: 31B W4A16 on stable vLLM, text-only.
- Exact-pair MTP: benchmarked but disabled by default because the checkpoints
  are text-only in the validated vLLM path and require heavy CPU offload.
- SGLang: retained as an isolated 12B comparison environment, not selected for
  31B serving.

For the constrained 31B vLLM pair, one MTP token raised measured output rate
from 0.407 to 0.823 tokens/s (2.022x), reduced TPOT p50 by 50.7%, and reduced
mean total request time by 44.2%; TTFT was effectively unchanged. These three
short samples establish the required ON/OFF comparison, not an unconstrained
production throughput claim. Evidence references and hashes are in
`benchmarks/results/raw-results.json`.
