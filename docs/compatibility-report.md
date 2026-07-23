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
  landed in 0.5.12. Its isolated CUDA 13 environment, official
  `sglang-kernel` 0.4.4 CUDA 13 wheel, package check, RTX 5090 device query,
  and CUDA matrix multiplication pass locally. The exact 12B pair was promoted
  to `FROZEN_KV_MTP` and passed text, tool, schema, streaming, image, and
  thinking smoke with 4 GiB CPU offload. The fixed-condition MTP latency run
  remains pending because the shared GPU was yielded to a new ComfyUI render.
- vLLM's official 0.25.1 x86_64 release wheel is pinned by its GitHub release
  SHA-256. The byte-identical PyPI artifact is used as a faster mirror and
  installed with uv's explicit CUDA 13.0 backend selection.
- SGLang's official 0.5.15.post1 CPython 3.12 x86_64 PyPI wheel and official
  `sglang-kernel` 0.4.4 CUDA 13 wheel are pinned by size and SHA-256. Its
  official installation guide requires the CUDA 13 PyTorch stack before the
  separate CUDA 13 kernel wheel.
- NVIDIA reports RTX 5090 compute capability 12.0. The installed driver
  advertises CUDA 13.3. Current vLLM and SGLang release lines use CUDA 13 /
  PyTorch 2.11-class stacks.
- faster-whisper 1.2.1 / CTranslate2 currently documents CUDA 12 + cuDNN 9,
  so it must be isolated from the CUDA 13 inference runtimes or initially use
  CPU fallback.
- faster-whisper 1.2.1 maps `large-v3-turbo` to the linked
  `mobiuslabsgmbh/faster-whisper-large-v3-turbo` conversion. That exact
  revision and the official Systran `small` revision are pinned as GPU and
  CPU candidates; neither is selected before Korean audio measurement.
- Chatterbox Multilingual V3 officially lists Korean and uses the MIT
  license. An isolated Python 3.14 environment avoids its Python-below-3.14
  torch pin and uses the tested CUDA 13 PyTorch stack without mixing it into
  inference runtimes. The exact V3 checkpoint passed local Korean synthesis
  and the worker path. Kokoro's official language list does not include
  Korean, so it is not selected as the primary Korean fallback.
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
| Gemma MTP target | `google/gemma-4-12B-it-qat-q4_0-unquantized` @ `b6ed862…` | Google HF | Text-only API passed on exact-fix runtime | Yes | N/A | Exact target for 12B assistant; measured 89.6% preliminary acceptance | Text passed; multimodal config blocked | Tool/schema smoke passed; statistical gate required | Q4_0 QAT extracted half precision | Yes, disabled benchmark candidate |
| Gemma assistant | `google/gemma-4-12B-it-qat-q4_0-unquantized-assistant` @ `1893406…` | Google HF | Exact pair loaded and generated | Yes | N/A | Dedicated assistant detected as `Gemma4MTPModel` | Follows target path; multimodal blocked | Tool/schema smoke passed; statistical gate required | Q4_0 QAT assistant | Yes, disabled exact-pair candidate |
| Gemma default target | `google/gemma-4-31B-it-qat-w4a16-ct` @ `52f3f65…` | Google HF | Text API passed with explicit KV cache | N/A | Yes | No matching W4A16 assistant selected | Text passed; image pending; no audio | Tool/schema smoke passed | W4A16 compressed-tensors | Yes, on-demand text candidate |
| Gemma MTP target | `google/gemma-4-31B-it-qat-q4_0-unquantized` @ `1e4d8be…` | Google HF | Both shards SHA-256 passed; CPU-offload feasibility gate remains | N/A | Yes | Exact target for 31B assistant | Text/image, no audio | Output-equivalence test required | Q4_0 QAT extracted half precision | Conditional |
| Gemma assistant | `google/gemma-4-31B-it-qat-q4_0-unquantized-assistant` @ `96d4c8c…` | Google HF | SHA-256 passed; exact target downloaded | N/A | Yes | Dedicated assistant | Follows target path | Output-equivalence test required | Q4_0 QAT assistant | Yes, exact-pair gated |
| vLLM | 0.25.1 stable | vLLM docs/releases | CUDA passed locally | Passed MTP OFF | Text/tool/schema/stream passed | Dispatch passes; embedding share regression blocks stable MTP | 12B image passed; 31B image and audio/video pending | Gemma4 parser + structured outputs passed | compressed-tensors passed | Stable baseline |
| vLLM MTP fix | commit `b2b8f679d058…`, cu130 wheel | vLLM commit/PR/nightly index | RTX 5090 text MTP passed | Exact-pair text API passed | Conditional | Exact pair loaded; 48 drafted / 43 accepted | Q4 target config blocks multimodal init | Tool + structured-output smoke passed | Exact wheel/package check passed | Disabled pending quality and multimodal gates |
| SGLang | 0.5.15.post1 stable + kernel 0.4.4 cu130 | SGLang releases/docs | Local CUDA 13/SM 12.0, W4A16, and exact-pair MTP load passed | Text/image/tool/schema/stream/thinking passed; MTP-OFF 10-sample latency recorded | Official; local load pending | Exact assistant promoted to `FROZEN_KV_MTP`; 4 GiB CPU-offload functional smoke passed | 12B red-image smoke passed with MTP OFF and ON | Gemma4 tool/reasoning parsers passed locally | W4A16 and exact Q4_0 pair passed | Installed comparison candidate; MTP latency/quality gate pending |
| Transformers | >=5.10.1, lock after runtime resolution | Google Gemma function-calling guide | Wheels/test required | Official | Official | Official MTP guide | Official | `apply_chat_template(tools=…)` | Model dependent | Validation oracle |
| PyTorch | Runtime-pinned 2.11-class CUDA wheel | vLLM/SGLang release notes | SM 12.0 build must be verified | Yes | Yes | N/A | Yes | N/A | FP8/NVFP4 ecosystem | Per-runtime lock |
| Windows fallback | llama.cpp b10092 + `ggml-org/gemma-4-12B-it-GGUF` Q4_0 @ `d72ee272…` | Google llama.cpp integration, ggml-org release/model | CPU-only Windows path passed while GPU was occupied; CUDA binary installed, GPU smoke pending | 12B Korean text passed | N/A | Disabled for fallback | Text only guaranteed | Native tool call and strict JSON passed | Q4_0 GGUF, SHA-256 passed | Selected recovery fallback |

