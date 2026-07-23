# Compatibility report

Research date: 2026-07-23. Only official project documentation, official
model repositories, and upstream release notes are used for selections.

## Key findings

- Gemma 4 12B Unified was released on 2026-06-03. It accepts text, image,
  video-frame, and audio input and supports a 256K context window, thinking,
  system prompts, and function calling.
- Gemma 4 31B is text/image multimodal and has no native audio input.
- Official Google W4A16 compressed-tensors QAT checkpoints are available for
  both sizes and are intended for vLLM/SGLang-class servers.
- Google's runtime routing guide distinguishes the server target
  `{model}-qat-w4a16-ct` from the exact speculative-decoding target
  `{model}-qat-q4_0-unquantized`. The published MTP assistant must be paired
  with the latter target of the same size and QAT precision.
- The 32 GB RTX 5090 cannot safely host 31B BF16 (Google estimates 69.9 GB
  including 20% loading overhead). Q4/W4A16 is required for 31B.
- vLLM stable 0.25.1 explicitly supports Gemma 4 Unified, multimodal inputs,
  reasoning, tool use, structured output, and the Gemma 4 MTP path. Its
  released embedding-share guard has a measured Gemma 4 Unified MTP
  regression; upstream commit `b2b8f679d058…` fixes that exact guard.
- SGLang stable 0.5.15.post1 supports Gemma 4; the dedicated Gemma 4 MTP head
  landed in 0.5.12. It remains a benchmark candidate until function calling,
  multimodal paths, and MTP are tested on this workstation.
- vLLM's official 0.25.1 x86_64 release wheel is pinned by its GitHub release
  SHA-256. The byte-identical PyPI artifact is used as a faster mirror and
  installed with uv's explicit CUDA 13.0 backend selection.
- SGLang's official 0.5.15.post1 CPython 3.12 x86_64 PyPI wheel is pinned by
  its PyPI SHA-256. Its official installation guide states CUDA 13 is the
  default runtime line.
- NVIDIA reports RTX 5090 compute capability 12.0. The installed driver
  advertises CUDA 13.3. Current vLLM and SGLang release lines use CUDA 13 /
  PyTorch 2.11-class stacks.
- faster-whisper 1.2.1 / CTranslate2 currently documents CUDA 12 + cuDNN 9,
  so it must be isolated from the CUDA 13 inference runtimes or initially use
  CPU fallback.
- Chatterbox Multilingual V3 officially lists Korean and uses the MIT
  license. Kokoro's official language list does not include Korean, so it is
  not selected as the primary Korean fallback.
- PostgreSQL 18.4 is current. SQLAlchemy 2.1 remains beta; stable 2.0.51 is
  selected initially.
- Hugging Face Hub 1.24.0 is the current stable download client and supports
  Python 3.10+; it is isolated in a uv-managed Python 3.12 environment.
- Hugging Face Hub 1.24.0 rejects simultaneous `--local-dir` and
  `--cache-dir`. Xet and the HTTP fallback both created new random partial
  names after restart when used with `--local-dir` in this environment. The
  script therefore downloads small repository metadata with `hf`, transfers
  each pinned weight URL to a stable `.partial` file with HTTP range resume,
  and renames it only after exact size and SHA-256 validation.

## Runtime and model matrix

