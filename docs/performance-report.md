# Performance report

Status: model/runtime selection benchmark complete. Matching vLLM and SGLang
12B baselines, controlled exact-target 12B ON/OFF pairs, and a constrained
vLLM 31B ON/OFF pair completed. Physical Android end-to-end voice latency
remains a separate QA item.
Shared-GPU SGLang MTP retries on 2026-07-24 were safely yielded when ComfyUI
reclaimed the device.

The project does not claim TTFT, TPOT, tokens/s, first-audio latency, MTP
speedup, VRAM peak, or end-to-end voice latency until the benchmark harness
uses fixed model revisions, prompts, sampling, context, background load, and
GPU power conditions.

## Qwen3-TTS primary voice-clone smoke

Qwen3-TTS 12Hz 1.7B Base revision `fd4b254…` loaded on the RTX 5090 with
PyTorch 2.11.0+cu130 and SDPA. One cold load took 26.148 seconds and peak
allocated VRAM was 4,750,705,664 bytes. These are single-run smoke values, not
p50/p95 benchmarks.

| Route | Synthesis | Audio | RTF |
|---|---:|---:|---:|
| Neutral with 160 ms terminal tail | 7.914 s | 5.680 s | 1.393 |
| Happy cached reference | 4.339 s | 4.160 s | 1.043 |
| Dark cached reference | 4.978 s | 4.960 s | 1.004 |

The worker uses exact reference transcripts, a four-entry bounded prompt
cache, non-streaming text mode, and a verified 160 ms zero-PCM terminal tail.
Comma splitting was removed after listening QA exposed unnatural joins.
Physical Android listening QA for the new worker remains pending.

## User-authorized reference voice smoke

A local 8.192-second Korean reference clip was canonicalized to 24 kHz mono
PCM16 and tested against Chatterbox Multilingual V3 with exaggeration 0.5,
CFG weight 0.5, and temperature 0.8. No LLM endpoint was running during this
one-shot test.

| Metric | Result |
|---|---:|
| Model load | 16.556 s |
| Synthesis | 3.974 s |
| Generated audio | 7.080 s |
| Realtime factor | 0.561 |
| Peak allocated VRAM | 3,427,896,832 bytes |

The process exited after synthesis and observed total GPU use returned to
approximately 4.7 GiB. This proves local reference conditioning and
faster-than-realtime synthesis for one supplied utterance; it does not prove
speaker similarity, first-audio streaming latency, or a p50/p95
distribution. Physical listening remains pending. Full evidence and the
synthesized sample remain in the external application-data evidence root and
are intentionally not committed.

Planned results:

- `benchmarks/results/raw-results.json`
- `benchmarks/reports/model-comparison.md`
- `benchmarks/reports/runtime-comparison.md`

## Fixed-condition vLLM 12B MTP-OFF baseline

Ten concurrency-1 streaming samples completed with temperature 0 and a
128-token cap against exact revision
`1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee`.

| Metric | Result |
|---|---:|
| TTFT p50 / p95 | 48.034 / 547.537 ms |
| TPOT p50 / p95 | 7.980 / 8.190 ms |
| Output throughput mean | 126.223 tokens/s |
| Successful samples | 10 / 10 |
| OOM / crash | 0 / 0 |
| Highest endpoint GPU snapshot | 25,337 MiB total used; not a sampled peak |

Evidence:
`E:\Data\LocalVoiceAgent\benchmarks\results\vllm-12b-mtp-off-20260723T221500000Z.json`,
SHA-256
`fdd417bc62bdb573badff432e5541971d2326e94e3f7d53663c3c2b61401ced2`.
The unusually wide TTFT p95 includes the first warm-up sample; no outlier was
removed. This single row is not evidence of an MTP speedup or runtime win.

## Fixed-condition SGLang 12B MTP-OFF baseline

The same exact model revision, prompt catalog, temperature, 128-token cap,
streaming mode, and concurrency-1 conditions completed for SGLang
0.5.15.post1:

- successful samples: 10 / 10
- TTFT p50 / p95: 42.635 / 50.426 ms
- TPOT p50 / p95: 18.561 / 18.931 ms
- mean output rate: 54.335 tokens/s
- observed total GPU memory at the endpoint snapshot: 17,957 MiB
- OOM or crash: 0

Evidence:
`E:\Data\LocalVoiceAgent\benchmarks\results\sglang-12b-mtp-off-latency.json`,
SHA-256
`947a95570509d4bbe2cca87eed17ddfaa88cf83c895bdeb97eb818f2bafe03dc`.
This matching base row enables a direct MTP-OFF comparison, but does not settle
MTP behavior, model-switch reliability, or the final runtime selection.

