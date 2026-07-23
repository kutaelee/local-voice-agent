# Runtime comparison

Status: `PARTIAL`

The vLLM stable 12B MTP-OFF baseline completed. SGLang and MTP-ON do not yet
have the same completed fixed-condition run, so no runtime is selected from
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
| SGLang stable, MTP OFF | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| SGLang stable, MTP ON | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Windows fallback | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

Final selection and ADR status remain pending until all applicable rows contain
measured values and evidence IDs.
