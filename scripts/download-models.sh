#!/usr/bin/env bash
set -euo pipefail

mode="${1:---plan-only}"
download_env="${HOME}/.local/share/local-voice-agent/runtimes/model-download/.venv"
hf_bin="${download_env}/bin/hf"
python_bin="${download_env}/bin/python"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
model_root="/mnt/e/AI/Models/Standalone/LocalVoiceAgent"
cache_root="/mnt/e/Cache/LocalVoiceAgent/huggingface"
state_root="/mnt/e/Cache/LocalVoiceAgent/download-state"
download_workers="${MODEL_DOWNLOAD_WORKERS:-16}"
download_only="${MODEL_DOWNLOAD_ONLY:-}"

case "${download_only}" in
  ""|default_target_12b|mtp_assistant_12b|mtp_target_12b|escalation_target_31b|mtp_assistant_31b|mtp_target_31b|stt_large_v3_turbo|stt_small|tts_chatterbox_v3)
    ;;
  *)
    echo "Unknown MODEL_DOWNLOAD_ONLY role: ${download_only}" >&2
    exit 8
    ;;
esac

models=(
  "default_target_12b|google/gemma-4-12B-it-qat-w4a16-ct|1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee|${model_root}/gemma4/12b/target/1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee|model.safetensors|60b6e3989502969d8ae04185d72ecbbc7db63978d5af747a493d53895aa6bfa3|10264229896|Apache-2.0"
  "mtp_assistant_12b|google/gemma-4-12B-it-qat-q4_0-unquantized-assistant|18934064dd4c5c6cc3621f6381e7d377fc8cb7bd|${model_root}/gemma4/12b/mtp-assistant/18934064dd4c5c6cc3621f6381e7d377fc8cb7bd|model.safetensors|67f1420cf24aa5065089aaed175223f7c245ccfda16111b6c56765afd7280db6|845719296|Apache-2.0"
  "mtp_target_12b|google/gemma-4-12B-it-qat-q4_0-unquantized|b6ed86275a6a5735884e208bfed95b445a684ca2|${model_root}/gemma4/12b/mtp-target/b6ed86275a6a5735884e208bfed95b445a684ca2|model.safetensors|26f2cee4292298a3f9f92209643c37c80e34e011381e22434088870d9439a0a0|23919549408|Apache-2.0"
  "escalation_target_31b|google/gemma-4-31B-it-qat-w4a16-ct|52f3f65bc7a02d555763bc923bd1d9094898219d|${model_root}/gemma4/31b/target/52f3f65bc7a02d555763bc923bd1d9094898219d|model.safetensors|1b9b1d622a93f02c0d33f98e502f233b5d707443af6ddc464ed0bf5498506c20|23265352448|Apache-2.0"
  "mtp_assistant_31b|google/gemma-4-31B-it-qat-q4_0-unquantized-assistant|96d4c8ca3cb38c107a8478587878124895d1e844|${model_root}/gemma4/31b/mtp-assistant/96d4c8ca3cb38c107a8478587878124895d1e844|model.safetensors|50008e854554a1a9c26317216cd99ae5a3567d4942c9e061398b995cc48c34b9|939042560|Apache-2.0"
  "mtp_target_31b|google/gemma-4-31B-it-qat-q4_0-unquantized|1e4d8beecacb8b7590c1d8bedd7335f687bf311f|${model_root}/gemma4/31b/mtp-target/1e4d8beecacb8b7590c1d8bedd7335f687bf311f|model-00001-of-00002.safetensors|8ad3c67895dca6184c70d88a31f042eca42971728782dfb2c18edb736f3060a0|49784788364|Apache-2.0"
  "mtp_target_31b|google/gemma-4-31B-it-qat-q4_0-unquantized|1e4d8beecacb8b7590c1d8bedd7335f687bf311f|${model_root}/gemma4/31b/mtp-target/1e4d8beecacb8b7590c1d8bedd7335f687bf311f|model-00002-of-00002.safetensors|a373e71426e369a2498a7a69793ce9ccdb07d2c96aa807c6baf675520f9add87|12761549884|Apache-2.0"
  "stt_large_v3_turbo|mobiuslabsgmbh/faster-whisper-large-v3-turbo|0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf|${model_root}/stt/faster-whisper-large-v3-turbo/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf|model.bin|e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da|1617884929|MIT"
  "stt_small|Systran/faster-whisper-small|536b0662742c02347bc0e980a01041f333bce120|${model_root}/stt/faster-whisper-small/536b0662742c02347bc0e980a01041f333bce120|model.bin|3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671|483546902|MIT"
  "tts_chatterbox_v3|ResembleAI/chatterbox|5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18|${model_root}/tts/chatterbox-multilingual-v3/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18|t3_mtl23ls_v3.safetensors|5abca8321ede76f8e61f1cc0d19aea6c946b28871017ce8726f8a69203f05953|2143989928|MIT"
  "tts_chatterbox_v3|ResembleAI/chatterbox|5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18|${model_root}/tts/chatterbox-multilingual-v3/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18|s3gen.pt|9b9ff07e60b20c136e2b1b3d7563a24604e8d2c4c267888d1ee929dd0151d2a3|1057165844|MIT"
  "tts_chatterbox_v3|ResembleAI/chatterbox|5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18|${model_root}/tts/chatterbox-multilingual-v3/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18|ve.pt|4b16d836bc598509860f6fa068165a8bb5e9ac84f05582dfcf278a5a372879f1|5698626|MIT"
)

