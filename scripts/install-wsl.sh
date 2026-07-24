#!/usr/bin/env bash
set -euo pipefail

mode="${1:---plan-only}"
runtime_root="${HOME}/.local/share/local-voice-agent/runtimes"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${mode}" == "--plan-only" ]]; then
  cat <<EOF
WSL runtime installation plan
- runtime root: ${runtime_root}
- Python: uv-managed 3.12 per environment
- vLLM: 0.25.1 isolated environment
- vLLM MTP fix: exact commit b2b8f679d058 isolated environment
- SGLang: 0.5.15.post1 isolated environment
- STT: faster-whisper 1.2.1 isolated CUDA 12/CPU environment
- VAD: Silero VAD 6.2.1 ONNX CPU environment
- TTS primary: Qwen3-TTS 12Hz 1.7B Base isolated CUDA 13 environment
- TTS fallback: Chatterbox Multilingual V3 isolated environment

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
  local python_version="${2:-3.12}"
  if [[ ! -x "${environment}/.venv/bin/python" ]]; then
    mkdir -p "${environment}"
    "${uv_bin}" venv --python "${python_version}" "${environment}/.venv"
  fi
}

download_verified() {
  local url="$1"
  local destination="$2"
  local expected_sha="$3"
  local expected_bytes="$4"
  local partial="${destination}.partial"
  local download_python="${runtime_root}/model-download/.venv/bin/python"

  if [[ -f "${destination}" ]]; then
    local existing_bytes
    local existing_sha
    existing_bytes="$(stat -c '%s' "${destination}")"
    existing_sha="$(sha256sum "${destination}" | awk '{print $1}')"
    [[ "${existing_bytes}" == "${expected_bytes}" && "${existing_sha}" == "${expected_sha}" ]] || {
      echo "Refusing to overwrite invalid existing download: ${destination}" >&2
      return 4
    }
    return 0
  fi

  [[ -x "${download_python}" ]] || {
    echo "Run --bootstrap-download-tool before runtime installation." >&2
    return 5
  }
  "${download_python}" "${script_dir}/download-file.py" \
    "${url}" \
    "${partial}" \
    "${expected_bytes}" \
    "${expected_sha}" \
    --workers 16
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
      "https://files.pythonhosted.org/packages/35/9d/c379618ce0abfc2679607d403c0f586b07e9c9c33d08c5bdd6196cb524e0/vllm-0.25.1-cp38-abi3-manylinux_2_28_x86_64.whl" \
      "${wheel}" \
      "16fc7a28df1576eb6f7ca0455026551b8f9adb674c19c66059359ef3e964bd1e" \
      "250100306"
    create_environment "${environment}"
    "${uv_bin}" pip install \
      --python "${environment}/.venv/bin/python" \
      --torch-backend=cu130 \
      "${wheel}"
    "${environment}/.venv/bin/python" -c \
      'import torch, vllm; print(f"vllm={vllm.__version__} torch={torch.__version__} cuda={torch.version.cuda} gpu={torch.cuda.get_device_name(0)}")'
    ;;

  --install-vllm-mtp-fix)
    environment="${runtime_root}/vllm-b2b8f679d058-cu130"
    wheel="${cache_root}/vllm-0.23.1rc1.dev1352+gb2b8f679d-cp38-abi3-manylinux_2_28_x86_64.whl"
    download_verified \
      "https://wheels.vllm.ai/b2b8f679d0589f0c956f3e734cc70dab07b27b8a/vllm-0.23.1rc1.dev1352%2Bgb2b8f679d-cp38-abi3-manylinux_2_28_x86_64.whl" \
      "${wheel}" \
      "d19e66ce501be98d2790a64c01d07d10c376e7785b0b4ca623db23ca4ebf0d61" \
      "308229710"
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
    kernel_wheel="${cache_root}/sglang_kernel-0.4.4+cu130-cp310-abi3-manylinux2014_x86_64.whl"
    download_verified \
      "https://files.pythonhosted.org/packages/c1/24/701bf55add96c074047d76f56fe1778f2d2a2280de1455b0ee84dde52e29/sglang-0.5.15.post1-cp312-cp312-manylinux_2_34_x86_64.whl" \
      "${wheel}" \
      "d1cf208d6ed6bd1d66e6c284635cb671519855dcdfe119e3c4011b6797c90679" \
      "12848778"
    download_verified \
      "https://github.com/sgl-project/whl/releases/download/v0.4.4/sglang_kernel-0.4.4%2Bcu130-cp310-abi3-manylinux2014_x86_64.whl" \
      "${kernel_wheel}" \
      "eb19842cd9809cce7e71d291aa1808f3a7e8c7ad46070a505d970e1ca8105240" \
      "615071971"
    create_environment "${environment}"
    "${uv_bin}" pip install \
      --python "${environment}/.venv/bin/python" \
      --prerelease=allow \
      --torch-backend=cu130 \
      "${wheel}"
    "${uv_bin}" pip install \
      --python "${environment}/.venv/bin/python" \
      --reinstall \
      --no-deps \
      "${kernel_wheel}"
    "${uv_bin}" pip check --python "${environment}/.venv/bin/python"
    "${environment}/.venv/bin/python" -c \
      'import torch, sglang; print(f"sglang={sglang.__version__} torch={torch.__version__} cuda={torch.version.cuda} gpu={torch.cuda.get_device_name(0)}")'
    ;;

  --install-stt)
    environment="${runtime_root}/stt-faster-whisper-1.2.1"
    lock_file="${script_dir}/requirements/stt.lock"
    [[ -f "${lock_file}" ]] || {
      echo "Missing STT lock file: ${lock_file}" >&2
      exit 6
    }
    create_environment "${environment}"
    "${uv_bin}" pip sync \
      --python "${environment}/.venv/bin/python" \
      --require-hashes \
      "${lock_file}"
    nvidia_library_path="$("${environment}/.venv/bin/python" -c \
      'import nvidia.cublas.lib, nvidia.cudnn.lib; print(next(iter(nvidia.cublas.lib.__path__)) + ":" + next(iter(nvidia.cudnn.lib.__path__)))')"
    LD_LIBRARY_PATH="${nvidia_library_path}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
      "${environment}/.venv/bin/python" -c \
      'import ctranslate2, faster_whisper; print(f"faster_whisper={faster_whisper.__version__} ctranslate2={ctranslate2.__version__} cuda_devices={ctranslate2.get_cuda_device_count()}")'
    ;;

  --install-vad)
    environment="${runtime_root}/vad-silero-6.2.1"
    wheel="${cache_root}/silero_vad-6.2.1-py3-none-any.whl"
    download_verified \
      "https://files.pythonhosted.org/packages/0b/2b/48566f29a8b53d856ceb1994f209122749b3fda0a733a07e82047257de7a/silero_vad-6.2.1-py3-none-any.whl" \
      "${wheel}" \
      "09de93c4d874bb19c53e62a47dd38be5f163cedad2b5599583231f2a84ef79cb" \
      "9146242"
    create_environment "${environment}"
    "${uv_bin}" pip install \
      --python "${environment}/.venv/bin/python" \
      --torch-backend=cpu \
      "${wheel}[onnx-cpu]" \
      "onnxruntime==1.27.0"
    "${uv_bin}" pip check --python "${environment}/.venv/bin/python"
    "${environment}/.venv/bin/python" -c \
      'import onnxruntime, silero_vad, torch; print(f"silero_vad={silero_vad.__version__} onnxruntime={onnxruntime.__version__} torch={torch.__version__} providers={onnxruntime.get_available_providers()}")'
    ;;

  --install-tts)
    environment="${runtime_root}/tts-chatterbox-v3-py3146"
    lock_file="${script_dir}/requirements/tts.lock"
    source_archive="${cache_root}/chatterbox-5de7a54aa4e5e2baadb0182dde554908b48b85c2.tar.gz"
    [[ -f "${lock_file}" ]] || {
      echo "Missing TTS lock file: ${lock_file}" >&2
      exit 7
    }
    download_verified \
      "https://codeload.github.com/resemble-ai/chatterbox/tar.gz/5de7a54aa4e5e2baadb0182dde554908b48b85c2" \
      "${source_archive}" \
      "003f8c85dcfeb2d91b3a6f97f43b74703d15131e987dfabb7f3d9aee7c0da2cf" \
      "1432683"
    if [[ ! -x "${environment}/.venv/bin/python" ]]; then
      mkdir -p "${environment}"
      "${uv_bin}" venv \
        --managed-python \
        --python "3.14.6" \
        "${environment}/.venv"
    fi
    "${uv_bin}" pip sync \
      --python "${environment}/.venv/bin/python" \
      --require-hashes \
      --torch-backend=cu130 \
      "${lock_file}"
    "${uv_bin}" pip install \
      --python "${environment}/.venv/bin/python" \
      --no-deps \
      "${source_archive}"
    "${environment}/.venv/bin/python" -c \
      'import chatterbox, torch, torchaudio; print(f"torch={torch.__version__} cuda={torch.version.cuda} torchaudio={torchaudio.__version__} gpu={torch.cuda.get_device_name(0)}")'
    ;;

  --install-qwen3-tts)
    environment="${runtime_root}/tts-qwen3-1.7b"
    lock_file="${script_dir}/requirements/qwen3-tts.lock"
    [[ -f "${lock_file}" ]] || {
      echo "Missing Qwen3-TTS lock file: ${lock_file}" >&2
      exit 8
    }
    create_environment "${environment}"
    "${uv_bin}" pip sync \
      --python "${environment}/.venv/bin/python" \
      --require-hashes \
      --torch-backend=cu130 \
      "${lock_file}"
    "${uv_bin}" pip check --python "${environment}/.venv/bin/python"
    "${environment}/.venv/bin/python" -c \
      'from importlib.metadata import version; import torch, torchaudio; print(f"qwen-tts={version(\"qwen-tts\")} torch={torch.__version__} cuda={torch.version.cuda} torchaudio={torchaudio.__version__} gpu={torch.cuda.get_device_name(0)}")'
    ;;

  *)
    echo "Refusing unrecognized mode: ${mode}" >&2
    exit 2
    ;;
esac
