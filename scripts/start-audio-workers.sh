#!/usr/bin/env bash
set -euo pipefail

repo="/mnt/c/Dev/Repos/local-voice-agent"
run_root="/home/kutae/.local/share/local-voice-agent/run"
log_root="/mnt/e/Data/LocalVoiceAgent/runtime/logs"
stt_runtime="/home/kutae/.local/share/local-voice-agent/runtimes/stt-faster-whisper-1.2.1/.venv"
tts_engine="${LVA_TTS_ENGINE:-qwen3}"
qwen3_tts_size="${LVA_QWEN3_TTS_SIZE:-1.7b}"
vad_runtime="/home/kutae/.local/share/local-voice-agent/runtimes/vad-silero-6.2.1/.venv"
stt_model="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/stt/faster-whisper-large-v3-turbo/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
voice_profiles_root="/mnt/e/Data/LocalVoiceAgent/voice-profiles"
stt_socket="${run_root}/stt.sock"
tts_socket="${run_root}/tts.sock"
vad_socket="${run_root}/vad.sock"

worker_token="${LVA_AUDIO_WORKER_TOKEN:-}"
if [[ -z "${worker_token}" && -f /mnt/e/Data/LocalVoiceAgent/secrets/audio-worker-token ]]; then
  worker_token="$(< /mnt/e/Data/LocalVoiceAgent/secrets/audio-worker-token)"
fi
[[ "${#worker_token}" -ge 32 ]] || {
  echo "LVA_AUDIO_WORKER_TOKEN must contain at least 32 characters." >&2
  exit 3
}
export LVA_AUDIO_WORKER_TOKEN="${worker_token}"
mkdir -p "${run_root}" "${log_root}" "${voice_profiles_root}/profiles"
chmod 700 "${run_root}"
chmod 700 "${voice_profiles_root}" "${voice_profiles_root}/profiles"

case "${tts_engine}" in
  qwen3)
    tts_runtime="/home/kutae/.local/share/local-voice-agent/runtimes/tts-qwen3-1.7b/.venv"
    case "${qwen3_tts_size}" in
      0.6b)
        tts_model="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/tts/qwen3-tts-12hz-0.6b-base/5d83992436eae1d760afd27aff78a71d676296fc"
        ;;
      1.7b)
        tts_model="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/tts/qwen3-tts-12hz-1.7b-base/fd4b254389122332181a7c3db7f27e918eec64e3"
        ;;
      *)
        echo "LVA_QWEN3_TTS_SIZE must be 0.6b or 1.7b." >&2
        exit 3
        ;;
    esac
    tts_worker="${repo}/apps/pc-server/workers/qwen3_tts_worker.py"
    # Inter-unit silence is added once by the gateway after the whole response.
    # Adding it here would create a guaranteed pause after every sentence unit.
    tts_extra_args=(
      --tail-silence-ms 0
      --max-cached-prompts 4
      --max-code-tokens 384
    )
    ;;
  chatterbox)
    tts_runtime="/home/kutae/.local/share/local-voice-agent/runtimes/tts-chatterbox-v3-py3146/.venv"
    tts_model="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/tts/chatterbox-multilingual-v3/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
    tts_worker="${repo}/apps/pc-server/workers/tts_worker.py"
    tts_extra_args=()
    ;;
  *)
    echo "LVA_TTS_ENGINE must be qwen3 or chatterbox." >&2
    exit 3
    ;;
esac

assert_not_running() {
  local name="$1"
  local pid_file="${run_root}/${name}.pid"
  if [[ -f "${pid_file}" ]]; then
    local pid
    pid="$(<"${pid_file}")"
    if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null; then
      echo "${name} worker is already running with PID ${pid}." >&2
      exit 4
    fi
  fi
}

wait_for_health() {
  local socket="$1"
  local attempts="$2"
  for ((index = 0; index < attempts; index++)); do
    if [[ -S "${socket}" ]] && \
      "${stt_runtime}/bin/python" "${repo}/scripts/audio-worker-health.py" \
        "${socket}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

assert_not_running stt
assert_not_running tts
assert_not_running vad
started_pids=()
cleanup_on_error() {
  local exit_code=$?
  for pid in "${started_pids[@]}"; do
    kill -TERM "${pid}" 2>/dev/null || true
  done
  exit "${exit_code}"
}
trap cleanup_on_error ERR

nohup env \
  PYTHONNOUSERSITE=1 \
  LVA_AUDIO_WORKER_TOKEN="${worker_token}" \
  "${vad_runtime}/bin/python" "${repo}/apps/pc-server/workers/vad_worker.py" \
    --socket "${vad_socket}" \
    --threshold 0.5 \
    --negative-threshold 0.35 \
    --min-silence-ms 500 \
    --min-speech-ms 100 \
  >"${log_root}/vad-worker.log" 2>&1 &
vad_pid=$!
started_pids+=("${vad_pid}")
echo "${vad_pid}" >"${run_root}/vad.pid"

if ! wait_for_health "${vad_socket}" 30; then
  echo "VAD worker failed health check; see ${log_root}/vad-worker.log" >&2
  exit 5
fi

stt_libraries="${stt_runtime}/lib/python3.12/site-packages/nvidia/cublas/lib:${stt_runtime}/lib/python3.12/site-packages/nvidia/cudnn/lib"
nohup env \
  PYTHONNOUSERSITE=1 \
  HF_HUB_OFFLINE=1 \
  LD_LIBRARY_PATH="${stt_libraries}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
  LVA_AUDIO_WORKER_TOKEN="${worker_token}" \
  "${stt_runtime}/bin/python" "${repo}/apps/pc-server/workers/stt_worker.py" \
    --socket "${stt_socket}" \
    --model "${stt_model}" \
    --device cuda \
    --compute-type float16 \
  >"${log_root}/stt-worker.log" 2>&1 &
stt_pid=$!
started_pids+=("${stt_pid}")
echo "${stt_pid}" >"${run_root}/stt.pid"

if ! wait_for_health "${stt_socket}" 90; then
  echo "STT worker failed health check; see ${log_root}/stt-worker.log" >&2
  exit 6
fi

nohup env \
  PYTHONNOUSERSITE=1 \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  LVA_AUDIO_WORKER_TOKEN="${worker_token}" \
  "${tts_runtime}/bin/python" "${tts_worker}" \
    --socket "${tts_socket}" \
    --model "${tts_model}" \
    --voice-profiles-root "${voice_profiles_root}" \
    "${tts_extra_args[@]}" \
  >"${log_root}/tts-worker.log" 2>&1 &
tts_pid=$!
started_pids+=("${tts_pid}")
echo "${tts_pid}" >"${run_root}/tts.pid"

if ! wait_for_health "${tts_socket}" 120; then
  echo "TTS worker failed health check; see ${log_root}/tts-worker.log" >&2
  exit 7
fi

trap - ERR
echo "Audio workers ready: vad_pid=${vad_pid} stt_pid=${stt_pid} tts_pid=${tts_pid} tts_engine=${tts_engine} qwen3_size=${qwen3_tts_size}"
