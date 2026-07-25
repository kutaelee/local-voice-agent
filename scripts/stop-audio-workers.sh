#!/usr/bin/env bash
set -euo pipefail

run_root="/home/kutae/.local/share/local-voice-agent/run"

stop_owned() {
  local name="$1"
  local expected="$2"
  local pid_file="${run_root}/${name}.pid"
  local socket_file="${run_root}/${name}.sock"
  if [[ -e "${pid_file}" ]]; then
    [[ -f "${pid_file}" && ! -L "${pid_file}" ]] || {
      echo "Invalid ${name} PID path; refusing cleanup." >&2
      return 1
    }
    local pid
    pid="$(<"${pid_file}")"
    [[ "${pid}" =~ ^[0-9]+$ ]] || {
      echo "Invalid ${name} PID file; refusing to signal." >&2
      return 1
    }
    if kill -0 "${pid}" 2>/dev/null; then
      local command
      command="$(tr '\0' ' ' <"/proc/${pid}/cmdline")"
      [[ "${command}" == *"${expected}"* ]] || {
        echo "PID ${pid} is not the owned ${name} worker; refusing to signal." >&2
        return 1
      }
      kill -TERM "${pid}"
      local stopped=0
      for _ in {1..100}; do
        if ! kill -0 "${pid}" 2>/dev/null; then
          stopped=1
          break
        fi
        sleep 0.1
      done
      [[ "${stopped}" -eq 1 ]] || {
        echo "${name} worker did not stop within 10 seconds." >&2
        return 1
      }
    fi
    rm -f -- "${pid_file}"
  fi
  if [[ -e "${socket_file}" || -S "${socket_file}" ]]; then
    [[ -S "${socket_file}" && ! -L "${socket_file}" ]] || {
      echo "Invalid ${name} socket path; refusing cleanup." >&2
      return 1
    }
    rm -f -- "${socket_file}"
  fi
}

stop_owned stt "/apps/pc-server/workers/stt_worker.py"
stop_owned tts "tts_worker.py"
stop_owned vad "/apps/pc-server/workers/vad_worker.py"
echo "Owned audio workers stopped."
