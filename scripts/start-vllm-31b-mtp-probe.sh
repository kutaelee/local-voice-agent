#!/usr/bin/env bash
set -euo pipefail

repo="/mnt/c/Dev/Repos/local-voice-agent"
run_root="${HOME}/.local/share/local-voice-agent/run"
log_root="/mnt/e/Data/LocalVoiceAgent/runtime/logs"
status_root="/mnt/e/Data/LocalVoiceAgent/runtime/status"
pid_file="${run_root}/vllm.pid"
status_file="${status_root}/vllm.json"
port="${LVA_VLLM_PROBE_PORT:-8767}"
cpu_offload_gb="${LVA_VLLM_PROBE_CPU_OFFLOAD_GB:-36}"
startup_timeout="${LVA_VLLM_PROBE_STARTUP_TIMEOUT_SECONDS:-900}"
api_key="${LVA_VLLM_API_KEY:-}"

[[ "${#api_key}" -ge 32 ]] || {
  echo "LVA_VLLM_API_KEY must contain at least 32 characters." >&2
  exit 3
}
[[ "${port}" =~ ^[0-9]+$ ]] && ((port >= 1024 && port <= 65535)) || {
  echo "LVA_VLLM_PROBE_PORT is invalid." >&2
  exit 4
}
[[ "${cpu_offload_gb}" =~ ^(2[8-9]|3[0-9]|4[0-8])$ ]] || {
  echo "31B MTP probe CPU offload must be an integer from 28 to 48 GiB." >&2
  exit 5
}
[[ "${startup_timeout}" =~ ^[0-9]+$ ]] \
  && ((startup_timeout >= 300 && startup_timeout <= 1800)) || {
  echo "31B MTP probe startup timeout must be 300 to 1800 seconds." >&2
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
  ((free_mib >= 28500)) || {
    echo \
      "31B MTP probe requires 28500 MiB free; observed ${free_mib} MiB." \
      >&2
    exit 8
  }
  ((sample == 2)) || sleep 3
done

available_kib="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
required_kib="$(((cpu_offload_gb + 12) * 1024 * 1024))"
[[ "${available_kib}" =~ ^[0-9]+$ ]] \
  && ((available_kib >= required_kib)) || {
  echo \
    "31B MTP probe requires at least $((cpu_offload_gb + 12)) GiB available WSL memory; observed $((available_kib / 1024 / 1024)) GiB." \
    >&2
  exit 9
}

mkdir -p "${run_root}" "${log_root}" "${status_root}"
chmod 700 "${run_root}"
if [[ -f "${pid_file}" ]]; then
  existing_pid="$(<"${pid_file}")"
  if [[ "${existing_pid}" =~ ^[0-9]+$ ]] \
    && kill -0 "${existing_pid}" 2>/dev/null; then
    echo "An owned vLLM process is already running." >&2
    exit 10
  fi
  rm -f -- "${pid_file}"
fi

stamp="$(date --utc +%Y%m%dT%H%M%SZ)"
log_file="${log_root}/vllm-31b-mtp-probe-${stamp}.log"
export \
  VLLM_SMOKE_PORT="${port}" \
  VLLM_SMOKE_GPU_MEMORY_UTILIZATION="0.95" \
  VLLM_SMOKE_MAX_MODEL_LEN="256" \
  VLLM_SMOKE_MAX_NUM_SEQS="1" \
  VLLM_SMOKE_ENFORCE_EAGER="1" \
  VLLM_SMOKE_LANGUAGE_MODEL_ONLY="1" \
  VLLM_SMOKE_KV_CACHE_MEMORY_BYTES="268435456" \
  VLLM_SMOKE_CPU_OFFLOAD_GB="${cpu_offload_gb}" \
  VLLM_SMOKE_SPECULATIVE_TOKENS="1" \
  VLLM_USE_V2_MODEL_RUNNER="0"

nohup setsid bash "${repo}/scripts/serve-vllm-smoke.sh" 31b on \
  >"${log_file}" 2>&1 &
pid=$!
echo "${pid}" >"${pid_file}"
unset api_key LVA_VLLM_API_KEY

for ((elapsed = 0; elapsed < startup_timeout; elapsed += 1)); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f -- "${pid_file}"
    echo "31B MTP probe exited during startup; see ${log_file}" >&2
    exit 11
  fi
  if curl \
    --silent \
    --fail \
    --max-time 2 \
    "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
    status_tmp="${status_file}.tmp.${pid}"
    printf \
      '{"schema_version":"1.0","component":"vllm","state":"ready","pid":%s,"port":%s,"model_size":"31b","model_id":"gemma4-31b-mtp","mtp_mode":"on","cpu_offload_gib":%s,"log_path":"%s","updated_at":"%s"}\n' \
      "${pid}" \
      "${port}" \
      "${cpu_offload_gb}" \
      "${log_file}" \
      "$(date --utc +%Y-%m-%dT%H:%M:%SZ)" \
      >"${status_tmp}"
    mv -f -- "${status_tmp}" "${status_file}"
    echo \
      "31B MTP probe ready: pid=${pid} port=${port} offload=${cpu_offload_gb}"
    exit 0
  fi
  sleep 1
done

kill -TERM "${pid}" 2>/dev/null || true
rm -f -- "${pid_file}"
echo "31B MTP probe did not become healthy within ${startup_timeout}s." >&2
exit 12
