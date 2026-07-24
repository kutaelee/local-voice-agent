#!/usr/bin/env bash
set -euo pipefail

run_root="/home/kutae/.local/share/local-voice-agent/run"

stop_owned() {
  local name="$1"
  local expected="$2"
  local pid_file="${run_root}/${name}.pid"
  [[ -f "${pid_file}" ]] || return 0
  local pid
  pid="$(<"${pid_file}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] || {
    echo "Invalid ${name} PID file; refusing to signal." >&2
    return 1
  }
  if ! kill -0 "${pid}" 2>/dev/null; then
    return 0
  fi
  local command
  command="$(tr '\0' ' ' <"/proc/${pid}/cmdline")"
  [[ "${command}" == *"${expected}"* ]] || {
    echo "PID ${pid} is not the owned ${name} worker; refusing to signal." >&2
    return 1
  }
  kill -TERM "${pid}"
  for _ in {1..100}; do
    kill -0 "${pid}" 2>/dev/null || return 0
    sleep 0.1
  done
  echo "${name} worker did not stop within 10 seconds." >&2
  return 1
}

stop_owned stt "/apps/pc-server/workers/stt_worker.py"
stop_owned tts "tts_worker.py"
stop_owned vad "/apps/pc-server/workers/vad_worker.py"
echo "Owned audio workers stopped."
