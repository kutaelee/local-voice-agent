#!/usr/bin/env bash
set -euo pipefail

repo="/mnt/c/Dev/Repos/local-voice-agent"
run_root="/home/kutae/.local/share/local-voice-agent/run"
log_root="/mnt/e/Data/LocalVoiceAgent/runtime/logs"
pid_file="${run_root}/vllm.pid"
port="${LVA_VLLM_PORT:-8766}"
api_key="${LVA_VLLM_API_KEY:-}"

[[ "${#api_key}" -ge 32 ]] || {
  echo "LVA_VLLM_API_KEY must contain at least 32 characters." >&2
  exit 3
}
[[ "${port}" =~ ^[0-9]+$ ]] && ((port >= 1024 && port <= 65535)) || {
  echo "LVA_VLLM_PORT is invalid." >&2
  exit 4
}
mkdir -p "${run_root}" "${log_root}"
chmod 700 "${run_root}"
if [[ -f "${pid_file}" ]]; then
  existing_pid="$(<"${pid_file}")"
  if [[ "${existing_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    echo "vLLM is already running with PID ${existing_pid}." >&2
    exit 5
  fi
fi

nohup env \
  LVA_VLLM_API_KEY="${api_key}" \
  VLLM_SMOKE_PORT="${port}" \
  VLLM_SMOKE_GPU_MEMORY_UTILIZATION="0.45" \
  VLLM_SMOKE_MAX_MODEL_LEN="4096" \
  VLLM_SMOKE_MAX_NUM_SEQS="1" \
  VLLM_USE_V2_MODEL_RUNNER="0" \
  bash "${repo}/scripts/serve-vllm-smoke.sh" 12b off \
  >"${log_root}/vllm-12b.log" 2>&1 &
pid=$!
echo "${pid}" >"${pid_file}"

startup_timeout_seconds="${LVA_VLLM_STARTUP_TIMEOUT_SECONDS:-360}"
[[ "${startup_timeout_seconds}" =~ ^[0-9]+$ ]] && ((startup_timeout_seconds >= 60 && startup_timeout_seconds <= 900)) || {
  echo "LVA_VLLM_STARTUP_TIMEOUT_SECONDS must be between 60 and 900." >&2
  exit 8
}

for ((elapsed = 0; elapsed < startup_timeout_seconds; elapsed += 1)); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "vLLM exited during startup; see ${log_root}/vllm-12b.log" >&2
    exit 6
  fi
  if curl \
    --silent \
    --fail \
    --max-time 2 \
    --header "Authorization: Bearer ${api_key}" \
    "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
    echo "vLLM ready: pid=${pid} port=${port} model=gemma4-12b"
    exit 0
  fi
  sleep 1
done

kill -TERM "${pid}" 2>/dev/null || true
echo "vLLM did not become healthy within ${startup_timeout_seconds} seconds." >&2
exit 7
