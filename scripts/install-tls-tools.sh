#!/usr/bin/env bash
set -euo pipefail

runtime_root="${HOME}/.local/share/local-voice-agent/runtimes/tls-tools-49.0.0"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
lock_file="${repo_root}/scripts/requirements/tls-tools.lock"

uv_bin="$(command -v uv || true)"
if [[ -z "${uv_bin}" && -x "${HOME}/.local/bin/uv" ]]; then
  uv_bin="${HOME}/.local/bin/uv"
fi
[[ -n "${uv_bin}" ]] || {
  echo "uv is required and was not found." >&2
  exit 3
}
[[ -f "${lock_file}" ]] || {
  echo "TLS tools lock file is unavailable: ${lock_file}" >&2
  exit 4
}

if [[ ! -x "${runtime_root}/.venv/bin/python" ]]; then
  mkdir -p "${runtime_root}"
  "${uv_bin}" venv --python 3.12 "${runtime_root}/.venv"
fi

"${uv_bin}" pip sync \
  --python "${runtime_root}/.venv/bin/python" \
  --require-hashes \
  "${lock_file}"
"${uv_bin}" pip check --python "${runtime_root}/.venv/bin/python"
"${runtime_root}/.venv/bin/python" -c \
  'import cryptography; assert cryptography.__version__ == "49.0.0"; print(cryptography.__version__)'
