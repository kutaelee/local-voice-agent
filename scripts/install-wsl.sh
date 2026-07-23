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

uv_bin="$(command -v uv || true)"
if [[ -z "${uv_bin}" && -x "${HOME}/.local/bin/uv" ]]; then
  uv_bin="${HOME}/.local/bin/uv"
fi
[[ -n "${uv_bin}" ]] || {
  echo "uv is required and was not found." >&2
  exit 3
}

download_env="${runtime_root}/model-download"
mkdir -p "${download_env}"
"${uv_bin}" venv --python 3.12 "${download_env}/.venv"
"${uv_bin}" pip install --python "${download_env}/.venv/bin/python" \
  "huggingface_hub==1.24.0"
"${download_env}/.venv/bin/hf" version
