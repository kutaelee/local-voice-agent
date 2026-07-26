#!/usr/bin/env bash
set -euo pipefail

# Foreground process for gpuq. Keep the reservation active for the complete
# lifetime of the vLLM-Omni TTS server.

runtime="/home/kutae/.local/share/local-voice-agent/runtimes/vllm-omni-0.24.0/.venv"
model="/mnt/e/AI/Models/HuggingFace/hub/models--Qwen--Qwen3-TTS-12Hz-0.6B-Base/snapshots/5d83992436eae1d760afd27aff78a71d676296fc"
deploy_config="/mnt/c/Dev/Repos/local-voice-agent/configs/vllm-omni-qwen3-tts.yaml"
voice_root="/mnt/e/Data/LocalVoiceAgent/voice-profiles"
speaker_cache="/mnt/e/Data/LocalVoiceAgent/runtime/cache/vllm-omni-speakers"
port="${LVA_VLLM_OMNI_TTS_PORT:-46329}"
prefetch_weights="${LVA_TTS_PREFETCH_WEIGHTS:-0}"

[[ -x "${runtime}/bin/vllm" ]] || {
  echo "vLLM-Omni runtime is unavailable." >&2
  exit 3
}
[[ -d "${model}" && -f "${model}/config.json" ]] || {
  echo "Canonical Qwen3-TTS snapshot is unavailable." >&2
  exit 4
}
[[ -f "${deploy_config}" ]] || {
  echo "Pinned Qwen3-TTS deploy configuration is unavailable." >&2
  exit 5
}
[[ -d "${voice_root}" ]] || {
  echo "Voice profile root is unavailable." >&2
  exit 6
}
[[ "${prefetch_weights}" =~ ^[01]$ ]] || {
  echo "LVA_TTS_PREFETCH_WEIGHTS must be 0 or 1." >&2
  exit 7
}
mkdir -p "${speaker_cache}"
chmod 700 "${speaker_cache}"

export \
  HF_HOME="/mnt/e/AI/Models/HuggingFace" \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  PYTHONNOUSERSITE=1 \
  SPEAKER_SAMPLES_DIR="${speaker_cache}"

# Optional diagnostic for the canonical model store's WSL 9P mount. It creates
# no second on-disk model copy. This is off by default: the 2026-07-26 measured
# run added 11.52s while stage-0 weight loading stayed effectively unchanged.
if [[ "${prefetch_weights}" == "1" ]]; then
  "${runtime}/bin/python" - "${model}" <<'PY'
from pathlib import Path
import sys
import time

root = Path(sys.argv[1])
paths = sorted(root.rglob("*.safetensors"))
started = time.monotonic()
total = 0
for path in paths:
    with path.open("rb", buffering=8 * 1024 * 1024) as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            total += len(chunk)
elapsed = time.monotonic() - started
print(
    f"Prefetched {len(paths)} safetensors files ({total / (1024**3):.2f} GiB) "
    f"from canonical storage in {elapsed:.2f}s.",
    file=sys.stderr,
)
PY
fi

exec "${runtime}/bin/vllm" serve "${model}" \
  --omni \
  --deploy-config "${deploy_config}" \
  --host 127.0.0.1 \
  --port "${port}" \
  --allowed-local-media-path "${voice_root}" \
  --trust-remote-code
