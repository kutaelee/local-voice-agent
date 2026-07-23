# Environment report

Initial capture was read-only on 2026-07-23 (Asia/Seoul). Post-capture SDK
and isolated runtime installations are recorded separately below and in
`manifests/runtimes.yaml`.

## Hardware

| Item | Observed |
|---|---|
| CPU | AMD Ryzen 9 9950X3D, 16 cores / 32 logical processors |
| RAM | 125.61 GiB total, 96.05 GiB available at capture |
| GPU | NVIDIA GeForce RTX 5090 |
| VRAM | 32,607 MiB total, 31,048 MiB free at capture |
| Compute capability | 12.0 |
| NVIDIA driver | 610.62 |
| Driver CUDA support | CUDA 13.3 |
| Active network | Wi-Fi 866.7 Mbps; Ethernet link reported 10 Mbps |
| Android device | No connected device observed; ADB 37.0.0 is now installed |

## Windows

| Item | Observed |
|---|---|
| OS | Windows 11 Pro 10.0.26200, build 26200, 64-bit |
| PowerShell | 5.1.26100.8875 |
| winget | 1.11.510 |
| Git | 2.55.0.windows.3 |
| Git LFS | 3.7.1 |
| GitHub CLI | 2.96.0; authenticated as `kutaelee` |
| uv | 0.11.30 |
| Java | Azul Zulu OpenJDK 17.0.20 |
| Docker Desktop | 4.83.0; Engine/CLI 29.6.2 |
| WSL | 2.7.10.0; WSL2 Ubuntu and docker-desktop running |

Not found on Windows PATH or canonical install locations at initial capture:
usable Python, Node/npm, Android Studio, Android SDK, ADB, FFmpeg, CMake, Ninja, Visual
Studio Build Tools, CUDA Toolkit, Hugging Face CLI, Ollama, llama.cpp, and
PostgreSQL client/server.

## Post-capture Android build environment

The command-line SDK was installed without administrator rights, registry
changes, or persistent PATH changes:

| Item | Installed/verified |
|---|---|
| SDK root | `C:\Dev\SDK\Android` |
| Command-line tools | 22.0; official archive SHA-256 passed |
| Platform | Android 17 / API 37.0, revision 2 |
| Build Tools | 36.0.0; `aapt2` and `apksigner` invoked |
| Platform Tools | 37.0.0; ADB invoked |
| Gradle | 9.6.1, distribution SHA-256 pinned |
| Android Gradle Plugin | 9.3.0 |
| Compose BOM | 2026.06.00 |
| Full Android Studio | Not installed |

The exact sources, checksums, paths, and rollback steps are in
`manifests/android-sdk.yaml`.

## WSL Ubuntu

| Item | Observed |
|---|---|
| Distribution | Ubuntu 26.04 LTS |
| Kernel | 6.18.33.2-microsoft-standard-WSL2 |
| Root filesystem | ext4, 1007 GiB total, 933 GiB available |
| Python | 3.14.4 system interpreter |
| uv | 0.11.31 |
| GCC | 15.2.0 |
| CMake | 4.2.3 |
| Ninja | 1.13.2 |
| GPU passthrough | RTX 5090 visible; 32,607 MiB VRAM |
| CUDA Toolkit (`nvcc`) | Not installed |
| AI Python packages at initial capture | torch, Triton, FlashAttention, FlashInfer, vLLM, SGLang, Transformers, faster-whisper, Silero VAD not installed |

The system Python 3.14 interpreter will not be used for GPU runtimes. Each
runtime will use a uv-managed Python version compatible with its locked
release, initially Python 3.12 unless official wheels require otherwise.

## Existing development and AI assets

- 24 Git repositories were found under `C:\Dev\Repos`.
- `C:\Dev\Current` is empty.
- Canonical ComfyUI app exists at `E:\AI\Apps\ComfyUI`.
- Existing models are under `E:\AI\Models\ComfyUI` and
  `E:\AI\Models\Standalone`; no Gemma 4 checkpoint was found.
- `HF_HOME` points to `E:\Cache\HuggingFace`; it contains no model snapshot.
- The Ubuntu VHDX is `C:\WSL\Ubuntu\ext4.vhdx` and currently occupies
  approximately 24.137 GiB.

## Installation gaps requiring a later gate

- Android command-line SDK/ADB and JDK 17 are installed and verified without
  a system PATH mutation. Full Android Studio remains an explicit-approval
  item and is not required for the command-line build.
- FFmpeg is needed for broader audio tooling, although faster-whisper itself
  can decode through bundled PyAV.
- PostgreSQL 18 is absent. Installation/container provisioning is a Level 2
  action and is not part of Slice 0.
- Versioned vLLM, SGLang, faster-whisper, and Chatterbox environments were
  subsequently installed under the WSL user runtime root. Their exact
  packages, checksums, model paths, and measured smokes are recorded in
  `manifests/runtimes.yaml` and `docs/test-report.md`. Silero VAD 6.2.1 was
  subsequently installed in a CPU-only ONNX environment and its persistent
  worker smoke passed.
