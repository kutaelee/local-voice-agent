#!/usr/bin/env bash
set -euo pipefail

repo="/mnt/c/Dev/Repos/local-voice-agent"
run_root="/home/kutae/.local/share/local-voice-agent/run"
log_root="/mnt/e/Data/LocalVoiceAgent/runtime/logs"
stt_runtime="/home/kutae/.local/share/local-voice-agent/runtimes/stt-faster-whisper-1.2.1/.venv"
tts_runtime="/home/kutae/.local/share/local-voice-agent/runtimes/tts-chatterbox-v3-py3146/.venv"
vad_runtime="/home/kutae/.local/share/local-voice-agent/runtimes/vad-silero-6.2.1/.venv"
stt_model="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/stt/faster-whisper-large-v3-turbo/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
tts_model="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/tts/chatterbox-multilingual-v3/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
stt_socket="${run_root}/stt.sock"
tts_socket="${run_root}/tts.sock"
vad_socket="${run_root}/vad.sock"

worker_token="${LVA_AUDIO_WORKER_TOKEN:-}"
[[ "${#worker_token}" -ge 32 ]] || {
  echo "LVA_AUDIO_WORKER_TOKEN must contain at least 32 characters." >&2
  exit 3
}
mkdir -p "${run_root}" "${log_root}"
chmod 700 "${run_root}"

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
  LVA_AUDIO_WORKER_TOKEN="${worker_token}" \
  "${tts_runtime}/bin/python" "${repo}/apps/pc-server/workers/tts_worker.py" \
    --socket "${tts_socket}" \
    --model "${tts_model}" \
  >"${log_root}/tts-worker.log" 2>&1 &
tts_pid=$!
started_pids+=("${tts_pid}")
echo "${tts_pid}" >"${run_root}/tts.pid"

if ! wait_for_health "${tts_socket}" 120; then
  echo "TTS worker failed health check; see ${log_root}/tts-worker.log" >&2
  exit 7
fi

trap - ERR
echo "Audio workers ready: vad_pid=${vad_pid} stt_pid=${stt_pid} tts_pid=${tts_pid}"