| Component | Candidate | Official source | RTX 5090 | 12B | 31B | MTP | Multimodal | Function calling | Quantization | Selected |
|---|---|---|---|---|---|---|---|---|---|---|
| Gemma default target | `google/gemma-4-12B-it-qat-w4a16-ct` @ `1d2c2d7…` | Google HF | Passed on local V1 runner | Yes | N/A | No matching W4A16 assistant selected | Text/image/video/audio | Native model protocol | W4A16 compressed-tensors | Yes, MTP OFF default |
| Gemma MTP target | `google/gemma-4-12B-it-qat-q4_0-unquantized` @ `b6ed862…` | Google HF | Download/test pending | Yes | N/A | Exact target for 12B assistant | Text/image/video/audio | Output-equivalence test required | Q4_0 QAT extracted half precision | Yes, MTP benchmark |
| Gemma assistant | `google/gemma-4-12B-it-qat-q4_0-unquantized-assistant` @ `1893406…` | Google HF | Loads into MTP path; exact-pair run pending | Yes | N/A | Dedicated assistant | Follows target path | Output-equivalence test required | Q4_0 QAT assistant | Yes, exact-pair gated |
| Gemma default target | `google/gemma-4-31B-it-qat-w4a16-ct` @ `52f3f65…` | Google HF | Download/test pending | N/A | Yes | No matching W4A16 assistant selected | Text/image, no audio | Native model protocol | W4A16 compressed-tensors | Yes, on-demand candidate |
| Gemma MTP target | `google/gemma-4-31B-it-qat-q4_0-unquantized` @ `1e4d8be…` | Google HF | CPU-offload feasibility gate | N/A | Yes | Exact target for 31B assistant | Text/image, no audio | Output-equivalence test required | Q4_0 QAT extracted half precision | Conditional |
| Gemma assistant | `google/gemma-4-31B-it-qat-q4_0-unquantized-assistant` @ `96d4c8c…` | Google HF | Download/test pending | N/A | Yes | Dedicated assistant | Follows target path | Output-equivalence test required | Q4_0 QAT assistant | Yes, exact-pair gated |
| vLLM | 0.25.1 stable | vLLM docs/releases | CUDA passed locally | Passed MTP OFF | Download pending | Dispatch passes; embedding share regression blocks run | Image passed; audio/video pending | Gemma4 parser + structured outputs passed | compressed-tensors passed | Stable baseline |
| vLLM MTP fix | commit `b2b8f679d058…`, cu130 wheel | vLLM commit/PR/nightly index | Test pending | Exact-pair test pending | Conditional | Fixes measured target-embedding share regression | Regression test required | Regression test required | Same stack, exact wheel test pending | MTP candidate |
| SGLang | 0.5.15.post1 stable | SGLang releases/docs | CUDA 13 / Blackwell features; local test required | Official | Official | Added in 0.5.12 | Official VLM path | Local parser validation required | Multiple; exact QAT path test required | Comparison |
| Transformers | >=5.10.1, lock after runtime resolution | Google Gemma function-calling guide | Wheels/test required | Official | Official | Official MTP guide | Official | `apply_chat_template(tools=…)` | Model dependent | Validation oracle |
| PyTorch | Runtime-pinned 2.11-class CUDA wheel | vLLM/SGLang release notes | SM 12.0 build must be verified | Yes | Yes | N/A | Yes | N/A | FP8/NVFP4 ecosystem | Per-runtime lock |
| Windows fallback | llama.cpp + official Q4_0 GGUF | Google QAT routing table | CUDA support must be tested | Candidate | Candidate | Not assumed | Reduced | App-level schema validation | Official GGUF | Fallback candidate |

## Audio and application matrix

| Component | Candidate | License | Korean | Streaming | GPU/CPU | Selected rationale |
|---|---|---|---|---|---|---|
| VAD | Silero VAD 6.2.1 ONNX | MIT | Language-agnostic, 6000+ language training claim | Yes | Prefer CPU | Lightweight and independent of CUDA stack |
| STT | faster-whisper 1.2.1 | MIT | Whisper multilingual | Chunk/partial orchestration required | CUDA 12 + cuDNN 9 or CPU | Benchmark candidate; isolate from CUDA 13 |
| STT alternative | Gemma 4 12B audio understanding / newer runtime ASR | Apache-2.0/model-specific | Yes, measure | Runtime-dependent | GPU | Not the baseline until latency and tool contention are measured |
| TTS | Chatterbox Multilingual V3 | MIT | Officially listed | Sentence/chunk orchestration | GPU/CPU support to measure | Primary quality candidate |
| TTS fallback | Kokoro 82M | Model/code license requires final inventory | Official list lacks Korean | Fast | CPU/GPU | Rejected as Korean default |
| Android | Kotlin + Compose, target API 37 | Android licenses | N/A | WebSocket/audio APIs | Device | Android 17 is current; local-network permission must be handled |
| Database | PostgreSQL 18.4 | PostgreSQL License | N/A | N/A | CPU | Current supported release |
| ORM | SQLAlchemy 2.0.51 async | MIT | N/A | Async | CPU | Stable; 2.1 is beta |
| Migration | Alembic 1.18.5 | MIT | N/A | N/A | CPU | Current stable |

## Known issues and gates

