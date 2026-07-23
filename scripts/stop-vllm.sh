#!/usr/bin/env bash
set -euo pipefail

pid_file="/home/kutae/.local/share/local-voice-agent/run/vllm.pid"
[[ -f "${pid_file}" ]] || {
  echo "No owned vLLM PID file exists."
  exit 0
}
pid="$(<"${pid_file}")"
[[ "${pid}" =~ ^[0-9]+$ ]] || {
  echo "Invalid vLLM PID file; refusing to signal." >&2
  exit 3
}
if ! kill -0 "${pid}" 2>/dev/null; then
  rm -f -- "${pid_file}"
  echo "Owned vLLM process is not running."
  exit 0
fi
command="$(tr '\0' ' ' <"/proc/${pid}/cmdline")"
[[ "${command}" == *"vllm"*"serve"*"/gemma4/12b/"* ]] || {
  echo "PID ${pid} is not the owned vLLM process; refusing to signal." >&2
  exit 4
}
kill -TERM "${pid}"
for _ in {1..300}; do
  kill -0 "${pid}" 2>/dev/null || {
    rm -f -- "${pid_file}"
    echo "Owned vLLM process stopped."
    exit 0
  }
  sleep 0.1
done
echo "vLLM did not stop within 30 seconds." >&2
exit 5
