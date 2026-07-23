#!/usr/bin/env bash
set -euo pipefail

runtime="/home/kutae/.local/share/local-voice-agent/runtimes/sglang-0.5.15.post1/.venv"
model="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/gemma4/12b/target/1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee"
run_root="/home/kutae/.local/share/local-voice-agent/run"
log_root="/mnt/e/Data/LocalVoiceAgent/runtime/logs"
pid_file="${run_root}/sglang.pid"
port="${LVA_SGLANG_PORT:-8768}"
api_key="${LVA_SGLANG_API_KEY:-}"
startup_timeout_seconds="${LVA_SGLANG_STARTUP_TIMEOUT_SECONDS:-480}"

[[ "${#api_key}" -ge 32 ]] || {
  echo "LVA_SGLANG_API_KEY must contain at least 32 characters." >&2
  exit 3
}
[[ "${port}" =~ ^[0-9]+$ ]] && ((port >= 1024 && port <= 65535)) || {
  echo "LVA_SGLANG_PORT is invalid." >&2
  exit 4
}
[[ "${startup_timeout_seconds}" =~ ^[0-9]+$ ]] \
  && ((startup_timeout_seconds >= 60 && startup_timeout_seconds <= 900)) || {
  echo "LVA_SGLANG_STARTUP_TIMEOUT_SECONDS must be between 60 and 900." >&2
  exit 5
}
[[ -x "${runtime}/bin/python" && -d "${model}" ]] || {
  echo "The pinned SGLang runtime or Gemma model is unavailable." >&2
  exit 6
}

mkdir -p "${run_root}" "${log_root}"
chmod 700 "${run_root}"
if [[ -f "${pid_file}" ]]; then
  existing_pid="$(<"${pid_file}")"
  if [[ "${existing_pid}" =~ ^[0-9]+$ ]] \
    && kill -0 "${existing_pid}" 2>/dev/null; then
    echo "SGLang is already running with PID ${existing_pid}." >&2
    exit 7
  fi
fi

nohup setsid "${runtime}/bin/python" -m sglang.launch_server \
  --model-path "${model}" \
  --served-model-name gemma4-12b \
  --host 127.0.0.1 \
  --port "${port}" \
  --api-key "${api_key}" \
  --context-length 4096 \
  --mem-fraction-static 0.45 \
  --max-running-requests 1 \
  --tool-call-parser gemma4 \
  --reasoning-parser gemma4 \
  --enable-metrics \
  --disable-cuda-graph \
  >"${log_root}/sglang-12b.log" 2>&1 &
pid=$!
echo "${pid}" >"${pid_file}"

for ((elapsed = 0; elapsed < startup_timeout_seconds; elapsed += 1)); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "SGLang exited during startup; see ${log_root}/sglang-12b.log" >&2
    exit 8
  fi
  if curl \
    --silent \
    --fail \
    --max-time 5 \
    --header "Authorization: Bearer ${api_key}" \
    "http://127.0.0.1:${port}/health_generate" >/dev/null 2>&1; then
    echo "SGLang ready: pid=${pid} port=${port} model=gemma4-12b"
    exit 0
  fi
  sleep 1
done

kill -TERM -- "-${pid}" 2>/dev/null || true
echo "SGLang did not become healthy within ${startup_timeout_seconds} seconds." >&2
exit 9
