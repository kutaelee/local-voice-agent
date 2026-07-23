#!/usr/bin/env bash
set -euo pipefail

mode="${1:---plan-only}"
download_env="${HOME}/.local/share/local-voice-agent/runtimes/model-download/.venv"
hf_bin="${download_env}/bin/hf"
python_bin="${download_env}/bin/python"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
model_root="/mnt/e/AI/Models/Standalone/LocalVoiceAgent"
cache_root="/mnt/e/Cache/LocalVoiceAgent/huggingface"

models=(
  "google/gemma-4-12B-it-qat-w4a16-ct|1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee|${model_root}/gemma4/12b/target/1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee|model.safetensors|60b6e3989502969d8ae04185d72ecbbc7db63978d5af747a493d53895aa6bfa3|10264229896"
  "google/gemma-4-12B-it-qat-q4_0-unquantized-assistant|18934064dd4c5c6cc3621f6381e7d377fc8cb7bd|${model_root}/gemma4/12b/mtp-assistant/18934064dd4c5c6cc3621f6381e7d377fc8cb7bd|model.safetensors|67f1420cf24aa5065089aaed175223f7c245ccfda16111b6c56765afd7280db6|845719296"
  "google/gemma-4-31B-it-qat-w4a16-ct|52f3f65bc7a02d555763bc923bd1d9094898219d|${model_root}/gemma4/31b/target/52f3f65bc7a02d555763bc923bd1d9094898219d|model.safetensors|1b9b1d622a93f02c0d33f98e502f233b5d707443af6ddc464ed0bf5498506c20|23265352448"
  "google/gemma-4-31B-it-qat-q4_0-unquantized-assistant|96d4c8ca3cb38c107a8478587878124895d1e844|${model_root}/gemma4/31b/mtp-assistant/96d4c8ca3cb38c107a8478587878124895d1e844|model.safetensors|50008e854554a1a9c26317216cd99ae5a3567d4942c9e061398b995cc48c34b9|939042560"
)

required_bytes=36000000000
available_bytes="$(df -B1 --output=avail /mnt/e | tail -1 | tr -d ' ')"

echo "Official source: https://huggingface.co/google"
echo "License: Apache-2.0"
echo "Canonical target: ${model_root}"
echo "Cache: ${cache_root}"
echo "Required download estimate: ${required_bytes} bytes"
echo "Available on E: ${available_bytes} bytes"

if (( available_bytes < required_bytes * 5 )); then
  echo "Refusing: download would violate the 20% operational reserve policy." >&2
  exit 4
fi

for entry in "${models[@]}"; do
  IFS='|' read -r model revision target filename sha bytes <<<"${entry}"
  echo "${model}@${revision}"
  echo "  target=${target}"
  echo "  largest_file=${filename} bytes=${bytes} sha256=${sha}"
done

if [[ "${mode}" == "--plan-only" ]]; then
  echo "Plan only: no network download performed."
  exit 0
fi

if [[ "${mode}" != "--execute" ]]; then
  echo "Refusing unrecognized mode: ${mode}" >&2
  exit 2
fi

[[ -x "${hf_bin}" ]] || {
  echo "Missing ${hf_bin}; run install-wsl.sh --bootstrap-download-tool first." >&2
  exit 5
}

mkdir -p "${cache_root}"
export HF_HOME="${cache_root}"

for entry in "${models[@]}"; do
  IFS='|' read -r model revision target filename expected_sha expected_bytes <<<"${entry}"
  mkdir -p "${target}"

  # Repository metadata is small. The large weight is transferred separately
  # to a stable partial path so interrupted downloads can safely resume.
  "${hf_bin}" download "${model}" \
    --revision "${revision}" \
    --exclude "${filename}" \
    --local-dir "${target}"

  actual_file="${target}/${filename}"
  partial_file="${actual_file}.partial"
  weight_url="https://huggingface.co/${model}/resolve/${revision}/${filename}?download=true"

  if [[ -f "${actual_file}" ]]; then
    actual_bytes="$(stat -c '%s' "${actual_file}")"
    actual_sha="$(sha256sum "${actual_file}" | awk '{print $1}')"
    [[ "${actual_bytes}" == "${expected_bytes}" && "${actual_sha}" == "${expected_sha}" ]] || {
      echo "Refusing to overwrite an existing invalid file: ${actual_file}" >&2
      exit 6
    }
  else
    "${python_bin}" "${script_dir}/download-file.py" \
      "${weight_url}" \
      "${partial_file}" \
      "${expected_bytes}" \
      "${expected_sha}" \
      --workers 8

    actual_bytes="$(stat -c '%s' "${partial_file}")"
    actual_sha="$(sha256sum "${partial_file}" | awk '{print $1}')"
    [[ "${actual_bytes}" == "${expected_bytes}" ]] || {
      echo "Size mismatch for ${partial_file}" >&2
      exit 6
    }
    [[ "${actual_sha}" == "${expected_sha}" ]] || {
      echo "SHA-256 mismatch for ${partial_file}" >&2
      exit 7
    }
    mv -- "${partial_file}" "${actual_file}"
  fi

  [[ "${actual_bytes}" == "${expected_bytes}" ]] || {
    echo "Size mismatch for ${actual_file}" >&2
    exit 6
  }
  [[ "${actual_sha}" == "${expected_sha}" ]] || {
    echo "SHA-256 mismatch for ${actual_file}" >&2
    exit 7
  }
  echo "Validated ${model}@${revision}: ${actual_sha}"
done
