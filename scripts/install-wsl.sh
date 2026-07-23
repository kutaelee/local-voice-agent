#!/usr/bin/env bash
set -euo pipefail

mode="${1:---plan-only}"
runtime_root="${HOME}/.local/share/local-voice-agent/runtimes"

if [[ "${mode}" == "--plan-only" ]]; then
  cat <<EOF
WSL runtime installation plan
- runtime root: ${runtime_root}
- Python: uv-managed 3.12 per environment
- vLLM: 0.25.1 isolated environment
- SGLang: 0.5.15.post1 isolated environment
- STT: faster-whisper 1.2.1 isolated CUDA 12/CPU environment
- VAD: Silero VAD 6.2.1 ONNX CPU environment
- TTS: Chatterbox Multilingual V3 isolated environment

No package is installed in plan-only mode.
EOF
  exit 0
fi

if [[ "${mode}" != "--bootstrap-download-tool" ]]; then
  echo "Refusing unrecognized mode: ${mode}" >&2
  exit 2
fi

command -v uv >/dev/null 2>&1 || {
  echo "uv is required and was not found." >&2
  exit 3
}

download_env="${runtime_root}/model-download"
mkdir -p "${download_env}"
uv venv --python 3.12 "${download_env}/.venv"
uv pip install --python "${download_env}/.venv/bin/python" \
  "huggingface_hub[cli]==0.36.0"
"${download_env}/.venv/bin/hf" version