## Audio and application matrix

| Component | Candidate | License | Korean | Streaming | GPU/CPU | Selected rationale |
|---|---|---|---|---|---|---|
| VAD | Silero VAD 6.2.1 + ONNX Runtime 1.27.0 | MIT | Language-agnostic, 6000+ language training claim | Authenticated streaming worker passed | CPUExecutionProvider | Selected; 500 ms endpoint avoids splitting the measured Korean sample pause |
| STT | faster-whisper 1.2.1, `large-v3-turbo` + `small` | MIT | Whisper multilingual | Chunk/partial orchestration required | CUDA 12 + cuDNN 9 or CPU | GPU/CPU benchmark pair; isolate from CUDA 13 |
| STT alternative | Gemma 4 12B audio understanding / newer runtime ASR | Apache-2.0/model-specific | Yes, measure | Runtime-dependent | GPU | Not the baseline until latency and tool contention are measured |
| TTS | Chatterbox Multilingual V3, HF `5bb1f6e…`, package 0.1.7 | MIT | Officially listed | Sentence/chunk orchestration | PyTorch pin compatibility gate | Primary quality candidate |
| TTS fallback | Kokoro 82M | Model/code license requires final inventory | Official list lacks Korean | Fast | CPU/GPU | Rejected as Korean default |
| Android | Kotlin + Compose, target API 37 | Android licenses | N/A | WebSocket/audio APIs | Device | Android 17 is current; local-network permission must be handled |
| Browser automation | Playwright Python 1.61.0 + Chrome for Testing 149 | Apache-2.0 / browser notices | N/A | DOM, ARIA, screenshot | CPU | Selected; Windows 11 supported, isolated loopback-only live smoke passed |
| Windows UI | Microsoft UI Automation + pywinauto 0.6.9 | Windows API / BSD-3-Clause | N/A | Accessibility tree, invoke, text, screenshot | CPU | Selected for bounded non-coordinate fallback; action executable allowlist enforced |
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
   software. The exact 31B MTP target is about 58.3 GiB on disk, has passed
   both shard hashes, and cannot
   reside wholly in 32 GB VRAM; it is conditional on a measured CPU-offload
   feasibility test. Context length must start conservatively. On this shared
   host, a utilization-based 31B launch loaded the weights but failed because
   no KV-cache blocks remained. A retry with an explicit 384 MiB KV cache,
   256-token context, and one sequence passed health, Korean text, tool call,
   strict structured output, and streaming. These constrained smoke settings
   are not production defaults and 31B multimodal input remains untested.
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
10. Chatterbox 0.1.7's Python <3.14 dependency pins torch and torchaudio 2.6.
    The isolated Python 3.14.6 TTS environment instead resolves torch and
    torchaudio 2.11 + CUDA 13.0 and has passed import, CUDA, Korean synthesis,
    and persistent-worker smoke tests. Long-form quality remains a benchmark
    gate. Voice cloning stays disabled.
11. SGLang 0.5.15.post1 and kernel 0.4.4 cu130 are installed in a versioned
    WSL environment. Its 194-package check and RTX 5090 CUDA smoke pass.
    Launching Gemma was deliberately deferred when an unrelated Windows
    process left only 2,954 MiB VRAM free; no process was killed and no model
    failure is inferred from this resource gate.

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
