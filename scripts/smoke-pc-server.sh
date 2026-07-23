#!/usr/bin/env bash
set -euo pipefail

repo_root="/mnt/c/Dev/Repos/local-voice-agent"
app_root="${repo_root}/apps/pc-server"
runtime_root="/home/kutae/.local/share/local-voice-agent/runtimes/pc-server"
server_python="${runtime_root}/.venv/bin/python"
host="${LVA_SMOKE_HOST:-127.0.0.1}"
port="${LVA_SMOKE_PORT:-8787}"
log_path="${LVA_SMOKE_LOG:-/mnt/e/Data/LocalVoiceAgent/runtime/logs/pc-server-integration-smoke.log}"

if [[ ! "${port}" =~ ^[0-9]+$ ]] || (( port < 1024 || port > 65535 )); then
  echo "LVA_SMOKE_PORT must be an unprivileged TCP port" >&2
  exit 2
fi
if [[ ! -x "${server_python}" ]]; then
  echo "PC-server environment is not installed: ${server_python}" >&2
  exit 3
fi
if ss -ltn "sport = :${port}" | grep -q LISTEN; then
  echo "Refusing to use occupied port ${port}" >&2
  exit 4
fi

cd "${app_root}"
export LVA_PAIRING_TOKEN="integration-test-token-with-at-least-32-characters"

"${server_python}" -m uvicorn \
  local_voice_agent_server.api:create_app_from_environment \
  --factory \
  --host "${host}" \
  --port "${port}" \
  >"${log_path}" 2>&1 &
server_pid=$!

cleanup() {
  if kill -0 "${server_pid}" 2>/dev/null; then
    kill -TERM "${server_pid}"
    wait "${server_pid}" || true
  fi
}
trap cleanup EXIT

ready=0
for _ in {1..30}; do
  if curl --fail --silent \
    "http://${host}:${port}/health"; then
    printf '\n'
    ready=1
    break
  fi
  sleep 0.2
done

if [[ "${ready}" != "1" ]]; then
  echo "PC server did not become healthy" >&2
  tail -n 50 "${log_path}" >&2
  exit 5
fi

cleanup
trap - EXIT
echo "pc-server integration smoke passed; stopped pid=${server_pid}"