## Fixed-condition SGLang 12B exact-target MTP OFF/ON

The exact target also completed ten samples with the same revision, 4 GiB CPU
offload, context, prompts, sampling, concurrency, and output cap but without
the assistant:

- MTP OFF TTFT p50 / p95: 427.834 / 502.049 ms
- MTP OFF TPOT p50 / p95: 171.786 / 172.388 ms
- MTP OFF mean output rate: 5.885 tokens/s
- MTP OFF observed endpoint GPU snapshot: 28,907 MiB
- MTP OFF evidence SHA-256:
  `d02b4667e6a36c1b39e251e565ce0154db2b8b897ad87e45974be62d74f9a3be`

Against that controlled baseline, one-step MTP:

- raised mean output rate to 9.441 tokens/s, a measured 1.60× ratio;
- reduced TPOT p50 to 106.929 ms, a 37.8% reduction;
- reduced mean total request time from 19,680.581 to 12,396.196 ms, a 37.0%
  reduction;
- increased TTFT p50 to 447.962 ms, 20.128 ms or 4.7% higher;
- completed all 10 samples with no crash or OOM.

Ten streaming samples completed with the exact target revision
`b6ed86275a6a5735884e208bfed95b445a684ca2`, matching assistant, one MTP step,
and 4 GiB CPU offload:

- successful samples: 10 / 10
- TTFT p50 / p95: 447.962 / 523.587 ms
- TPOT p50 / p95: 106.929 / 113.024 ms
- mean output rate: 9.441 tokens/s
- observed total GPU memory at endpoint snapshots: 28,728 MiB
- OOM or crash: 0
- periodic decoder acceptance observations: 16, mean 0.7687, range 0.68–0.85

The target and assistant loaded in 132.69 and 5.04 seconds. SGLang explicitly
promoted the assistant to `FROZEN_KV_MTP`. Evidence:
`E:\Data\LocalVoiceAgent\benchmarks\results\sglang-12b-mtp-on-s1-20260723T230801960Z.json`,
SHA-256
`0bbac572cb7396cc0e20975ca241ae12cd28b8d3ce394571c0fa7044f5956ad6`.
The runtime log SHA-256 is
`6590b653853d69a8a103c1c0d25925a238a843d6c4a9efeab65c453287917c2d`.

Both exact-target conditions are much slower than the W4A16 base row because
the exact checkpoint requires CPU offload. The ON/OFF pair does isolate the
assistant effect for latency, but exact-off tool/schema and multimodal parity
are still unmeasured. MTP therefore remains disabled by default.

## Fixed-condition vLLM 12B exact-target MTP OFF/ON

The isolated fix build at commit
`b2b8f679d0589f0c956f3e734cc70dab07b27b8a` ran the same exact target,
2,048-token context, prompt catalog, temperature, concurrency, and 128-token
cap with and without its matching assistant. Both conditions first passed
Korean text, `inspect_gpu({})`, strict structured output, and streaming.

| Metric | MTP OFF | MTP ON, one token |
|---|---:|---:|
| TTFT p50 / p95 | 54.916 / 59.106 ms | 61.227 / 74.725 ms |
| TPOT p50 / p95 | 16.998 / 17.357 ms | 11.938 / 12.583 ms |
| Mean output rate | 59.278 tokens/s | 85.260 tokens/s |
| Mean total request | 1,963.186 ms | 1,381.526 ms |
| Endpoint GPU snapshot | 28,276 MiB | 28,310 MiB |
| Successful samples | 10 / 10 | 10 / 10 |

One-step MTP raised mean output rate by a measured 1.438x, reduced TPOT p50
by 29.8%, and reduced mean total request time by 29.6%. TTFT p50 increased by
6.311 ms or 11.5%. The final cumulative runtime metric reported 355 accepted
of 460 drafted tokens, a 77.2% acceptance rate.

Evidence:

- OFF benchmark:
  `E:\Data\LocalVoiceAgent\benchmarks\results\vllm-12b-exact-mtp-off-20260723T233218260Z.json`,
  SHA-256
  `78ddc368bc1770917dc6ac42fd44709e563ed9df806b73f26a4bbd7d28c757dc`
- ON benchmark:
  `E:\Data\LocalVoiceAgent\benchmarks\results\vllm-12b-exact-mtp-on-s1-20260723T233655325Z.json`,
  SHA-256
  `5c8210ad669bf87ebb56435cdd333f05516c60a5c213f94e11364e74193a1e2a`
- OFF functional:
  `E:\Data\LocalVoiceAgent\runtime\evidence\vllm-12b-exact-mtp-off-functional-20260723T233218260Z.json`,
  SHA-256
  `9870135a650c9091102d226078d2261ea0279e765ad4f3e7e86bb2394fc60538`
