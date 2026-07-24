#!/usr/bin/env bash
set -euo pipefail

repo="/mnt/c/Dev/Repos/local-voice-agent"
run_root="/home/kutae/.local/share/local-voice-agent/run"
log_root="/mnt/e/Data/LocalVoiceAgent/runtime/logs"
evidence_root="/mnt/e/Data/LocalVoiceAgent/runtime/evidence/salon"
runtime="/home/kutae/.local/share/local-voice-agent/runtimes/tts-qwen3-1.7b/.venv"
health_runtime="/home/kutae/.local/share/local-voice-agent/runtimes/stt-faster-whisper-1.2.1/.venv"
model="/mnt/e/AI/Models/Standalone/LocalVoiceAgent/tts/qwen3-tts-12hz-1.7b-base/fd4b254389122332181a7c3db7f27e918eec64e3"
profiles="/mnt/e/Data/LocalVoiceAgent/voice-profiles"
socket="${run_root}/tts.sock"
pid_file="${run_root}/tts.pid"
token_file="/mnt/e/Data/LocalVoiceAgent/secrets/audio-worker-token"
stamp="$(date --utc +%Y%m%dT%H%M%S.%NZ)"
log_path="${log_root}/tts-salon-smoke-${stamp}.log"
evidence_path="${evidence_root}/salon-tts-smoke-${stamp}.json"

[[ -f "${token_file}" ]] || {
  echo "Audio worker token file is unavailable." >&2
  exit 3
}
worker_token="$(<"${token_file}")"
[[ "${#worker_token}" -ge 32 ]] || {
  echo "Audio worker token must contain at least 32 characters." >&2
  exit 3
}
[[ -x "${runtime}/bin/python" && -d "${model}" ]] || {
  echo "Registered Qwen3-TTS runtime or model is unavailable." >&2
  exit 4
}
if [[ -f "${pid_file}" ]]; then
  existing_pid="$(<"${pid_file}")"
  if [[ "${existing_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    echo "A registered TTS worker is already running; refusing to replace it." >&2
    exit 5
  fi
  rm -f -- "${pid_file}"
fi
if [[ -S "${socket}" ]]; then
  if ss -xlpn | grep -F -- "${socket}" >/dev/null; then
    echo "An unowned live TTS socket already exists; refusing to replace it." >&2
    exit 5
  fi
  rm -f -- "${socket}"
elif [[ -e "${socket}" || -L "${socket}" ]]; then
  echo "A non-socket TTS path already exists; refusing to replace it." >&2
  exit 5
fi

mkdir -p "${run_root}" "${log_root}" "${evidence_root}"
chmod 700 "${run_root}"
tts_pid=""
cleanup() {
  exit_code=$?
  if [[ -n "${tts_pid}" ]] && kill -0 "${tts_pid}" 2>/dev/null; then
    kill -TERM "${tts_pid}" 2>/dev/null || true
    for _ in {1..300}; do
      kill -0 "${tts_pid}" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "${tts_pid}" 2>/dev/null; then
      kill -KILL "${tts_pid}" 2>/dev/null || true
    fi
  fi
  if [[ -f "${pid_file}" ]] && [[ "$(<"${pid_file}")" == "${tts_pid}" ]]; then
    rm -f -- "${pid_file}"
  fi
  [[ ! -S "${socket}" ]] || rm -f -- "${socket}"
  unset worker_token LVA_AUDIO_WORKER_TOKEN
  exit "${exit_code}"
}
trap cleanup EXIT

export \
  PYTHONNOUSERSITE=1 \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  LVA_AUDIO_WORKER_TOKEN="${worker_token}"
nohup "${runtime}/bin/python" \
  "${repo}/apps/pc-server/workers/qwen3_tts_worker.py" \
    --socket "${socket}" \
    --model "${model}" \
    --voice-profiles-root "${profiles}" \
    --tail-silence-ms 0 \
    --max-cached-prompts 4 \
    --max-code-tokens 384 \
  >"${log_path}" 2>&1 &
tts_pid=$!
echo "${tts_pid}" >"${pid_file}"

healthy=0
for _ in {1..180}; do
  kill -0 "${tts_pid}" 2>/dev/null || {
    echo "TTS worker exited during startup; see ${log_path}" >&2
    exit 6
  }
  if [[ -S "${socket}" ]] && \
    "${health_runtime}/bin/python" "${repo}/scripts/audio-worker-health.py" \
      "${socket}" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 1
done
[[ "${healthy}" == "1" ]] || {
  echo "TTS worker did not become healthy; see ${log_path}" >&2
  exit 7
}

PYTHONPATH="${repo}/apps/pc-server/src" \
  "/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv/bin/python" \
  "${repo}/scripts/smoke-salon-tts.py" \
  --output "${evidence_path}"
echo "Salon TTS evidence: ${evidence_path}"
