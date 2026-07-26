#!/usr/bin/env bash
set -euo pipefail

# Foreground process for gpuq. Keep the reservation active for the complete
# lifetime of the vLLM-Omni TTS server.

runtime="/home/kutae/.local/share/local-voice-agent/runtimes/vllm-omni-0.24.0/.venv"
tts_size="${LVA_QWEN3_TTS_SIZE:-1.7b}"
case "${tts_size}" in
  0.6b)
    model="/mnt/e/AI/Models/HuggingFace/hub/models--Qwen--Qwen3-TTS-12Hz-0.6B-Base/snapshots/5d83992436eae1d760afd27aff78a71d676296fc"
    ;;
  1.7b)
    model="/mnt/e/AI/Models/HuggingFace/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base/snapshots/fd4b254389122332181a7c3db7f27e918eec64e3"
    ;;
  *)
    echo "LVA_QWEN3_TTS_SIZE must be 0.6b or 1.7b." >&2
    exit 2
    ;;
esac
deploy_config="/mnt/c/Dev/Repos/local-voice-agent/configs/vllm-omni-qwen3-tts.yaml"
voice_root="/mnt/e/Data/LocalVoiceAgent/voice-profiles"
speaker_cache="/mnt/e/Data/LocalVoiceAgent/runtime/cache/vllm-omni-speakers"
site_packages="${runtime}/lib/python3.12/site-packages"
compat_patch="/mnt/c/Dev/Repos/local-voice-agent/scripts/patches/vllm-omni-0.24.0-disable-qwen-artifact-only.patch"
serving_speech="${site_packages}/vllm_omni/entrypoints/openai/serving_speech.py"
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
[[ -f "${compat_patch}" && -f "${serving_speech}" ]] || {
  echo "Pinned vLLM-Omni compatibility patch is unavailable." >&2
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

if ! grep -q "LVA_QWEN3_TTS_DISABLE_ARTIFACT_ONLY" "${serving_speech}"; then
  patch --batch --forward -p1 -d "${site_packages}" <"${compat_patch}"
fi
grep -q "LVA_QWEN3_TTS_DISABLE_ARTIFACT_ONLY" "${serving_speech}" || {
  echo "vLLM-Omni compatibility patch validation failed." >&2
  exit 8
}

export \
  HF_HOME="/mnt/e/AI/Models/HuggingFace" \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  PYTHONNOUSERSITE=1 \
  SPEAKER_SAMPLES_DIR="${speaker_cache}" \
  LVA_QWEN3_TTS_DISABLE_ARTIFACT_ONLY=1

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
