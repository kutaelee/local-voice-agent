"""One interruptible voice turn composed over STT, conversation, and TTS ports."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from ..domain.audio_stream import AudioStream


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class SynthesizedAudio:
    pcm_s16le: bytes
    sample_rate_hz: int
    channels: int = 1


@dataclass(frozen=True, slots=True)
class VoiceEvent:
    type: str
    payload: dict[str, object]


class SpeechToTextPort(Protocol):
    async def transcribe(
        self,
        audio: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
    ) -> Transcript: ...


class ConversationPort(Protocol):
    async def respond(self, text: str, *, language: str) -> str: ...


class TextToSpeechPort(Protocol):
    async def synthesize(self, text: str, *, language: str) -> SynthesizedAudio: ...


class VoiceTurnService:
    def __init__(
        self,
        *,
        stt: SpeechToTextPort,
        conversation: ConversationPort,
        tts: TextToSpeechPort,
        max_input_bytes: int = 8 * 1024 * 1024,
        output_chunk_bytes: int = 32 * 1024,
    ) -> None:
        if output_chunk_bytes < 1 or output_chunk_bytes > 384 * 1024:
            raise ValueError("output chunk size is invalid")
        self._stream = AudioStream(max_bytes=max_input_bytes)
        self._stt = stt
        self._conversation = conversation
        self._tts = tts
        self._output_chunk_bytes = output_chunk_bytes

    def start(
        self,
        *,
        stream_id: UUID,
        encoding: str,
        sample_rate_hz: int,
        channels: int,
    ) -> list[VoiceEvent]:
        self._stream.start(
            stream_id=stream_id,
            encoding=encoding,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )
        return [
            VoiceEvent(
                type="assistant.state",
                payload={"state": "listening"},
            )
        ]

    def append(
        self,
        *,
        stream_id: UUID,
        chunk_index: int,
        data: bytes,
        duration_ms: int,
    ) -> list[VoiceEvent]:
        self._stream.append(
            stream_id=stream_id,
            chunk_index=chunk_index,
            data=data,
            duration_ms=duration_ms,
        )
        return []

    async def finish(self, *, stream_id: UUID) -> list[VoiceEvent]:
        audio = self._stream.finish(stream_id=stream_id)
        sample_rate_hz = self._stream.sample_rate_hz
        channels = self._stream.channels
        if sample_rate_hz is None or channels is None:
            raise RuntimeError("audio stream metadata is unavailable")

        events = [
            VoiceEvent(
                type="assistant.state",
                payload={"state": "recognizing"},
            )
        ]
        transcript = await self._stt.transcribe(
            audio,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )
        if not transcript.text.strip():
            raise ValueError("speech recognition returned no text")
        transcript_payload: dict[str, object] = {
            "text": transcript.text,
            "language": transcript.language,
            "audio_stream_id": str(stream_id),
        }
        if transcript.confidence is not None:
            transcript_payload["confidence"] = transcript.confidence
        events.extend(
            [
                VoiceEvent("transcript.user.final", transcript_payload),
                VoiceEvent("assistant.state", {"state": "thinking"}),
            ]
        )

        response = await self._conversation.respond(
            transcript.text,
            language=transcript.language,
        )
        if not response.strip():
            raise ValueError("conversation model returned no text")
        events.extend(
            [
                VoiceEvent(
                    "assistant.text.final",
                    {"text": response, "interrupted": False},
                ),
                VoiceEvent("assistant.state", {"state": "synthesizing"}),
            ]
        )

        output = await self._tts.synthesize(
            response,
            language=transcript.language,
        )
        output_stream_id = uuid4()
        events.append(VoiceEvent("assistant.state", {"state": "speaking"}))
        bytes_per_second = output.sample_rate_hz * output.channels * 2
        for chunk_index, offset in enumerate(
            range(0, len(output.pcm_s16le), self._output_chunk_bytes)
        ):
            chunk = output.pcm_s16le[
                offset : offset + self._output_chunk_bytes
            ]
            duration_ms = max(1, round(len(chunk) * 1_000 / bytes_per_second))
            events.append(
                VoiceEvent(
                    "audio.output.chunk",
                    {
                        "audio_stream_id": str(output_stream_id),
                        "chunk_index": chunk_index,
                        "encoding": "pcm_s16le",
                        "sample_rate_hz": output.sample_rate_hz,
                        "channels": output.channels,
                        "duration_ms": duration_ms,
                        "data_base64": base64.b64encode(chunk).decode("ascii"),
                    },
                )
            )
        events.append(
            VoiceEvent(
                "audio.output.end",
                {
                    "audio_stream_id": str(output_stream_id),
                    "reason": "completed",
                },
            )
        )
        return events