- ON functional:
  `E:\Data\LocalVoiceAgent\runtime\evidence\vllm-12b-exact-mtp-on-s1-functional-20260723T233655325Z.json`,
  SHA-256
  `ebb9113e9a18f8ac9a4a2406806db0e3900406f8b0b80080120d0403d814b743`

The exact target still lacks the upstream multimodal configuration field
needed by this runtime path, so both controlled runs were text-only. MTP
remains disabled in production routing despite the measured latency gain.

## Fixed-condition vLLM 31B exact-target MTP OFF/ON

The exact target revision
`1e4d8beecacb8b7590c1d8bedd7335f687bf311f` ran with and without its
matching assistant under the same 36 GiB CPU offload, text-only context,
temperature 0, concurrency 1, 16-token cap, and three-sample prompt subset.
Both conditions first passed Korean text, `inspect_gpu({})`, strict structured
output, and streaming.

| Metric | MTP OFF | MTP ON, one token |
|---|---:|---:|
| TTFT p50 / p95 | 5,677.493 / 5,698.739 ms | 5,674.851 / 5,767.266 ms |
| TPOT p50 / p95 | 2,609.246 / 2,650.088 ms | 1,286.360 / 1,316.968 ms |
| Mean output rate | 0.407 tokens/s | 0.823 tokens/s |
| Mean total request | 44,985.775 ms | 25,106.414 ms |
| Endpoint GPU snapshot | 26,552 MiB | 27,731 MiB |
| Successful samples | 3 / 3 | 3 / 3 |

One-step MTP raised measured output rate by 2.022x, reduced TPOT p50 by
50.7%, and reduced mean total request time by 44.2%. TTFT p50 differed by
only 2.642 ms. Runtime intervals reported acceptance from 0.667 to 1.0, but
those interval observations are not a request-weighted acceptance benchmark.

Evidence:

- OFF benchmark SHA-256:
  `5b6314e02f846c81230edff5f4e4549c7442221f04fa4c6b17e3f895ce14d4d8`
- ON benchmark SHA-256:
  `106666fc6547e6202ba1673c9f7f71696b2b03036f0a1335118f48b909196c12`
- OFF functional SHA-256:
  `cf78e8d9296bf7cc2e252e94bf58e5e7691d61519ce8c41db198b651f6a848da`
- ON functional SHA-256:
  `b1f335ba35dc34f0e7a94a5ff85925cfa7021241b5a49a01f602b39de061a400`

The pair is valid comparison evidence but not the production profile: long
CPU-offloaded load/request latency and the text-only exact target keep MTP
disabled. The W4A16 31B profile remains the on-demand serving choice.

## SGLang 31B bounded probes

SGLang 0.5.15.post1 did not produce a usable 31B serving row:

- The pinned W4A16 checkpoint failed during the runtime's compressed-tensors
  Marlin repack because output width 8,608 is not divisible by tile width 64.
- The exact 31B target loaded with 36 GiB CPU offload in 489.76 seconds and
  allocated 23.79 GiB for the model plus 0.87 GiB for KV cache, but its first
  fixed-condition request exceeded the registered 120-second timeout.
- No OOM occurred in the exact-target attempt. The owned runtime was stopped
  and no benchmark result was fabricated.

The W4A16 log SHA-256 is
`40225e7d1b10c815e7a7c3e9f13facceb4ebf3cb51857eb6e6e4a28cac6e42ab`.
The exact-target status SHA-256 is
`d8ff534a0d3f0433e6a6c78cd52430c23d69f61b675c7978c37d422560b90237`.
The launcher now rejects the known-incompatible W4A16/SGLang combination
before reserving the GPU.

## Live 12B-to-31B-to-12B model switch

The registered stable-vLLM production profiles completed a real
12B-to-31B-to-12B sequence. Each model was stopped before the next load,
model identity and a response were verified at every ready state, and the
final 12B process was stopped only after the return health check passed.
The evidence SHA-256 is
`60de96e58217c042a430083da91872720dfe276b55a07ac787fbf9f86d473d7e`.

## Exact 31B MTP feasibility probe

The exact 31B target and matching assistant passed a constrained live vLLM
probe with 36 GiB CPU offload, a 256-token text-only context, one sequence,
a 256 MiB explicit KV cache, eager execution, and one MTP token:

- target weight load: 278.93 seconds;
- assistant weight load: 7.57 seconds;
- total model load: 345.94 seconds, 22.48 GiB GPU memory reported;
- Korean text: 22,535.890 ms;
- `inspect_gpu({})`: 16,947.540 ms;
- strict structured output: 26,584.837 ms;
- streaming: 5,621.137 ms TTFT and 76,491.321 ms total;
- zero request errors, OOMs, or crashes before the requested shutdown.