[[ "${download_workers}" =~ ^([1-9]|1[0-6])$ ]] || {
  echo "MODEL_DOWNLOAD_WORKERS must be an integer from 1 to 16." >&2
  exit 3
}

selected_weight_bytes=0
selected_file_count=0
for entry in "${models[@]}"; do
  IFS='|' read -r role _model _revision _target _filename _sha bytes _license <<<"${entry}"
  [[ -z "${download_only}" || "${download_only}" == "${role}" ]] || continue
  selected_weight_bytes=$((selected_weight_bytes + bytes))
  selected_file_count=$((selected_file_count + 1))
done

metadata_headroom_bytes=1073741824
required_bytes=$((selected_weight_bytes + metadata_headroom_bytes))
read -r volume_bytes available_bytes < <(
  df -B1 --output=size,avail /mnt/e | tail -1 | xargs
)
reserve_bytes=$((volume_bytes / 5))
projected_available_bytes=$((available_bytes - required_bytes))

if (( projected_available_bytes < reserve_bytes )); then
  echo "Refusing: projected free space would cross the 20% reserve." >&2
  exit 4
fi

echo "Official sources and licenses: pinned per selected entry"
echo "Canonical target: ${model_root}"
echo "Cache: ${cache_root}"
echo "Parallel range workers: ${download_workers}"
echo "Selected weight files: ${selected_file_count}"
echo "Selected weight bytes: ${selected_weight_bytes}"
echo "Metadata headroom: ${metadata_headroom_bytes} bytes"
echo "Available on E: ${available_bytes} bytes"
echo "Projected available on E: ${projected_available_bytes} bytes"
echo "Required 20% reserve on E: ${reserve_bytes} bytes"

for entry in "${models[@]}"; do
  IFS='|' read -r role model revision target filename sha bytes license <<<"${entry}"
  [[ -z "${download_only}" || "${download_only}" == "${role}" ]] || continue
  echo "${role}: ${model}@${revision}"
  echo "  license=${license}"
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
mkdir -p "${state_root}"
export HF_HOME="${cache_root}"

for entry in "${models[@]}"; do
  IFS='|' read -r role model revision target filename expected_sha expected_bytes _license <<<"${entry}"
  [[ -z "${download_only}" || "${download_only}" == "${role}" ]] || continue
  mkdir -p "${target}"

  # Repository metadata is small. The large weight is transferred separately
  # to a stable partial path so interrupted downloads can safely resume.
  "${hf_bin}" download "${model}" \
    --revision "${revision}" \
    --exclude "*.safetensors" \
    --exclude "*.bin" \
    --exclude "*.pt" \
    --local-dir "${target}"

  actual_file="${target}/${filename}"
  partial_file="${actual_file}.partial"
  state_file="${state_root}/${model//\//--}-${revision}-${filename}.ranges.json"
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
      --state-file "${state_file}" \
      --workers "${download_workers}"

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
