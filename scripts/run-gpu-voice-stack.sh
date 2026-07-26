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
omni_tts_started=0
omni_tts_pid=""
shutdown_requested=0
omni_tts_port="${LVA_VLLM_OMNI_TTS_PORT:-46329}"
log_root="/mnt/e/Data/LocalVoiceAgent/runtime/logs"
voice_llm_size="${LVA_VOICE_LLM_SIZE:-e4b}"
tts_backend="${LVA_TTS_BACKEND:-worker}"
case "${voice_llm_size}" in
  e4b|12b) ;;
  *)
    echo "LVA_VOICE_LLM_SIZE must be e4b or 12b for the interactive voice stack." >&2
    exit 2
    ;;
esac
case "${tts_backend}" in
  worker|vllm-omni) ;;
  *)
    echo "LVA_TTS_BACKEND must be worker or vllm-omni." >&2
    exit 2
    ;;
esac

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
  if ((omni_tts_started == 1)) && [[ "${omni_tts_pid}" =~ ^[0-9]+$ ]] \
    && kill -0 "${omni_tts_pid}" 2>/dev/null; then
    kill -TERM "${omni_tts_pid}"
    wait "${omni_tts_pid}" 2>/dev/null || true
  fi
  rm -f -- "${run_root}/vllm-omni-tts.pid"
  if ((audio_started == 1)); then
    bash "${repo}/scripts/stop-audio-workers.sh"
  fi
  if ((vllm_started == 1)); then
    LVA_VLLM_EXPECTED_MODEL_SIZE="${voice_llm_size}" \
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
  LVA_VLLM_MODEL_SIZE="${voice_llm_size}" \
  LVA_VLLM_MTP_MODE=off \
  LVA_VLLM_PORT=46322 \
  LVA_VLLM_STARTUP_TIMEOUT_SECONDS=600
bash "${repo}/scripts/start-vllm.sh"
vllm_started=1

export \
  LVA_TTS_ENGINE=qwen3 \
  LVA_SKIP_TTS_WORKER="$([[ "${tts_backend}" == "worker" ]] && echo 0 || echo 1)" \
  LVA_QWEN3_TTS_SIZE="${LVA_QWEN3_TTS_SIZE:-1.7b}"
audio_started=1
bash "${repo}/scripts/start-audio-workers.sh"

if [[ "${tts_backend}" == "vllm-omni" ]]; then
  mkdir -p "${log_root}"
  bash "${repo}/scripts/run-vllm-omni-tts.sh" \
    >"${log_root}/vllm-omni-tts.log" 2>&1 &
  omni_tts_pid=$!
  omni_tts_started=1
  echo "${omni_tts_pid}" >"${run_root}/vllm-omni-tts.pid"
  for _ in {1..180}; do
    if curl --silent --fail --max-time 2 \
      "http://127.0.0.1:${omni_tts_port}/health" >/dev/null; then
      break
    fi
    if ! kill -0 "${omni_tts_pid}" 2>/dev/null; then
      echo "vLLM-Omni TTS exited during startup." >&2
      exit 12
    fi
    sleep 1
  done
  if ! curl --silent --fail --max-time 2 \
    "http://127.0.0.1:${omni_tts_port}/health" >/dev/null; then
    echo "vLLM-Omni TTS failed health check." >&2
    exit 12
  fi
  "${stt_runtime}/bin/python" "${repo}/scripts/sync-vllm-omni-voices.py" \
    --profiles-root "/mnt/e/Data/LocalVoiceAgent/voice-profiles/profiles" \
    --base-url "http://127.0.0.1:${omni_tts_port}"
fi

echo "gpuq-managed interactive voice stack is ready (tts=${tts_backend})."

while ((shutdown_requested == 0)); do
  vllm_pid="$(<"${run_root}/vllm.pid")"
  if [[ ! "${vllm_pid}" =~ ^[0-9]+$ ]] \
    || ! kill -0 "${vllm_pid}" 2>/dev/null \
    || ! curl --silent --fail --max-time 2 \
      "http://127.0.0.1:46322/health" >/dev/null; then
    echo "Registered vLLM health check failed." >&2
    exit 10
  fi

  for worker in vad stt; do
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

  if [[ "${tts_backend}" == "vllm-omni" ]]; then
    if ! kill -0 "${omni_tts_pid}" 2>/dev/null \
      || ! curl --silent --fail --max-time 2 \
        "http://127.0.0.1:${omni_tts_port}/health" >/dev/null; then
      echo "Registered vLLM-Omni TTS health check failed." >&2
      exit 12
    fi
  else
    tts_pid="$(<"${run_root}/tts.pid")"
    if [[ ! "${tts_pid}" =~ ^[0-9]+$ ]] \
      || ! kill -0 "${tts_pid}" 2>/dev/null \
      || ! "${stt_runtime}/bin/python" \
        "${repo}/scripts/audio-worker-health.py" \
        "${run_root}/tts.sock" >/dev/null 2>&1; then
      echo "Registered Qwen3-TTS worker health check failed." >&2
      exit 12
    fi
  fi

  sleep 5 &
  wait $! || true
done

echo "gpuq-managed interactive voice stack shutdown requested."
