#!/usr/bin/env bash
set -euo pipefail

pid_file="/home/kutae/.local/share/local-voice-agent/run/vllm.pid"
status_file="/mnt/e/Data/LocalVoiceAgent/runtime/status/vllm.json"
expected_model_size="${LVA_VLLM_EXPECTED_MODEL_SIZE:-}"
if [[ -n "${expected_model_size}" ]] \
  && [[ "${expected_model_size}" != "12b" && "${expected_model_size}" != "31b" ]]; then
  echo "LVA_VLLM_EXPECTED_MODEL_SIZE must be 12b or 31b." >&2
  exit 2
fi
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
  if [[ -f "${status_file}" ]] \
    && grep -q "\"pid\":${pid}," "${status_file}"; then
    rm -f -- "${status_file}"
  fi
  echo "Owned vLLM process is not running."
  exit 0
fi
command="$(tr '\0' ' ' <"/proc/${pid}/cmdline")"
if [[ "${command}" != *"vllm"*"serve"*"/gemma4/"*"/target/"* ]] \
  && [[ "${command}" != *"vllm"*"serve"*"/gemma4/"*"/mtp-target/"* ]]; then
  echo "PID ${pid} is not the owned vLLM process; refusing to signal." >&2
  exit 4
fi
if [[ -n "${expected_model_size}" ]] \
  && [[ "${command}" != *"/gemma4/${expected_model_size}/"* ]]; then
  echo "Owned vLLM model does not match the requested stop target." >&2
  exit 4
fi
kill -TERM "${pid}"
for _ in {1..300}; do
  kill -0 "${pid}" 2>/dev/null || {
    rm -f -- "${pid_file}"
    if [[ -f "${status_file}" ]] \
      && grep -q "\"pid\":${pid}," "${status_file}"; then
      rm -f -- "${status_file}"
    fi
    echo "Owned vLLM process stopped."
    exit 0
  }
  sleep 0.1
done
echo "vLLM did not stop within 30 seconds." >&2
exit 5
