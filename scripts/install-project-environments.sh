#!/usr/bin/env bash
set -euo pipefail

repo="/mnt/c/Dev/Repos/local-voice-agent"
pc_environment="${HOME}/.local/share/local-voice-agent/runtimes/pc-server/.venv"
tls_environment="${HOME}/.local/share/local-voice-agent/runtimes/tls-tools-49.0.0/.venv"
tls_lock="${repo}/scripts/requirements/tls-tools.lock"

[[ -d "${repo}/.git" && -f "${tls_lock}" ]] || {
  echo "Canonical repository or TLS lock file is unavailable." >&2
  exit 3
}

uv_bin="$(command -v uv || true)"
if [[ -z "${uv_bin}" && -x "${HOME}/.local/bin/uv" ]]; then
  uv_bin="${HOME}/.local/bin/uv"
fi
[[ -n "${uv_bin}" ]] || {
  echo "uv is unavailable inside Ubuntu." >&2
  exit 4
}

cd "${repo}"
UV_PROJECT_ENVIRONMENT="${pc_environment}" \
  "${uv_bin}" sync \
    --project apps/pc-server \
    --locked \
    --extra test \
    --extra persistence

if [[ ! -x "${tls_environment}/bin/python" ]]; then
  "${uv_bin}" venv --python 3.12 "${tls_environment}"
fi
"${uv_bin}" pip sync \
  --python "${tls_environment}/bin/python" \
  --require-hashes \
  "${tls_lock}"

echo "wsl_project_environments=installed_and_locked"