Evidence:
`E:\Data\LocalVoiceAgent\runtime\evidence\vllm-31b-mtp-probe-20260724T000502870Z.json`,
SHA-256
`5c56bae23506ea32eaabba5f54406d853af686ef632193f7217777640431c0fe`.
The runtime log SHA-256 is
`d3beed68bef252af6341fada064df3bf865a75effcb1dbfe9a9184dd30be57a4`.

This proves assistant compatibility, not operational suitability. The
measured latency and text-only limitation keep this profile disabled; the
smaller W4A16 31B checkpoint remains the escalation serving path.

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

The exact 31B MTP pair remains a separate feasibility gate. Its registered
probe uses 36 GiB bounded CPU offload by default because the exact target
weights exceed device VRAM, and it refuses to run alongside any detected
ComfyUI process. No load, response, latency, or acceptance result is claimed
until that probe completes.

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

## Interactive voice optimization snapshot (2026-07-24)

This snapshot was taken with Gemma 4 12B, faster-whisper, Silero VAD, and the
Qwen3-TTS worker running together. It is a bounded smoke comparison, not a
p50/p95 benchmark.

| Item | Before | Selected configuration |
|---|---:|---:|
| Total observed GPU memory | about 25.7 GiB | 19,208 MiB used / 12,980 MiB free |
| vLLM observed GPU memory | 20,170 MiB | 13,377 MiB |
| vLLM context / sequences | larger dynamic reservation | 4,096 tokens / 1 sequence |
| vLLM explicit KV cache | dynamic | 1,610,612,736 bytes / 5,381 tokens |
| TTS checkpoint | Qwen3-TTS 1.7B Base | Qwen3-TTS 0.6B Base |
| TTS warm synthesis | 4.033 s for 4.08 s audio, RTF 0.988 | 3.704 s for 4.00 s audio, RTF 0.926 |
| First short speech unit | not separately measured | 1.497 s for 1.52 s audio, RTF 0.985 |
| Gemma streaming smoke | not comparable | 34.713 ms TTFT / 505.588 ms total |

The 0.6B checkpoint saved about 1.7 GiB relative to the 1.7B worker in the
observed live composition. The response pipeline now consumes model deltas
and synthesizes complete speech units concurrently through a bounded queue,
so one TTS request no longer pauses reception of later LLM deltas. The
installed high-level Qwen API still returns a complete waveform for each
speech unit; therefore this change reduces pipeline serialization but does
not claim true codec-frame streaming or sub-100 ms first audio.

Evidence is stored outside Git under
`E:\Data\LocalVoiceAgent\runtime\evidence\vllm-12b-interactive-optimized.json`,
`qwen3-tts-0.6b-warm.json`, and `qwen3-tts-0.6b-first-unit.json`.

## Web QA TTS latency investigation (2026-07-24)

The Web QA portal measures STT final latency, LLM TTFT, TTS first audio, and
predicted playback underrun separately. The tests below used the production
WebSocket pipeline and the consented local Qwen3-TTS voice profile. They are
bounded regression samples rather than p50/p95 results.

| Configuration | TTS first audio after text | Largest predicted playback gap | Result |
|---|---:|---:|---|
| Previous unbounded generation | 155,411.9 ms | Not meaningful; generated about 179 s of audio | Rejected |
| One worker with dynamic token cap | 5,130.8 ms | 3,832.2 ms | Selected |
| Two-worker prefetch, warm sample | 5,683.6 ms | 3,193.6 ms | Rejected |

The previous worker could miss the codec end token and continue until the
generic 2,048-token limit. The production worker now bounds codec generation
to the smaller of 256 tokens or a length-derived limit. It also removes the
guaranteed 160 ms silence that had been appended to every speech unit and
adds only one 80 ms tail after the complete response.

The two-worker experiment reduced one measured inter-sentence gap by about
0.64 seconds but made first audio slower and raised total GPU use from about
18.3 GiB to about 21.0 GiB. It is not selected. The installed official
high-level Qwen3-TTS API returns a complete waveform per speech unit rather
than online codec frames, so the remaining roughly five-second first-audio
delay is a runtime limitation, not reported as solved. The portal exposes
this value directly so a future official online-serving path can be compared
under the same protocol.

External evidence:

- `E:\Data\LocalVoiceAgent\runtime\evidence\web-qa\voice-warm.json`
- `E:\Data\LocalVoiceAgent\runtime\evidence\web-qa\voice-bounded-cold.json`
- `E:\Data\LocalVoiceAgent\runtime\evidence\web-qa\voice-dual-warm.json`
