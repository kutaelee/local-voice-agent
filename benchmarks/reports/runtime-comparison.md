# Runtime comparison

Status: `COMPLETE_FOR_RUNTIME_SELECTION`

Matching vLLM and SGLang stable 12B MTP-OFF baselines and controlled
exact-target MTP ON/OFF pairs completed. The 31B vLLM ON/OFF pair, live
12B-to-31B-to-12B switch, and bounded SGLang 31B failure probes complete the
runtime-selection evidence. Selection follows functional safety first, not
tokens-per-second alone.

## Decision order

1. Tool selection and argument correctness.
2. Stability and OOM rate.
3. Multimodal behavior.
4. End-to-end voice latency.
5. Model-switch reliability.
6. Throughput.
7. Installation and maintenance complexity.

## Result matrix

| Runtime condition | Model load | TTFT p50/p95 | TPOT p50/p95 | tok/s | Peak VRAM | Tool completion | Multimodal | Switch recovery | Crash/OOM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| vLLM stable, MTP OFF | 132.38 s prior cold load | 48.034 / 547.537 ms | 7.980 / 8.190 ms | 126.223 mean | >=25,337 MiB endpoint snapshot | Passed separate smoke | Passed red-image smoke | Unit/API only | 0/10 |
| vLLM exact-fix, MTP OFF | 126.95 s target | 54.916 / 59.106 ms | 16.998 / 17.357 ms | 59.278 mean | >=28,276 MiB endpoint snapshot | Passed same-run gate | Blocked by exact target config | NOT_RUN | 0/10 |
| vLLM exact-fix, MTP ON | 135.20 s target + assistant | 61.227 / 74.725 ms | 11.938 / 12.583 ms | 85.260 mean | >=28,310 MiB endpoint snapshot | Passed same-run gate | Blocked by exact target config | NOT_RUN | 0/10 |
| SGLang stable, MTP OFF | 60.98 s weight load | 42.635 / 50.426 ms | 18.561 / 18.931 ms | 54.335 mean | >=17,957 MiB endpoint snapshot | Passed separate smoke | Passed red-image smoke | NOT_RUN | 0/10 |
| SGLang exact target, MTP OFF | ~132.69 s target | 427.834 / 502.049 ms | 171.786 / 172.388 ms | 5.885 mean | >=28,907 MiB endpoint snapshot | NOT_RUN on exact-off endpoint | NOT_RUN on exact-off endpoint | NOT_RUN | 0/10 |
| SGLang stable, MTP ON | 132.69 s target + 5.04 s assistant | 447.962 / 523.587 ms | 106.929 / 113.024 ms | 9.441 mean | >=28,728 MiB endpoint snapshot | Passed separate smoke | Passed red-image smoke | NOT_RUN | 0/10 |
| vLLM exact-fix, 31B MTP OFF | CPU-offloaded exact target | 5,677.493 / 5,698.739 ms | 2,609.246 / 2,650.088 ms | 0.407 mean | 26,552 MiB endpoint snapshot | Passed same-run gate | Text-only profile | Live switch passed via W4A16 profile | 0/3 |
| vLLM exact-fix, 31B MTP ON | CPU-offloaded target + assistant | 5,674.851 / 5,767.266 ms | 1,286.360 / 1,316.968 ms | 0.823 mean | 27,731 MiB endpoint snapshot | Passed same-run gate | Text-only profile | Live switch passed via W4A16 profile | 0/3 |
| SGLang stable, 31B W4A16 | Failed during Marlin repack | NOT_AVAILABLE | NOT_AVAILABLE | NOT_AVAILABLE | No endpoint | NOT_RUN | NOT_RUN | NOT_SELECTED | 1 load failure |
| SGLang exact target, 31B MTP OFF | 489.76 s weight load | First request timed out | First request timed out | NOT_AVAILABLE | 23.79 GiB model + 0.87 GiB KV | NOT_RUN | Text-only probe | NOT_SELECTED | 0 OOM; 1 timeout |
| Windows fallback | 2.94 s CPU load | 640.311 ms single smoke | NOT_MEASURED | 7.322 observed | CPU-only | Tool/schema passed | Text-only | Recovery path passed | 0 functional errors |

## Runtime selection

Stable vLLM is selected for the 12B default and 31B on-demand production
profiles. It passed tool/schema/multimodal checks for 12B, the constrained 31B
functional checks, and an actual health-verified 12B-to-31B-to-12B process
sequence. SGLang remains installed for reproducible 12B comparisons but is
not selected for 31B. Native llama.cpp remains the WSL-failure diagnostic
fallback.

Within vLLM's controlled exact-target pair, one-step MTP raised mean output
rate from 59.278 to 85.260 tokens/s (1.438x), reduced TPOT p50 from 16.998
to 11.938 ms, and reduced mean total request time by 29.6%. Both same-run
functional gates passed, but this exact target remains text-only in vLLM.

Within the controlled exact-target pair, one-step MTP raised mean output rate
from 5.885 to 9.441 tokens/s (1.60×), reduced TPOT p50 from 171.786 to
106.929 ms, and reduced mean total request time by 37.0%. TTFT p50 increased
from 427.834 to 447.962 ms. Tool/schema and multimodal parity on the exact-off
endpoint remains open, so MTP stays disabled by default.

Within vLLM's constrained 31B exact-target pair, one-step MTP raised mean
output rate from 0.407 to 0.823 tokens/s (2.022x), reduced TPOT p50 from
2,609.246 to 1,286.360 ms, and reduced mean total request time from
44,985.775 to 25,106.414 ms. The 36 GiB CPU offload, text-only limitation,
and long load/request latency keep this profile disabled despite the measured
gain.
