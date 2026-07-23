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

uv_bin="$(command -v uv || true)"
if [[ -z "${uv_bin}" && -x "${HOME}/.local/bin/uv" ]]; then
  uv_bin="${HOME}/.local/bin/uv"
fi
[[ -n "${uv_bin}" ]] || {
  echo "uv is required and was not found." >&2
  exit 3
}

cache_root="/mnt/e/Cache/LocalVoiceAgent/downloads"
mkdir -p "${cache_root}"

create_environment() {
  local environment="$1"
  if [[ ! -x "${environment}/.venv/bin/python" ]]; then
    mkdir -p "${environment}"
    "${uv_bin}" venv --python 3.12 "${environment}/.venv"
  fi
}

download_verified() {
  local url="$1"
  local destination="$2"
  local expected_sha="$3"
  local partial="${destination}.partial"

  if [[ -f "${destination}" ]]; then
    local existing_sha
    existing_sha="$(sha256sum "${destination}" | awk '{print $1}')"
    [[ "${existing_sha}" == "${expected_sha}" ]] || {
      echo "Refusing to overwrite invalid existing download: ${destination}" >&2
      return 4
    }
    return 0
  fi

  curl --fail --location \
    --retry 5 \
    --retry-all-errors \
    --retry-delay 5 \
    --continue-at - \
    --output "${partial}" \
    "${url}"
  echo "${expected_sha}  ${partial}" | sha256sum --check -
  mv -- "${partial}" "${destination}"
}

case "${mode}" in
  --bootstrap-download-tool)
    environment="${runtime_root}/model-download"
    create_environment "${environment}"
    "${uv_bin}" pip install --python "${environment}/.venv/bin/python" \
      "huggingface_hub==1.24.0"
    "${environment}/.venv/bin/hf" version
    ;;

  --install-vllm)
    environment="${runtime_root}/vllm-0.25.1"
    wheel="${cache_root}/vllm-0.25.1-cp38-abi3-manylinux_2_28_x86_64.whl"
    download_verified \
      "https://github.com/vllm-project/vllm/releases/download/v0.25.1/vllm-0.25.1-cp38-abi3-manylinux_2_28_x86_64.whl" \
      "${wheel}" \
      "16fc7a28df1576eb6f7ca0455026551b8f9adb674c19c66059359ef3e964bd1e"
    create_environment "${environment}"
    "${uv_bin}" pip install \
      --python "${environment}/.venv/bin/python" \
      --torch-backend=cu130 \
      "${wheel}"
    "${environment}/.venv/bin/python" -c \
      'import torch, vllm; print(f"vllm={vllm.__version__} torch={torch.__version__} cuda={torch.version.cuda} gpu={torch.cuda.get_device_name(0)}")'
    ;;

  --install-sglang)
    environment="${runtime_root}/sglang-0.5.15.post1"
    wheel="${cache_root}/sglang-0.5.15.post1-cp312-cp312-manylinux_2_34_x86_64.whl"
    download_verified \
      "https://files.pythonhosted.org/packages/c1/24/701bf55add96c074047d76f56fe1778f2d2a2280de1455b0ee84dde52e29/sglang-0.5.15.post1-cp312-cp312-manylinux_2_34_x86_64.whl" \
      "${wheel}" \
      "d1cf208d6ed6bd1d66e6c284635cb671519855dcdfe119e3c4011b6797c90679"
    create_environment "${environment}"
    "${uv_bin}" pip install \
      --python "${environment}/.venv/bin/python" \
      --prerelease=allow \
      "${wheel}"
    "${environment}/.venv/bin/python" -c \
      'import torch, sglang; print(f"sglang={sglang.__version__} torch={torch.__version__} cuda={torch.version.cuda} gpu={torch.cuda.get_device_name(0)}")'
    ;;

  *)
    echo "Refusing unrecognized mode: ${mode}" >&2
    exit 2
    ;;
esac