1. Google requires the assistant and target QAT precision to match. The exact
   12B and 31B `qat-q4_0-unquantized` targets are therefore pinned for MTP;
   W4A16 remains the non-MTP serving format.
   vLLM 0.25.1 requires
   `{"method":"mtp","model":"<assistant>","num_speculative_tokens":1}` in
   `--speculative-config`; a log that resolves the method as `draft_model` is
   an explicit failure.
2. A measured vLLM 0.25.1 probe correctly selected `Gemma4MTPModel` and
   `method='mtp'`, then failed during compile: it kept the assistant's
   1,024-wide embedding separate, concatenated it with the 3,840-wide target
   state (4,864), and passed that to a projection expecting 7,680. Upstream
   PR 47953 restricts the embedding-width guard to EAGLE so MTP shares the
   target embedding as designed. The fix commit
   `b2b8f679d0589f0c956f3e734cc70dab07b27b8a` landed on 2026-07-21, after
   v0.25.1 was published on 2026-07-14. It must be tested in a separate,
   rollback-safe environment; the stable environment remains untouched.
3. The 31B W4A16 repository is about 21.7 GiB on disk and Google estimates
   about 17.5 GB static inference memory for Q4_0, excluding KV cache and
   software. The exact 31B MTP target is about 58.3 GiB on disk and cannot
   reside wholly in 32 GB VRAM; it is conditional on a measured CPU-offload
   feasibility test. Context length must start conservatively.
4. MTP is disabled by default for tool execution until JSON-schema validity,
   tool selection, and argument accuracy are statistically no worse than MTP
   off.
5. Stable releases are preferred. A nightly is allowed only if a reproduced
   defect blocks a required capability and the exact build/commit and stable
   rollback are recorded.
6. No Windows-native vLLM deployment is selected. WSL2 is the primary path.
7. Android 17 requires explicit local-network permission behavior for LAN
   communication and foreground-service microphone rules.
8. On this WSL 2 host, vLLM 0.25.1's default V2 Model Runner failed before
   weight loading with `RuntimeError: UVA is not available`. The documented
   `VLLM_USE_V2_MODEL_RUNNER=0` switch selected the V1 runner, which loaded the
   exact 12B checkpoint and passed health, text, function calling, structured
   output, streaming, and image requests. This is a measured host-specific
   compatibility setting, not a claim that every WSL host lacks UVA.
9. V1 startup reported failed best-effort multimodal warmups, but an actual
   in-memory PNG request returned the correct dominant color. Audio and video
   requests remain separate gates. The default model sampling configuration
   is disabled in repeatable smoke/benchmark launches with
   `--generation-config vllm`; requests specify sampling explicitly.

## Official references

- [Gemma 4 overview](https://ai.google.dev/gemma/docs/core)
- [Gemma 4 releases](https://ai.google.dev/gemma/docs/releases)
- [Gemma 4 MTP](https://ai.google.dev/gemma/docs/mtp/overview)
- [Gemma 4 function calling](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4)
- [Google Gemma 4 collection](https://huggingface.co/collections/google/gemma-4)
- [Google Gemma 4 QAT collection](https://huggingface.co/collections/google/gemma-4-qat-q4-0)
- [Hugging Face Hub downloads](https://huggingface.co/docs/huggingface_hub/guides/download)
- [Hugging Face Hub environment variables](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables)
- [vLLM supported models](https://docs.vllm.ai/en/stable/models/supported_models/)
- [vLLM MTP configuration](https://docs.vllm.ai/en/stable/features/speculative_decoding/mtp/)
- [vLLM Gemma 4 recipe](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html)
- [vLLM releases](https://github.com/vllm-project/vllm/releases)
- [vLLM MTP embedding-share fix](https://github.com/vllm-project/vllm/pull/47953)
- [SGLang releases](https://github.com/sgl-project/sglang/releases)
- [SGLang installation](https://docs.sglang.ai/get-started/install.html)
- [NVIDIA CUDA GPU compute capability](https://developer.nvidia.com/cuda/gpus)
- [NVIDIA CUDA on WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [Silero VAD](https://github.com/snakers4/silero-vad)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Chatterbox](https://github.com/resemble-ai/chatterbox)
- [Android 17](https://developer.android.com/about/versions/17)
- [Android foreground-service types](https://developer.android.com/develop/background-work/services/fgs/service-types)
- [PostgreSQL 18 documentation](https://www.postgresql.org/docs/current/)
- [SQLAlchemy releases](https://www.sqlalchemy.org/blog/)
