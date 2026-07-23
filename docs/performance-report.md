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

The first MTP launch used the already-downloaded W4A16 target only as a
compatibility probe. vLLM selected its dedicated Gemma 4 MTP implementation,
but compilation failed on a measured tensor-width mismatch (4,864 versus
7,680). Offline tensor inspection confirmed that the assistant projection
expects the target's 3,840-wide embedding to be shared; vLLM 0.25.1 instead
kept the assistant's 1,024-wide embedding. Upstream fixed this after the
stable release. No latency, acceptance-rate, or speedup result is reported
for that failed run. The benchmark now requires both the exact
`qat-q4_0-unquantized` pair and the pinned fix runtime.

## Preliminary exact-pair MTP text smoke

This is a four-request smoke run on a machine shared with other model setup,
not a fixed-condition benchmark and not evidence of MTP speedup. The exact
Q4_0 target and matching assistant ran with one speculative token, eager mode,
the V1 runner, a 2,048-token context, and `--language-model-only`.

| Item | Observed |
|---|---:|
| Runtime | exact vLLM commit `b2b8f679d058…` / torch 2.11.0+cu130 |
| Target checkpoint / assistant | 22.28 GiB / 0.79 GiB reported |
| Target weight read / assistant read | 159.23 s / 5.77 s |
| Total model loading | 165.84 s, 23.62 GiB |
| Engine profile/cache/warmup | 54.75 s |
| GPU KV cache | 2.34 GiB / 7,260 tokens |
| Highest polled total GPU memory | 32,050 MiB; only 138 MiB free |
| Korean text | 4,950.13 ms, correct answer; includes first-inference JIT |
| Tool call | 201.72 ms, valid `inspect_gpu({})` |
| Strict structured output | 1,548.87 ms, valid object |
| Streaming | 101.15 ms TTFT, 1,038.74 ms total, 32 chunks |
| Speculative acceptance | 43 / 48 draft tokens = 89.6% |
| Completed API requests | 4 / 4; zero error/abort |

The official exact target currently omits `vision_config.num_soft_tokens`.
Normal multimodal initialization failed before weight loading, so the passing
run explicitly disabled all multimodal processing. MTP remains disabled by
default until multimodal compatibility and the fixed-condition quality,
accuracy, latency, and VRAM gates pass.

The first PowerShell 5.1 request encoded Korean incorrectly. Sending explicit
UTF-8 bytes, and then repeating with the WSL Python client, produced correct
Korean input/output. Android and PC clients must always set and test UTF-8
transport explicitly.
