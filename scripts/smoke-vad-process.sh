#!/usr/bin/env bash
set -euo pipefail

repo="/mnt/c/Dev/Repos/local-voice-agent"
runtime="/home/kutae/.local/share/local-voice-agent/runtimes/vad-silero-6.2.1/.venv"
socket="/home/kutae/.local/share/local-voice-agent/run/vad-smoke.sock"
log="/mnt/e/Data/LocalVoiceAgent/runtime/logs/vad-worker-smoke.log"

[[ "${#LVA_AUDIO_WORKER_TOKEN}" -ge 32 ]] || {
  echo "LVA_AUDIO_WORKER_TOKEN must contain at least 32 characters." >&2
  exit 3
}
mkdir -p "$(dirname -- "${socket}")" "$(dirname -- "${log}")"

"${runtime}/bin/python" "${repo}/apps/pc-server/workers/vad_worker.py" \
  --socket "${socket}" >"${log}" 2>&1 &
pid=$!
cleanup() {
  kill -TERM "${pid}" 2>/dev/null || true
  wait "${pid}" 2>/dev/null || true
}
trap cleanup EXIT

healthy=0
for _ in {1..50}; do
  if [[ -S "${socket}" ]] \
    && "${runtime}/bin/python" "${repo}/scripts/audio-worker-health.py" \
      "${socket}" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  kill -0 "${pid}"
  sleep 0.2
done
[[ "${healthy}" == 1 ]] || {
  echo "VAD worker did not become healthy." >&2
  exit 4
}

"${runtime}/bin/python" "${repo}/scripts/audio-worker-health.py" "${socket}"
"${runtime}/bin/python" "${repo}/scripts/smoke-vad-worker.py" \
  --socket "${socket}"
