# Performance report

Status: preliminary 12B smoke observations only; fixed-condition benchmark has
not run.

The project does not claim TTFT, TPOT, tokens/s, first-audio latency, MTP
speedup, VRAM peak, or end-to-end voice latency until the benchmark harness
uses fixed model revisions, prompts, sampling, context, background load, and
GPU power conditions.

Planned results:

- `benchmarks/results/raw-results.json`
- `benchmarks/reports/model-comparison.md`
- `benchmarks/reports/runtime-comparison.md`

## Preliminary vLLM 12B smoke

These observations are not benchmark claims. The machine was shared with
other setup work, requests were single samples, and polling does not capture a
true VRAM peak.

| Item | Observed |
|---|---:|
| Runtime/model | vLLM 0.25.1 V1 runner / pinned 12B W4A16 |
| Filesystem/context | WSL 9P `/mnt/e` / 8,192 tokens |
| GPU memory utilization setting | 0.55 |
| Checkpoint size reported by vLLM | 9.56 GiB |
| Weight read time | 69.69 s |
| Model load time | 71.30 s |
| Model weight memory | 8.28 GiB |
| Engine profile/cache/warmup | 101.78 s |
| torch.compile | 31.31 s |
| CUDA graph capture | 9 s |
| Available KV cache | 6.56 GiB / 44,614 tokens |
| Maximum 8K-request concurrency estimate | 5.45x |
| Highest polled total GPU memory | 18,881 MiB |
| Korean text request | 201.97 ms, 9 completion tokens |
| Automatic tool-call request | 236.48 ms, valid `{}` arguments |
| JSON Schema request | 1,181.88 ms, valid object |
| Streaming sample | 175.88 ms TTFT, 577.90 ms total, 48 tokens |
| 32x32 PNG request | 812.56 ms, correct `Red` response |

The first PowerShell 5.1 request encoded Korean incorrectly. Sending explicit
UTF-8 bytes, and then repeating with the WSL Python client, produced correct
Korean input/output. Android and PC clients must always set and test UTF-8
transport explicitly.
