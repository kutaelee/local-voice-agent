# Runtime comparison

Status: `NOT_RUN`

vLLM and SGLang have not yet completed the same fixed-condition benchmark.
No runtime is selected from tokens-per-second alone.

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
| vLLM stable, MTP OFF | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| vLLM exact-fix, MTP ON | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| SGLang stable, MTP OFF | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| SGLang stable, MTP ON | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Windows fallback | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

Final selection and ADR status remain pending until all applicable rows contain
measured values and evidence IDs.
