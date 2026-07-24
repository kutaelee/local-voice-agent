#!/usr/bin/env bash
set -euo pipefail

# Foreground supervisor for gpuq. The scheduler reservation remains active for
# the complete lifetime of the detached vLLM, VAD, STT, and TTS workers.

repo="/mnt/c/Dev/Repos/local-voice-agent"
run_root="/home/kutae/.local/share/local-voice-agent/run"
stt_runtime="/home/kutae/.local/share/local-voice-agent/runtimes/stt-faster-whisper-1.2.1/.venv"
worker_token_file="/mnt/e/Data/LocalVoiceAgent/secrets/audio-worker-token"
vllm_started=0
audio_started=0
shutdown_requested=0

if [[ ! -r "${worker_token_file}" ]]; then
  echo "Audio worker token is unavailable." >&2
  exit 3
fi
export LVA_AUDIO_WORKER_TOKEN
LVA_AUDIO_WORKER_TOKEN="$(<"${worker_token_file}")"
if [[ "${#LVA_AUDIO_WORKER_TOKEN}" -lt 32 ]]; then
  echo "Audio worker token is invalid." >&2
  exit 3
fi

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  set +e
  if ((audio_started == 1)); then
    bash "${repo}/scripts/stop-audio-workers.sh"
  fi
  if ((vllm_started == 1)); then
    LVA_VLLM_EXPECTED_MODEL_SIZE=12b \
      bash "${repo}/scripts/stop-vllm.sh"
  fi
  unset LVA_AUDIO_WORKER_TOKEN
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

export \
  LVA_TTS_ENGINE=qwen3 \
  LVA_QWEN3_TTS_SIZE=0.6b
bash "${repo}/scripts/start-audio-workers.sh"
audio_started=1

echo "gpuq-managed interactive voice stack is ready."

while ((shutdown_requested == 0)); do
  vllm_pid="$(<"${run_root}/vllm.pid")"
  if [[ ! "${vllm_pid}" =~ ^[0-9]+$ ]] \
    || ! kill -0 "${vllm_pid}" 2>/dev/null \
    || ! curl --silent --fail --max-time 2 \
      "http://127.0.0.1:46322/health" >/dev/null; then
    echo "Registered vLLM health check failed." >&2
    exit 10
  fi

  for worker in vad stt tts; do
    pid_file="${run_root}/${worker}.pid"
    worker_pid="$(<"${pid_file}")"
    socket_path="${run_root}/${worker}.sock"
    if [[ ! "${worker_pid}" =~ ^[0-9]+$ ]] \
      || ! kill -0 "${worker_pid}" 2>/dev/null \
      || ! "${stt_runtime}/bin/python" \
        "${repo}/scripts/audio-worker-health.py" \
        "${socket_path}" >/dev/null 2>&1; then
      echo "Registered ${worker} worker health check failed." >&2
      exit 11
    fi
  done

  sleep 5 &
  wait $! || true
done

echo "gpuq-managed interactive voice stack shutdown requested."
