#!/usr/bin/env bash
set -euo pipefail

repo="/mnt/c/Dev/Repos/local-voice-agent"
run_root="/home/kutae/.local/share/local-voice-agent/run"
log_root="/mnt/e/Data/LocalVoiceAgent/runtime/logs"
status_root="/mnt/e/Data/LocalVoiceAgent/runtime/status"
pid_file="${run_root}/vllm.pid"
status_file="${status_root}/vllm.json"
port="${LVA_VLLM_PORT:-8766}"
api_key="${LVA_VLLM_API_KEY:-}"
model_size="${LVA_VLLM_MODEL_SIZE:-12b}"
mtp_mode="${LVA_VLLM_MTP_MODE:-off}"

[[ "${#api_key}" -ge 32 ]] || {
  echo "LVA_VLLM_API_KEY must contain at least 32 characters." >&2
  exit 3
}
[[ "${port}" =~ ^[0-9]+$ ]] && ((port >= 1024 && port <= 65535)) || {
  echo "LVA_VLLM_PORT is invalid." >&2
  exit 4
}
case "${model_size}:${mtp_mode}" in
  12b:off)
    minimum_free_mib=22000
    log_file="${log_root}/vllm-12b.log"
    ;;
  12b:on)
    minimum_free_mib=28500
    log_file="${log_root}/vllm-12b-mtp.log"
    ;;
  12b:exact-off)
    minimum_free_mib=28500
    log_file="${log_root}/vllm-12b-mtp-target-off.log"
    ;;
  31b:off)
    minimum_free_mib=27000
    log_file="${log_root}/vllm-31b.log"
    ;;
  31b:on)
    echo "31B MTP is not enabled before its runtime validation gate passes." >&2
    exit 5
    ;;
  *)
    echo "LVA_VLLM_MODEL_SIZE/MTP_MODE must be 12b|31b and off|exact-off|on." >&2
    exit 5
    ;;
esac
command -v nvidia-smi >/dev/null 2>&1 || {
  echo "nvidia-smi is unavailable; refusing an unverified GPU reservation." >&2
  exit 6
}
for sample in 1 2; do
  free_mib="$(
    nvidia-smi \
      --query-gpu=memory.free \
      --format=csv,noheader,nounits |
      head -n 1 |
      tr -d '[:space:]'
  )"
  [[ "${free_mib}" =~ ^[0-9]+$ ]] || {
    echo "Unable to measure free GPU memory." >&2
    exit 7
  }
  if ((free_mib < minimum_free_mib)); then
    echo \
      "GPU reservation declined: vLLM ${model_size} MTP=${mtp_mode} requires ${minimum_free_mib} MiB free; observed ${free_mib} MiB. A concurrent workload is preserved." \
      >&2
    exit 8
  fi
  ((sample == 2)) || sleep 2
done
mkdir -p "${run_root}" "${log_root}" "${status_root}"
chmod 700 "${run_root}"
if [[ -f "${pid_file}" ]]; then
  existing_pid="$(<"${pid_file}")"
  if [[ "${existing_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    echo "vLLM is already running with PID ${existing_pid}." >&2
    exit 9
  fi
  rm -f -- "${pid_file}"
fi

startup_timeout_seconds="${LVA_VLLM_STARTUP_TIMEOUT_SECONDS:-360}"
[[ "${startup_timeout_seconds}" =~ ^[0-9]+$ ]] && ((startup_timeout_seconds >= 60 && startup_timeout_seconds <= 900)) || {
  echo "LVA_VLLM_STARTUP_TIMEOUT_SECONDS must be between 60 and 900." >&2
  exit 10
}

export \
  VLLM_SMOKE_PORT="${port}" \
  VLLM_SMOKE_GPU_MEMORY_UTILIZATION="0.45" \
  VLLM_SMOKE_MAX_MODEL_LEN="4096" \
  VLLM_SMOKE_MAX_NUM_SEQS="1" \
  VLLM_SMOKE_ENFORCE_EAGER="0" \
  VLLM_SMOKE_LANGUAGE_MODEL_ONLY="0" \
  VLLM_SMOKE_KV_CACHE_MEMORY_BYTES="" \
  VLLM_USE_V2_MODEL_RUNNER="0"
if [[ "${model_size}" == "12b" && "${mtp_mode}" != "off" ]]; then
  export \
    VLLM_SMOKE_GPU_MEMORY_UTILIZATION="0.90" \
    VLLM_SMOKE_MAX_MODEL_LEN="2048" \
    VLLM_SMOKE_LANGUAGE_MODEL_ONLY="1"
elif [[ "${model_size}" == "31b" ]]; then
  export \
    VLLM_SMOKE_GPU_MEMORY_UTILIZATION="0.72" \
    VLLM_SMOKE_MAX_MODEL_LEN="256" \
    VLLM_SMOKE_MAX_NUM_SEQS="1" \
    VLLM_SMOKE_ENFORCE_EAGER="1" \
    VLLM_SMOKE_LANGUAGE_MODEL_ONLY="1" \
    VLLM_SMOKE_KV_CACHE_MEMORY_BYTES="402653184"
fi
nohup bash "${repo}/scripts/serve-vllm-smoke.sh" "${model_size}" "${mtp_mode}" \
  >"${log_file}" 2>&1 &
pid=$!
echo "${pid}" >"${pid_file}"
unset api_key LVA_VLLM_API_KEY

for ((elapsed = 0; elapsed < startup_timeout_seconds; elapsed += 1)); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f -- "${pid_file}"
    echo "vLLM exited during startup; see ${log_file}" >&2
    exit 11
  fi
  if curl \
    --silent \
    --fail \
    --max-time 2 \
    "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
    served_model="gemma4-${model_size}"
    if [[ "${mtp_mode}" == "on" ]]; then
      served_model="${served_model}-mtp"
    elif [[ "${mtp_mode}" == "exact-off" ]]; then
      served_model="${served_model}-mtp-target-off"
    fi
    status_tmp="${status_file}.tmp.${pid}"
    printf \
      '{"schema_version":"1.0","component":"vllm","state":"ready","pid":%s,"port":%s,"model_size":"%s","model_id":"%s","mtp_mode":"%s","log_path":"%s","updated_at":"%s"}\n' \
      "${pid}" \
      "${port}" \
      "${model_size}" \
      "${served_model}" \
      "${mtp_mode}" \
      "${log_file}" \
      "$(date --utc +%Y-%m-%dT%H:%M:%SZ)" \
      >"${status_tmp}"
    mv -f -- "${status_tmp}" "${status_file}"
    echo "vLLM ready: pid=${pid} port=${port} model=${served_model}"
    exit 0
  fi
  sleep 1
done

kill -TERM "${pid}" 2>/dev/null || true
for _ in {1..300}; do
  kill -0 "${pid}" 2>/dev/null || break
  sleep 0.1
done
rm -f -- "${pid_file}"
echo "vLLM did not become healthy within ${startup_timeout_seconds} seconds." >&2
exit 12
