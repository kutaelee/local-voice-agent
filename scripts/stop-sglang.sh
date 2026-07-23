#!/usr/bin/env bash
set -euo pipefail

pid_file="/home/kutae/.local/share/local-voice-agent/run/sglang.pid"
[[ -f "${pid_file}" ]] || {
  echo "No owned SGLang PID file exists."
  exit 0
}
pid="$(<"${pid_file}")"
[[ "${pid}" =~ ^[0-9]+$ ]] || {
  echo "Invalid SGLang PID file; refusing to signal." >&2
  exit 3
}
if ! kill -0 "${pid}" 2>/dev/null; then
  echo "Owned SGLang process is not running."
  exit 0
fi
command="$(tr '\0' ' ' <"/proc/${pid}/cmdline")"
[[ "${command}" == *"launch-sglang-secure.py"*"/gemma4/12b/"* ]] || {
  echo "PID ${pid} is not the owned SGLang process; refusing to signal." >&2
  exit 4
}
session_id="$(ps -o sid= -p "${pid}" | tr -d ' ')"
[[ "${session_id}" == "${pid}" ]] || {
  echo "Owned SGLang process is not its session leader; refusing group signal." >&2
  exit 5
}
kill -TERM -- "-${pid}"
for _ in {1..600}; do
  kill -0 "${pid}" 2>/dev/null || {
    rm -f -- "${pid_file}"
    echo "Owned SGLang process group stopped."
    exit 0
  }
  sleep 0.1
done
echo "SGLang did not stop within 60 seconds." >&2
exit 6
