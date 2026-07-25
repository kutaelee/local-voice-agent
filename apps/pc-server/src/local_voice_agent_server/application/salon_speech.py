"""Optional TTS projection for text-first salon assistant messages."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import uuid4

from .salon_calls import SalonEvent
from .voice_turn import (
    TextToSpeechPort,
    _finish_pcm16_speech_unit,
    _prepare_tts_text,
    _speech_units,
    _take_complete_speech_units,
)

_MAX_SINGLE_SALON_TTS_CHARACTERS = 72


class SalonSpeechService:
    def __init__(
        self,
        *,
        tts: TextToSpeechPort,
        output_chunk_bytes: int = 32 * 1024,
        release_fade_ms: int = 24,
        unit_silence_ms: int = 80,
        final_silence_ms: int = 200,
    ) -> None:
        if not 1 <= output_chunk_bytes <= 384 * 1024:
            raise ValueError("salon TTS output chunk size is invalid")
        if not 0 <= release_fade_ms <= 100:
            raise ValueError("salon TTS release fade is invalid")
        if not 0 <= unit_silence_ms <= 300:
            raise ValueError("salon TTS unit silence is invalid")
        if not 0 <= final_silence_ms <= 300:
            raise ValueError("salon TTS final silence is invalid")
        self._tts = tts
        self._output_chunk_bytes = output_chunk_bytes
        self._release_fade_ms = release_fade_ms
        self._unit_silence_ms = unit_silence_ms
        self._final_silence_ms = final_silence_ms

    async def synthesize(
        self,
        text: str,
        *,
        resume_state: Literal["listening", "idle"] = "listening",
        emit: Callable[[SalonEvent], Awaitable[None]] | None = None,
    ) -> tuple[SalonEvent, ...]:
        normalized = " ".join(text.strip().split())
        if not normalized or len(normalized) > 2_000:
            raise ValueError("salon TTS text is invalid")
        spoken_characters = len("".join(normalized.split()))
        if spoken_characters <= _MAX_SINGLE_SALON_TTS_CHARACTERS:
            # A normal one- or two-sentence receptionist reply should share one
            # acoustic generation. Splitting it exposes Qwen's per-generation
            # EOS and creates a synthetic pause plus a new attack at the next
            # sentence, which sounds like clipped Korean 요/다 endings.
            speech_units = (normalized,)
        else:
            ready, pending = _take_complete_speech_units(normalized)
            speech_units = tuple(
                [
                    *ready,
                    *([pending.strip()] if pending.strip() else []),
                ]
            )
            if not speech_units:
                speech_units = _speech_units(normalized)
        stream_id = uuid4()
        events: list[SalonEvent] = []

        async def publish(event: SalonEvent) -> None:
            events.append(event)
            if emit is not None:
                await emit(event)

        await publish(SalonEvent("assistant.state", {"state": "synthesizing"}))
        chunk_index = 0
        speaking = False
        try:
            for unit_index, speech_unit in enumerate(speech_units):
                output = await self._tts.synthesize(
                    _prepare_tts_text(speech_unit),
                    language="ko",
                )
                if (
                    output.sample_rate_hz < 8_000
                    or output.sample_rate_hz > 192_000
                    or output.channels not in {1, 2}
                ):
                    raise ValueError("salon TTS output format is invalid")
                if not speaking:
                    await publish(SalonEvent("assistant.state", {"state": "speaking"}))
                    speaking = True
                pcm = _finish_pcm16_speech_unit(
                    output.pcm_s16le,
                    sample_rate_hz=output.sample_rate_hz,
                    channels=output.channels,
                    release_fade_ms=self._release_fade_ms,
                    silence_ms=(
                        self._final_silence_ms
                        if unit_index == len(speech_units) - 1
                        else self._unit_silence_ms
                    ),
                )
                bytes_per_second = output.sample_rate_hz * output.channels * 2
                for offset in range(0, len(pcm), self._output_chunk_bytes):
                    chunk = pcm[offset : offset + self._output_chunk_bytes]
                    await publish(
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
                    chunk_index += 1
        except Exception:
            await publish(
                SalonEvent(
                    "audio.output.end",
                    {
                        "audio_stream_id": str(stream_id),
                        "reason": "failed",
                    },
                )
            )
            await publish(SalonEvent("assistant.state", {"state": resume_state}))
            raise
        await publish(
            SalonEvent(
                "audio.output.end",
                {
                    "audio_stream_id": str(stream_id),
                    "reason": "completed",
                },
            )
        )
        await publish(SalonEvent("assistant.state", {"state": resume_state}))
        return tuple(events)
