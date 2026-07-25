"""Pre-rendered speech used to cover an interactive model escalation."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
import wave
from uuid import uuid4

from .voice_turn import SynthesizedAudio, VoiceEvent


DEFAULT_MODEL_SWITCH_HOLD_TEXT = "잠시만요, 확인해 볼게요."
_MAX_WAVE_BYTES = 2 * 1024 * 1024
_MAX_DURATION_MS = 10_000
_MIN_DURATION_MS = 100


@dataclass(frozen=True, slots=True)
class ModelSwitchHold:
    audio: SynthesizedAudio
    text: str = DEFAULT_MODEL_SWITCH_HOLD_TEXT
    output_chunk_bytes: int = 32 * 1024

    def events(self) -> tuple[VoiceEvent, ...]:
        if not 1 <= self.output_chunk_bytes <= 384 * 1024:
            raise ValueError("model-switch hold chunk size is invalid")
        stream_id = uuid4()
        bytes_per_second = (
            self.audio.sample_rate_hz * self.audio.channels * 2
        )
        events = [
            VoiceEvent(
                "assistant.state",
                {
                    "state": "speaking",
                    "detail": "model_switch_hold",
                },
            )
        ]
        for chunk_index, offset in enumerate(
            range(0, len(self.audio.pcm_s16le), self.output_chunk_bytes)
        ):
            chunk = self.audio.pcm_s16le[
                offset : offset + self.output_chunk_bytes
            ]
            events.append(
                VoiceEvent(
                    "audio.output.chunk",
                    {
                        "audio_stream_id": str(stream_id),
                        "chunk_index": chunk_index,
                        "encoding": "pcm_s16le",
                        "sample_rate_hz": self.audio.sample_rate_hz,
                        "channels": self.audio.channels,
                        "duration_ms": max(
                            1,
                            round(len(chunk) * 1_000 / bytes_per_second),
                        ),
                        "data_base64": base64.b64encode(chunk).decode("ascii"),
                    },
                )
            )
        events.extend(
            (
                VoiceEvent(
                    "audio.output.end",
                    {
                        "audio_stream_id": str(stream_id),
                        "reason": "completed",
                    },
                ),
                VoiceEvent(
                    "assistant.state",
                    {
                        "state": "switching_model",
                        "detail": self.text,
                    },
                ),
            )
        )
        return tuple(events)


def load_model_switch_hold(path: Path) -> ModelSwitchHold:
    """Load a small, trusted PCM16 WAV without following a file symlink."""

    if not path.is_absolute():
        raise ValueError("model-switch hold audio path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise ValueError("model-switch hold audio must be a regular file")
    if path.stat().st_size > _MAX_WAVE_BYTES:
        raise ValueError("model-switch hold audio is too large")

    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_rate_hz = source.getframerate()
            sample_width = source.getsampwidth()
            frame_count = source.getnframes()
            compression = source.getcomptype()
            pcm_s16le = source.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as error:
        raise ValueError("model-switch hold audio is not a valid WAV") from error

    if channels not in {1, 2}:
        raise ValueError("model-switch hold audio channels are invalid")
    if not 8_000 <= sample_rate_hz <= 192_000:
        raise ValueError("model-switch hold sample rate is invalid")
    if sample_width != 2 or compression != "NONE":
        raise ValueError("model-switch hold audio must be PCM16")
    if len(pcm_s16le) != frame_count * channels * sample_width:
        raise ValueError("model-switch hold audio is truncated")
    duration_ms = round(frame_count * 1_000 / sample_rate_hz)
    if not _MIN_DURATION_MS <= duration_ms <= _MAX_DURATION_MS:
        raise ValueError("model-switch hold audio duration is invalid")

    return ModelSwitchHold(
        audio=SynthesizedAudio(
            pcm_s16le=pcm_s16le,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )
    )
