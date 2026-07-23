# Runtime comparison

Status: `PARTIAL`

Matching vLLM and SGLang stable 12B MTP-OFF baselines and a controlled
SGLang exact-target MTP ON/OFF pair completed. vLLM MTP-ON and 31B do not yet
have matching fixed-condition runs, so no runtime is selected from
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
| vLLM exact-fix, MTP ON | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| SGLang stable, MTP OFF | 60.98 s weight load | 42.635 / 50.426 ms | 18.561 / 18.931 ms | 54.335 mean | >=17,957 MiB endpoint snapshot | Passed separate smoke | Passed red-image smoke | NOT_RUN | 0/10 |
| SGLang exact target, MTP OFF | ~132.69 s target | 427.834 / 502.049 ms | 171.786 / 172.388 ms | 5.885 mean | >=28,907 MiB endpoint snapshot | NOT_RUN on exact-off endpoint | NOT_RUN on exact-off endpoint | NOT_RUN | 0/10 |
| SGLang stable, MTP ON | 132.69 s target + 5.04 s assistant | 447.962 / 523.587 ms | 106.929 / 113.024 ms | 9.441 mean | >=28,728 MiB endpoint snapshot | Passed separate smoke | Passed red-image smoke | NOT_RUN | 0/10 |
| Windows fallback | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

Final selection and ADR status remain pending until all applicable rows contain
measured values and evidence IDs.

Within the controlled exact-target pair, one-step MTP raised mean output rate
from 5.885 to 9.441 tokens/s (1.60×), reduced TPOT p50 from 171.786 to
106.929 ms, and reduced mean total request time by 37.0%. TTFT p50 increased
from 427.834 to 447.962 ms. Tool/schema and multimodal parity on the exact-off
endpoint remains open, so MTP stays disabled by default.
