#!/usr/bin/env bash
set -euo pipefail

model_size="${1:-12b}"
mtp_mode="${2:-off}"
stable_runtime_root="${HOME}/.local/share/local-voice-agent/runtimes/vllm-0.25.1"
mtp_runtime_root="${VLLM_MTP_RUNTIME_ROOT:-${HOME}/.local/share/local-voice-agent/runtimes/vllm-b2b8f679d058-cu130}"
model_root="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/gemma4"
host="${VLLM_SMOKE_HOST:-127.0.0.1}"
port="${VLLM_SMOKE_PORT:-8766}"
speculative_tokens="${VLLM_SMOKE_SPECULATIVE_TOKENS:-1}"
enforce_eager="${VLLM_SMOKE_ENFORCE_EAGER:-0}"
language_model_only="${VLLM_SMOKE_LANGUAGE_MODEL_ONLY:-0}"
kv_cache_memory="${VLLM_SMOKE_KV_CACHE_MEMORY_BYTES:-}"
max_num_seqs="${VLLM_SMOKE_MAX_NUM_SEQS:-}"
# WSL did not expose CUDA UVA to vLLM's V2 runner on this workstation.
# vLLM 0.25.1 officially supports forcing the V1 runner with this variable.
export VLLM_USE_V2_MODEL_RUNNER="${VLLM_USE_V2_MODEL_RUNNER:-0}"

case "${model_size}" in
  12b)
    target="${model_root}/12b/target/1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee"
    mtp_target="${model_root}/12b/mtp-target/b6ed86275a6a5735884e208bfed95b445a684ca2"
    assistant="${model_root}/12b/mtp-assistant/18934064dd4c5c6cc3621f6381e7d377fc8cb7bd"
    served_name="gemma4-12b"
    ;;
  31b)
    target="${model_root}/31b/target/52f3f65bc7a02d555763bc923bd1d9094898219d"
    mtp_target="${model_root}/31b/mtp-target/1e4d8beecacb8b7590c1d8bedd7335f687bf311f"
    assistant="${model_root}/31b/mtp-assistant/96d4c8ca3cb38c107a8478587878124895d1e844"
    served_name="gemma4-31b"
    ;;
  *)
    echo "model size must be 12b or 31b" >&2
    exit 2
    ;;
esac

[[ "${speculative_tokens}" =~ ^[1-3]$ ]] || {
  echo "VLLM_SMOKE_SPECULATIVE_TOKENS must be 1, 2, or 3" >&2
  exit 5
}
[[ "${enforce_eager}" =~ ^[01]$ ]] || {
  echo "VLLM_SMOKE_ENFORCE_EAGER must be 0 or 1" >&2
  exit 6
}
[[ "${language_model_only}" =~ ^[01]$ ]] || {
  echo "VLLM_SMOKE_LANGUAGE_MODEL_ONLY must be 0 or 1" >&2
  exit 7
}
if [[ -n "${kv_cache_memory}" && ! "${kv_cache_memory}" =~ ^[1-9][0-9]*$ ]]; then
  echo "VLLM_SMOKE_KV_CACHE_MEMORY_BYTES must be a positive integer" >&2
  exit 8
fi
if [[ -n "${max_num_seqs}" && ! "${max_num_seqs}" =~ ^[1-9][0-9]*$ ]]; then
  echo "VLLM_SMOKE_MAX_NUM_SEQS must be a positive integer" >&2
  exit 9
fi

case "${mtp_mode}" in
  off)
    runtime_root="${stable_runtime_root}"
    max_model_len="${VLLM_SMOKE_MAX_MODEL_LEN:-8192}"
    gpu_memory_utilization="${VLLM_SMOKE_GPU_MEMORY_UTILIZATION:-0.55}"
    speculative_args=()
    ;;
  on)
    runtime_root="${mtp_runtime_root}"
    max_model_len="${VLLM_SMOKE_MAX_MODEL_LEN:-2048}"
    gpu_memory_utilization="${VLLM_SMOKE_GPU_MEMORY_UTILIZATION:-0.90}"
    target="${mtp_target}"
    served_name="${served_name}-mtp"
    [[ -f "${assistant}/model.safetensors" ]] || {
      echo "missing validated MTP assistant weight: ${assistant}" >&2
      exit 6
    }
    speculative_args=(
      --speculative-config
      "{\"method\":\"mtp\",\"model\":\"${assistant}\",\"num_speculative_tokens\":${speculative_tokens}}"
    )
    ;;
  *)
    echo "MTP mode must be off or on" >&2
    exit 2
    ;;
esac

vllm_bin="${runtime_root}/.venv/bin/vllm"
[[ -x "${vllm_bin}" ]] || {
  echo "missing vLLM runtime: ${vllm_bin}" >&2
  exit 3
}

if [[ "${model_size}" == "31b" && "${mtp_mode}" == "on" ]]; then
  target_weight="${target}/model-00001-of-00002.safetensors"
else
  target_weight="${target}/model.safetensors"
fi
[[ -f "${target_weight}" ]] || {
  echo "missing validated target weight: ${target_weight}" >&2
  exit 4
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
  "${speculative_args[@]}"
)
if [[ -n "${LVA_VLLM_API_KEY:-}" ]]; then
  [[ "${#LVA_VLLM_API_KEY}" -ge 32 ]] || {
    echo "LVA_VLLM_API_KEY must contain at least 32 characters." >&2
    exit 10
  }
  args+=(--api-key "${LVA_VLLM_API_KEY}")
fi
if [[ "${enforce_eager}" == "1" ]]; then
  args+=(--enforce-eager)
fi
if [[ "${language_model_only}" == "1" ]]; then
  args+=(--language-model-only)
fi
if [[ -n "${kv_cache_memory}" ]]; then
  args+=(--kv-cache-memory "${kv_cache_memory}")
fi
if [[ -n "${max_num_seqs}" ]]; then
  args+=(--max-num-seqs "${max_num_seqs}")
fi

echo \
  "Starting ${served_name} MTP=${mtp_mode} runtime=${runtime_root} runner_v2=${VLLM_USE_V2_MODEL_RUNNER} enforce_eager=${enforce_eager} language_model_only=${language_model_only} on ${host}:${port}" \
  >&2
for variable_name in "${!VLLM_SMOKE_@}"; do
  unset "${variable_name}"
done
exec "${vllm_bin}" "${args[@]}"
