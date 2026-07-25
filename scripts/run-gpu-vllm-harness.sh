#!/usr/bin/env bash
set -euo pipefail

# Foreground supervisor for a gpuq reservation used by the text-first model
# harness. Audio workers intentionally stay unloaded during conversation QA.

repo="/mnt/c/Dev/Repos/local-voice-agent"
run_root="/home/kutae/.local/share/local-voice-agent/run"
secret_file="/mnt/e/Data/LocalVoiceAgent/secrets/vllm-api-key"
vllm_started=0
shutdown_requested=0

if [[ ! -r "${secret_file}" ]]; then
  echo "vLLM API credentials are unavailable." >&2
  exit 3
fi
export LVA_VLLM_API_KEY
LVA_VLLM_API_KEY="$(<"${secret_file}")"
if [[ "${#LVA_VLLM_API_KEY}" -lt 32 ]]; then
  echo "vLLM API credentials are invalid." >&2
  exit 3
fi

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  set +e
  if ((vllm_started == 1)); then
    LVA_VLLM_EXPECTED_MODEL_SIZE=12b \
      bash "${repo}/scripts/stop-vllm.sh"
  fi
  unset LVA_VLLM_API_KEY
  exit "${exit_code}"
}

request_shutdown() {
  shutdown_requested=1
}

trap cleanup EXIT
trap request_shutdown INT TERM

export \
  LVA_VLLM_MODEL_SIZE=12b \
  LVA_VLLM_MTP_MODE=off \
  LVA_VLLM_PORT=46322 \
  LVA_VLLM_STARTUP_TIMEOUT_SECONDS=600
bash "${repo}/scripts/start-vllm.sh"
vllm_started=1

echo "gpuq-managed vLLM conversation harness is ready."

while ((shutdown_requested == 0)); do
  vllm_pid="$(<"${run_root}/vllm.pid")"
  if [[ ! "${vllm_pid}" =~ ^[0-9]+$ ]] \
    || ! kill -0 "${vllm_pid}" 2>/dev/null \
    || ! curl --silent --fail --max-time 2 \
      "http://127.0.0.1:46322/health" >/dev/null; then
    echo "Registered vLLM health check failed." >&2
    exit 10
  fi
  sleep 5 &
  wait $! || true
done
