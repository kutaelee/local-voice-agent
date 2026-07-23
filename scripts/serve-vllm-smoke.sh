#!/usr/bin/env bash
set -euo pipefail

model_size="${1:-12b}"
mtp_mode="${2:-off}"
runtime_root="${HOME}/.local/share/local-voice-agent/runtimes/vllm-0.25.1"
vllm_bin="${runtime_root}/.venv/bin/vllm"
model_root="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/gemma4"
host="${VLLM_SMOKE_HOST:-127.0.0.1}"
port="${VLLM_SMOKE_PORT:-8766}"
max_model_len="${VLLM_SMOKE_MAX_MODEL_LEN:-8192}"
gpu_memory_utilization="${VLLM_SMOKE_GPU_MEMORY_UTILIZATION:-0.55}"
speculative_tokens="${VLLM_SMOKE_SPECULATIVE_TOKENS:-1}"
# WSL did not expose CUDA UVA to vLLM's V2 runner on this workstation.
# vLLM 0.25.1 officially supports forcing the V1 runner with this variable.
export VLLM_USE_V2_MODEL_RUNNER="${VLLM_USE_V2_MODEL_RUNNER:-0}"

case "${model_size}" in
  12b)
    target="${model_root}/12b/target/1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee"
    assistant="${model_root}/12b/mtp-assistant/18934064dd4c5c6cc3621f6381e7d377fc8cb7bd"
    served_name="gemma4-12b"
    ;;
  31b)
    target="${model_root}/31b/target/52f3f65bc7a02d555763bc923bd1d9094898219d"
    assistant="${model_root}/31b/mtp-assistant/96d4c8ca3cb38c107a8478587878124895d1e844"
    served_name="gemma4-31b"
    ;;
  *)
    echo "model size must be 12b or 31b" >&2
    exit 2
    ;;
esac

[[ -x "${vllm_bin}" ]] || {
  echo "missing vLLM runtime: ${vllm_bin}" >&2
  exit 3
}
[[ -f "${target}/model.safetensors" ]] || {
  echo "missing validated target weight: ${target}" >&2
  exit 4
}
[[ "${speculative_tokens}" =~ ^[1-3]$ ]] || {
  echo "VLLM_SMOKE_SPECULATIVE_TOKENS must be 1, 2, or 3" >&2
  exit 5
}

args=(
  serve "${target}"
  --host "${host}"
  --port "${port}"
  --served-model-name "${served_name}"
  --max-model-len "${max_model_len}"
  --gpu-memory-utilization "${gpu_memory_utilization}"
  --chat-template "${target}/chat_template.jinja"
  --chat-template-content-format auto
  --generation-config vllm
  --enable-auto-tool-choice
  --tool-call-parser gemma4
  --reasoning-parser gemma4
)

case "${mtp_mode}" in
  off)
    ;;
  on)
    [[ -f "${assistant}/model.safetensors" ]] || {
      echo "missing validated MTP assistant weight: ${assistant}" >&2
      exit 6
    }
    args+=(
      --speculative-config
      "{\"method\":\"mtp\",\"model\":\"${assistant}\",\"num_speculative_tokens\":${speculative_tokens}}"
    )
    ;;
  *)
    echo "MTP mode must be off or on" >&2
    exit 2
    ;;
esac

echo \
  "Starting ${served_name} MTP=${mtp_mode} runner_v2=${VLLM_USE_V2_MODEL_RUNNER} on ${host}:${port}" \
  >&2
exec "${vllm_bin}" "${args[@]}"
