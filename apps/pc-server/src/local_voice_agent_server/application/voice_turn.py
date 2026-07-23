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


@dataclass(frozen=True, slots=True)
class ConversationReply:
    text: str | None
    events: tuple[VoiceEvent, ...] = ()
    pending_approval_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class VoiceActivityDecision:
    speech_started: bool
    end_of_speech: bool
    probability: float
    processed_ms: int


class SpeechToTextPort(Protocol):
    async def transcribe(
        self,
        audio: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
    ) -> Transcript: ...


class ConversationPort(Protocol):
    async def respond(
        self,
        text: str,
        *,
        language: str,
    ) -> str | ConversationReply: ...

    async def decide_approval(
        self,
        *,
        approval_id: UUID,
        approved: bool,
        arguments_digest: str,
        reason: str | None,
    ) -> ConversationReply: ...


class TextToSpeechPort(Protocol):
    async def synthesize(self, text: str, *, language: str) -> SynthesizedAudio: ...


class VoiceActivityPort(Protocol):
    async def analyze(
        self,
        *,
        stream_id: UUID,
        pcm_s16le: bytes,
        sample_rate_hz: int,
        channels: int,
    ) -> VoiceActivityDecision: ...

    async def close(self, *, stream_id: UUID) -> None: ...


class VoiceTurnService:
    def __init__(
        self,
        *,
        stt: SpeechToTextPort,
        conversation: ConversationPort,
        tts: TextToSpeechPort,
        vad: VoiceActivityPort | None = None,
        max_input_bytes: int = 8 * 1024 * 1024,
        output_chunk_bytes: int = 32 * 1024,
    ) -> None:
        if output_chunk_bytes < 1 or output_chunk_bytes > 384 * 1024:
            raise ValueError("output chunk size is invalid")
        self._stream = AudioStream(max_bytes=max_input_bytes)
        self._stt = stt
        self._conversation = conversation
        self._tts = tts
        self._vad = vad
        self._output_chunk_bytes = output_chunk_bytes
        self._pending_language: str | None = None
        self._pending_approval_id: UUID | None = None

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
        encoding: str,
        data: bytes,
        duration_ms: int,
    ) -> list[VoiceEvent]:
        if encoding != self._stream.encoding:
            raise ValueError("audio chunk encoding does not match the stream")
        self._stream.append(
            stream_id=stream_id,
            chunk_index=chunk_index,
            data=data,
            duration_ms=duration_ms,
        )
        return []

    async def append_with_vad(
        self,
        *,
        stream_id: UUID,
        chunk_index: int,
        encoding: str,
        data: bytes,
        duration_ms: int,
    ) -> list[VoiceEvent]:
        self.append(
            stream_id=stream_id,
            chunk_index=chunk_index,
            encoding=encoding,
            data=data,
            duration_ms=duration_ms,
        )
        if self._vad is None:
            return []
        sample_rate_hz = self._stream.sample_rate_hz
        channels = self._stream.channels
        if sample_rate_hz is None or channels is None:
            raise RuntimeError("audio stream metadata is unavailable")
        decision = await self._vad.analyze(
            stream_id=stream_id,
            pcm_s16le=data,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )
        if not decision.end_of_speech:
            return []
        return [
            VoiceEvent(
                "assistant.state",
                {
                    "state": "recognizing",
                    "detail": "vad_end_detected",
                },
            )
        ]

    def cancel(self, *, stream_id: UUID) -> list[VoiceEvent]:
        self._stream.cancel(stream_id=stream_id)
        return [VoiceEvent("assistant.state", {"state": "interrupted"})]

    async def close_vad(self, *, stream_id: UUID) -> None:
        if self._vad is not None:
            await self._vad.close(stream_id=stream_id)

    @property
    def stream_id(self) -> UUID | None:
        return self._stream.stream_id

    @property
    def pending_approval_id(self) -> UUID | None:
        return self._pending_approval_id

    def cancel_pending_approval(self) -> None:
        self._pending_language = None
        self._pending_approval_id = None

    def cancel_active(self) -> None:
        if self._stream.stream_id is not None:
            try:
                self._stream.cancel(stream_id=self._stream.stream_id)
            except ValueError:
                pass

    async def finish(self, *, stream_id: UUID) -> list[VoiceEvent]:
        audio = self._stream.finish(stream_id=stream_id)
        await self.close_vad(stream_id=stream_id)
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

        response_value = await self._conversation.respond(
            transcript.text,
            language=transcript.language,
        )
        if isinstance(response_value, ConversationReply):
            events.extend(response_value.events)
            if response_value.text is None:
                if response_value.pending_approval_id is None:
                    raise ValueError(
                        "conversation returned neither text nor approval"
                    )
                self._pending_language = transcript.language
                self._pending_approval_id = (
                    response_value.pending_approval_id
                )
                return events
            response = response_value.text
        else:
            response = response_value
        if not response.strip():
            raise ValueError("conversation model returned no text")
        return await self._complete_response(
            events,
            response=response,
            language=transcript.language,
        )

    async def continue_after_approval(
        self,
        *,
        approval_id: UUID,
        approved: bool,
        arguments_digest: str,
        reason: str | None,
    ) -> list[VoiceEvent]:
        if (
            self._pending_language is None
            or self._pending_approval_id != approval_id
        ):
            raise ValueError("approval does not match the pending voice turn")
        decide = getattr(self._conversation, "decide_approval", None)
        if decide is None:
            raise ValueError("conversation does not support approval")
        reply = await decide(
            approval_id=approval_id,
            approved=approved,
            arguments_digest=arguments_digest,
            reason=reason,
        )
        events = list(reply.events)
        if reply.text is None:
            if reply.pending_approval_id is None:
                raise ValueError(
                    "conversation returned neither text nor approval"
                )
            self._pending_approval_id = reply.pending_approval_id
            return events
        language = self._pending_language
        self._pending_language = None
        self._pending_approval_id = None
        return await self._complete_response(
            events,
            response=reply.text,
            language=language,
        )

    async def _complete_response(
        self,
        events: list[VoiceEvent],
        *,
        response: str,
        language: str,
    ) -> list[VoiceEvent]:
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
            language=language,
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
