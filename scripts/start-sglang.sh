#!/usr/bin/env bash
set -euo pipefail

runtime="/home/kutae/.local/share/local-voice-agent/runtimes/sglang-0.5.15.post1/.venv"
launcher="/mnt/c/Dev/Repos/local-voice-agent/scripts/launch-sglang-secure.py"
base_model="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/gemma4/12b/target/1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee"
mtp_model="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/gemma4/12b/mtp-target/b6ed86275a6a5735884e208bfed95b445a684ca2"
mtp_assistant="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/gemma4/12b/mtp-assistant/18934064dd4c5c6cc3621f6381e7d377fc8cb7bd"
run_root="/home/kutae/.local/share/local-voice-agent/run"
log_root="/mnt/e/Data/LocalVoiceAgent/runtime/logs"
pid_file="${run_root}/sglang.pid"
port="${LVA_SGLANG_PORT:-8768}"
mode="${LVA_SGLANG_MODE:-base}"
speculative_steps="${LVA_SGLANG_SPECULATIVE_STEPS:-1}"
mtp_cpu_offload_gib="${LVA_SGLANG_MTP_CPU_OFFLOAD_GIB:-4}"
startup_timeout_seconds="${LVA_SGLANG_STARTUP_TIMEOUT_SECONDS:-480}"

api_key_for_validation="${LVA_SGLANG_API_KEY:-}"
[[ "${#api_key_for_validation}" -ge 32 ]] || {
  echo "LVA_SGLANG_API_KEY must contain at least 32 characters." >&2
  exit 3
}
unset api_key_for_validation
[[ "${port}" =~ ^[0-9]+$ ]] && ((port >= 1024 && port <= 65535)) || {
  echo "LVA_SGLANG_PORT is invalid." >&2
  exit 4
}
[[ "${startup_timeout_seconds}" =~ ^[0-9]+$ ]] \
  && ((startup_timeout_seconds >= 60 && startup_timeout_seconds <= 900)) || {
  echo "LVA_SGLANG_STARTUP_TIMEOUT_SECONDS must be between 60 and 900." >&2
  exit 5
}
[[ "${mode}" == "base" || "${mode}" == "mtp" ]] || {
  echo "LVA_SGLANG_MODE must be base or mtp." >&2
  exit 6
}
[[ "${speculative_steps}" =~ ^[1-5]$ ]] || {
  echo "LVA_SGLANG_SPECULATIVE_STEPS must be between 1 and 5." >&2
  exit 7
}
[[ "${mtp_cpu_offload_gib}" =~ ^([0-9]|1[0-6])$ ]] || {
  echo "LVA_SGLANG_MTP_CPU_OFFLOAD_GIB must be between 0 and 16." >&2
  exit 8
}
[[ -x "${runtime}/bin/python" && -f "${launcher}" ]] || {
  echo "The pinned SGLang runtime or secure launcher is unavailable." >&2
  exit 9
}

if [[ "${mode}" == "base" ]]; then
  model="${base_model}"
  served_model="gemma4-12b"
  context_length=4096
  mem_fraction=0.45
  minimum_free_mib=22000
  log_file="${log_root}/sglang-12b-base.log"
  speculative_args=()
else
  model="${mtp_model}"
  served_model="gemma4-12b-mtp"
  context_length=2048
  mem_fraction=0.82
  minimum_free_mib=28500
  log_file="${log_root}/sglang-12b-mtp-s${speculative_steps}.log"
  speculative_args=(
    --speculative-algorithm NEXTN
    --speculative-draft-model-path "${mtp_assistant}"
    --speculative-num-steps "${speculative_steps}"
    --speculative-num-draft-tokens "$((speculative_steps + 1))"
    --speculative-eagle-topk 1
    --cpu-offload-gb "${mtp_cpu_offload_gib}"
  )
fi

[[ -d "${model}" ]] || {
  echo "The pinned SGLang runtime or Gemma model is unavailable." >&2
  exit 10
}
if [[ "${mode}" == "mtp" && ! -d "${mtp_assistant}" ]]; then
  echo "The paired Gemma MTP assistant is unavailable." >&2
  exit 11
fi
command -v nvidia-smi >/dev/null 2>&1 || {
  echo "nvidia-smi is unavailable; refusing an unverified GPU reservation." >&2
  exit 12
}

# A stable two-sample free-memory gate avoids racing a concurrently loading
# ComfyUI/Qwen task. This launcher never stops or unloads foreign processes.
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
    exit 13
  }
  if ((free_mib < minimum_free_mib)); then
    echo \
      "GPU reservation declined: mode=${mode} requires ${minimum_free_mib} MiB free; observed ${free_mib} MiB. A concurrent workload is preserved." \
      >&2
    exit 14
  fi
  ((sample == 2)) || sleep 2
done

mkdir -p "${run_root}" "${log_root}"
chmod 700 "${run_root}"
if [[ -f "${pid_file}" ]]; then
  existing_pid="$(<"${pid_file}")"
  if [[ "${existing_pid}" =~ ^[0-9]+$ ]] \
    && kill -0 "${existing_pid}" 2>/dev/null; then
    echo "SGLang is already running with PID ${existing_pid}." >&2
    exit 15
  fi
fi

nohup setsid "${runtime}/bin/python" "${launcher}" \
  --model-path "${model}" \
  --served-model-name "${served_model}" \
  --host 127.0.0.1 \
  --port "${port}" \
  --context-length "${context_length}" \
  --mem-fraction-static "${mem_fraction}" \
  --max-running-requests 1 \
  --tool-call-parser gemma4 \
  --reasoning-parser gemma4 \
  --enable-metrics \
  --disable-cuda-graph \
  "${speculative_args[@]}" \
  >"${log_file}" 2>&1 &
pid=$!
echo "${pid}" >"${pid_file}"
unset LVA_SGLANG_API_KEY

for ((elapsed = 0; elapsed < startup_timeout_seconds; elapsed += 1)); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "SGLang exited during startup; see ${log_file}" >&2
    exit 16
  fi
  if curl \
    --silent \
    --fail \
    --max-time 5 \
    "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
    echo "SGLang ready: pid=${pid} port=${port} model=${served_model} mode=${mode}"
    exit 0
  fi
  sleep 1
done

kill -TERM -- "-${pid}" 2>/dev/null || true
echo "SGLang did not become healthy within ${startup_timeout_seconds} seconds." >&2
exit 9
