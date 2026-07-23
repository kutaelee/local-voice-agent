#!/usr/bin/env bash
set -euo pipefail

runtime="/home/kutae/.local/share/local-voice-agent/runtimes/stt-faster-whisper-1.2.1/.venv"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cublas="${runtime}/lib/python3.12/site-packages/nvidia/cublas/lib"
cudnn="${runtime}/lib/python3.12/site-packages/nvidia/cudnn/lib"

[[ -x "${runtime}/bin/python" ]] || {
  echo "STT runtime is not installed." >&2
  exit 3
}
[[ -d "${cublas}" && -d "${cudnn}" ]] || {
  echo "Pinned NVIDIA CUDA libraries are not installed." >&2
  exit 4
}

export LD_LIBRARY_PATH="${cublas}:${cudnn}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
exec "${runtime}/bin/python" "${script_dir}/smoke-stt.py" "$@"
