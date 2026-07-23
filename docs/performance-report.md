# Performance report

Status: preliminary smoke observations only; the fixed-condition benchmark
has not completed. Shared-GPU retries on 2026-07-24 were safely yielded when
ComfyUI reclaimed the device, so no partial latency result is reported.

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

## Preliminary vLLM 31B text smoke

This is a constrained compatibility run on a GPU shared with an unrelated
Ollama workload, not a fixed-condition benchmark. Multimodal input and MTP
were disabled. Polling does not capture a true VRAM peak.

The first launch used `gpu-memory-utilization=0.72`. It loaded the weights in
110.04 seconds and reported 18.7 GiB model memory, then failed cleanly because
the computed KV-cache budget was -3.17 GiB. The retry used an explicit 384 MiB
KV cache rather than claiming more shared GPU memory.

| Item | Observed |
|---|---:|
| Runtime/model | vLLM 0.25.1 V1 runner / pinned 31B W4A16 |
| Filesystem/context | WSL 9P `/mnt/e` / 256 tokens |
| Concurrency / KV cache | 1 sequence / 384 MiB, 421 tokens |
| Checkpoint size reported by vLLM | 21.67 GiB |
| Weight read time | 106.34 s |
| Model load time / memory | 107.34 s / 18.7 GiB |
| Engine profile/cache/warmup | 2.31 s |
| Highest polled total GPU memory | 27,187 MiB |
| Minimum observed free GPU memory | 5,001 MiB |
| Korean text | 2,719.56 ms, correct answer; includes first-inference JIT |
| Automatic tool call | 302.84 ms, valid `inspect_gpu({})` |
| JSON Schema request | 1,575.09 ms, valid object |
| Streaming | 67.33 ms TTFT, 1,504.65 ms total, 51 chunks |
| Completed API requests | 4 / 4; zero error/abort |

## Preliminary SGLang 12B MTP functional smoke

This is a functional compatibility result, not the fixed-condition MTP
benchmark. SGLang 0.5.15.post1 recognized the exact paired assistant as
`FROZEN_KV_MTP`. Loading the full target and assistant without offload used
30.08 GiB and failed before health because no KV cache could be allocated.
With 4 GiB of official CPU weight offload, the same pair became healthy:

| Item | Observed |
|---|---:|
| Target / assistant load | 132.92 s / 5.58 s |
| Reported target / assistant GPU weight memory | 19.12 GiB / 0.50 GiB |
| Runtime memory available after KV allocation | 4.39 GiB |
| Health-time total GPU memory | 28,619 MiB |
| Speculation | 1 step, 2 draft tokens, top-k 1 |
| Functional checks | Korean, tool call, strict JSON, streaming, image, thinking passed |
| Streaming sample | 402.958 ms TTFT / 5,704.630 ms total |
| Point-in-time speculative acceptance | 0.625; not a distribution |

The full 10-sample latency run was interrupted when a separately managed
ComfyUI render acquired the shared GPU. Only the owned SGLang process group
was stopped. No p50/p95 or speedup is claimed for this interrupted run.
