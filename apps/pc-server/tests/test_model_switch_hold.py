from __future__ import annotations

import importlib.util
from pathlib import Path
import wave

import pytest

from local_voice_agent_server.application.model_switch_hold import (
    load_model_switch_hold,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def write_wave(
    path: Path,
    *,
    sample_rate_hz: int = 16_000,
    channels: int = 1,
    sample_width: int = 2,
    frames: int = 1_600,
) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(sample_width)
        output.setframerate(sample_rate_hz)
        output.writeframes(b"\x00" * frames * channels * sample_width)


def test_load_model_switch_hold_and_project_protocol_events(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hold.wav"
    write_wave(path)

    hold = load_model_switch_hold(path)
    events = hold.events()

    assert hold.audio.sample_rate_hz == 16_000
    assert hold.audio.channels == 1
    assert [event.type for event in events] == [
        "assistant.state",
        "audio.output.chunk",
        "audio.output.end",
        "assistant.state",
    ]
    assert events[0].payload["state"] == "speaking"
    assert events[-1].payload == {
        "state": "switching_model",
        "detail": "잠시만요, 확인해 볼게요.",
    }


@pytest.mark.parametrize(
    ("sample_width", "channels"),
    ((1, 1), (2, 3)),
)
def test_load_model_switch_hold_rejects_unsupported_wave_format(
    tmp_path: Path,
    sample_width: int,
    channels: int,
) -> None:
    path = tmp_path / "hold.wav"
    write_wave(path, sample_width=sample_width, channels=channels)

    with pytest.raises(ValueError):
        load_model_switch_hold(path)


def test_load_model_switch_hold_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    link = tmp_path / "hold.wav"
    write_wave(source)
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(ValueError, match="regular file"):
        load_model_switch_hold(link)


def test_warmup_cache_writer_round_trips_through_runtime_loader(
    tmp_path: Path,
) -> None:
    script_path = REPO_ROOT / "scripts" / "warm-qwen3-tts-worker.py"
    spec = importlib.util.spec_from_file_location(
        "warm_qwen3_tts_worker",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    warmup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(warmup)
    path = tmp_path / "hold.wav"

    warmup.write_pcm_wave(
        path,
        pcm_s16le=b"\x01\x00" * 1_600,
        sample_rate_hz=16_000,
        channels=1,
    )

    hold = load_model_switch_hold(path)
    assert hold.audio.pcm_s16le == b"\x01\x00" * 1_600
