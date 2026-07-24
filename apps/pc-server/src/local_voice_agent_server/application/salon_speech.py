"""Optional TTS projection for text-first salon assistant messages."""

from __future__ import annotations

import base64
from typing import Literal
from uuid import uuid4

from .salon_calls import SalonEvent
from .voice_turn import TextToSpeechPort, _finish_pcm16_speech_unit


class SalonSpeechService:
    def __init__(
        self,
        *,
        tts: TextToSpeechPort,
        output_chunk_bytes: int = 32 * 1024,
        release_fade_ms: int = 24,
        final_silence_ms: int = 200,
    ) -> None:
        if not 1 <= output_chunk_bytes <= 384 * 1024:
            raise ValueError("salon TTS output chunk size is invalid")
        if not 0 <= release_fade_ms <= 100:
            raise ValueError("salon TTS release fade is invalid")
        if not 0 <= final_silence_ms <= 300:
            raise ValueError("salon TTS final silence is invalid")
        self._tts = tts
        self._output_chunk_bytes = output_chunk_bytes
        self._release_fade_ms = release_fade_ms
        self._final_silence_ms = final_silence_ms

    async def synthesize(
        self,
        text: str,
        *,
        resume_state: Literal["listening", "idle"] = "listening",
    ) -> tuple[SalonEvent, ...]:
        normalized = " ".join(text.strip().split())
        if not normalized or len(normalized) > 2_000:
            raise ValueError("salon TTS text is invalid")
        output = await self._tts.synthesize(normalized, language="ko")
        if (
            output.sample_rate_hz < 8_000
            or output.sample_rate_hz > 192_000
            or output.channels not in {1, 2}
        ):
            raise ValueError("salon TTS output format is invalid")
        pcm = _finish_pcm16_speech_unit(
            output.pcm_s16le,
            sample_rate_hz=output.sample_rate_hz,
            channels=output.channels,
            release_fade_ms=self._release_fade_ms,
            silence_ms=self._final_silence_ms,
        )
        stream_id = uuid4()
        bytes_per_second = output.sample_rate_hz * output.channels * 2
        events = [
            SalonEvent("assistant.state", {"state": "speaking"}),
        ]
        for chunk_index, offset in enumerate(
            range(0, len(pcm), self._output_chunk_bytes)
        ):
            chunk = pcm[offset : offset + self._output_chunk_bytes]
            events.append(
                SalonEvent(
                    "audio.output.chunk",
                    {
                        "audio_stream_id": str(stream_id),
                        "chunk_index": chunk_index,
                        "encoding": "pcm_s16le",
                        "sample_rate_hz": output.sample_rate_hz,
                        "channels": output.channels,
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
                SalonEvent(
                    "audio.output.end",
                    {
                        "audio_stream_id": str(stream_id),
                        "reason": "completed",
                    },
                ),
                SalonEvent("assistant.state", {"state": resume_state}),
            )
        )
        return tuple(events)
