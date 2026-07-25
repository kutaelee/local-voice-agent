from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_stop_audio_workers_cleans_only_owned_runtime_paths() -> None:
    source = (ROOT / "scripts" / "stop-audio-workers.sh").read_text(
        encoding="utf-8"
    )

    assert 'run_root="/home/kutae/.local/share/local-voice-agent/run"' in source
    assert '[[ -f "${pid_file}" && ! -L "${pid_file}" ]]' in source
    assert '[[ -S "${socket_file}" && ! -L "${socket_file}" ]]' in source
    assert 'command="$(tr \'\\0\' \' \' <"/proc/${pid}/cmdline")"' in source
    assert '[[ "${command}" == *"${expected}"* ]]' in source
    assert 'rm -f -- "${pid_file}"' in source
    assert 'rm -f -- "${socket_file}"' in source
    assert "stop_owned stt" in source
    assert "stop_owned tts" in source
    assert "stop_owned vad" in source
