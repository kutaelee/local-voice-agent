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
- The 32 GB RTX 5090 cannot safely host 31B BF16 (Google estimates 69.9 GB
  including 20% loading overhead). Q4/W4A16 is required for 31B.
- vLLM stable 0.25.1 explicitly supports Gemma 4 Unified, multimodal inputs,
  reasoning, tool use, structured output, and the Gemma 4 MTP path.
- SGLang stable 0.5.15.post1 supports Gemma 4; the dedicated Gemma 4 MTP head
  landed in 0.5.12. It remains a benchmark candidate until function calling,
  multimodal paths, and MTP are tested on this workstation.
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
  `--cache-dir`. The download script uses the official `HF_HOME` mechanism and
  `HF_XET_HIGH_PERFORMANCE=1`, while retaining per-target resume metadata.

## Runtime and model matrix

| Component | Candidate | Official source | RTX 5090 | 12B | 31B | MTP | Multimodal | Function calling | Quantization | Selected |
|---|---|---|---|---|---|---|---|---|---|---|
| Gemma target | `google/gemma-4-12B-it-qat-w4a16-ct` @ `1d2c2d7…` | Google HF | Expected; test required | Yes | N/A | Matching assistant must be validated | Text/image/video/audio | Native model protocol | W4A16 compressed-tensors | Yes, default candidate |
| Gemma assistant | `google/gemma-4-12B-it-qat-q4_0-unquantized-assistant` @ `1893406…` | Google HF | Expected; test required | Matched by size/QAT family | N/A | Dedicated assistant | Follows target path | Output-equivalence test required | QAT assistant | Yes, compatibility-gated |
| Gemma target | `google/gemma-4-31B-it-qat-w4a16-ct` @ `52f3f65…` | Google HF | Expected; tight VRAM test | N/A | Yes | Matching assistant must be validated | Text/image, no audio | Native model protocol | W4A16 compressed-tensors | Yes, on-demand candidate |
| Gemma assistant | `google/gemma-4-31B-it-qat-q4_0-unquantized-assistant` @ `96d4c8c…` | Google HF | Expected; test required | N/A | Matched by size/QAT family | Dedicated assistant | Follows target path | Output-equivalence test required | QAT assistant | Yes, compatibility-gated |
| vLLM | 0.25.1 stable | vLLM docs/releases | CUDA supports NVIDIA; local test required | Official | Official | Official Gemma 4 path | Official | Gemma4 parser + structured outputs | compressed-tensors, FP8/NVFP4 paths | Primary |
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

1. Google model cards state QAT assistants must match the target QAT precision.
   The published W4A16 collection exposes target checkpoints while published
   assistant checkpoints are labeled Q4_0-unquantized QAT. Do not claim MTP
   compatibility until vLLM and SGLang load the exact pair and the log shows
   the Gemma 4 MTP path, not generic draft decoding.
2. The 31B W4A16 repository is about 21.7 GiB on disk and Google estimates
   about 17.5 GB static inference memory for Q4_0, excluding KV cache and
   software. Context length must start at 8K with conservative GPU memory
   utilization.
3. MTP is disabled by default for tool execution until JSON-schema validity,
   tool selection, and argument accuracy are statistically no worse than MTP
   off.
4. Stable releases are preferred. A nightly is allowed only if a reproduced
   defect blocks a required capability and the exact build/commit and stable
   rollback are recorded.
5. No Windows-native vLLM deployment is selected. WSL2 is the primary path.
6. Android 17 requires explicit local-network permission behavior for LAN
   communication and foreground-service microphone rules.

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
- [vLLM Gemma 4 recipe](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html)
- [vLLM releases](https://github.com/vllm-project/vllm/releases)
- [SGLang releases](https://github.com/sgl-project/sglang/releases)
- [NVIDIA CUDA GPU compute capability](https://developer.nvidia.com/cuda/gpus)
- [NVIDIA CUDA on WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [Silero VAD](https://github.com/snakers4/silero-vad)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Chatterbox](https://github.com/resemble-ai/chatterbox)
- [Android 17](https://developer.android.com/about/versions/17)
- [Android foreground-service types](https://developer.android.com/develop/background-work/services/fgs/service-types)
- [PostgreSQL 18 documentation](https://www.postgresql.org/docs/current/)
- [SQLAlchemy releases](https://www.sqlalchemy.org/blog/)
