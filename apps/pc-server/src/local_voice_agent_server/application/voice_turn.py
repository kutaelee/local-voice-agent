"""One interruptible voice turn composed over STT, conversation, and TTS ports."""

from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from dataclasses import dataclass, field
import inspect
import re
from typing import AsyncIterator, Awaitable, Callable, Protocol
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


VoiceEventEmitter = Callable[[VoiceEvent], Awaitable[None]]


@dataclass(slots=True)
class _AudioOutputState:
    stream_id: UUID = field(default_factory=uuid4)
    output_format: tuple[int, int] | None = None
    chunk_index: int = 0
    started: bool = False


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

    async def cancel_pending_approval(self) -> None:
        cancel = getattr(self._conversation, "cancel_pending_approval", None)
        if cancel is not None:
            result = cancel()
            if inspect.isawaitable(result):
                await result
        self._pending_language = None
        self._pending_approval_id = None

    def cancel_active(self) -> None:
        if self._stream.stream_id is not None:
            try:
                self._stream.cancel(stream_id=self._stream.stream_id)
            except ValueError:
                pass

    async def finish(
        self,
        *,
        stream_id: UUID,
        emit: VoiceEventEmitter | None = None,
    ) -> list[VoiceEvent]:
        audio = self._stream.finish(stream_id=stream_id)
        await self.close_vad(stream_id=stream_id)
        sample_rate_hz = self._stream.sample_rate_hz
        channels = self._stream.channels
        if sample_rate_hz is None or channels is None:
            raise RuntimeError("audio stream metadata is unavailable")

        events: list[VoiceEvent] = []
        await self._deliver(
            events,
            VoiceEvent(
                type="assistant.state",
                payload={"state": "recognizing"},
            ),
            emit=emit,
        )
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
        await self._deliver(
            events,
            VoiceEvent("transcript.user.final", transcript_payload),
            emit=emit,
        )
        await self._deliver(
            events,
            VoiceEvent("assistant.state", {"state": "thinking"}),
            emit=emit,
        )

        stream_response = getattr(self._conversation, "stream", None)
        if emit is not None and callable(stream_response):
            stream = stream_response(
                transcript.text,
                language=transcript.language,
            )
            return await self._complete_streamed_response(
                events,
                stream=stream,
                language=transcript.language,
                emit=emit,
            )

        response_value = await self._conversation.respond(
            transcript.text,
            language=transcript.language,
        )
        if isinstance(response_value, ConversationReply):
            for event in response_value.events:
                await self._deliver(events, event, emit=emit)
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
            emit=emit,
        )

    async def continue_after_approval(
        self,
        *,
        approval_id: UUID,
        approved: bool,
        arguments_digest: str,
        reason: str | None,
        emit: VoiceEventEmitter | None = None,
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
        events: list[VoiceEvent] = []
        for event in reply.events:
            await self._deliver(events, event, emit=emit)
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
            emit=emit,
        )

    async def _complete_response(
        self,
        events: list[VoiceEvent],
        *,
        response: str,
        language: str,
        emit: VoiceEventEmitter | None = None,
    ) -> list[VoiceEvent]:
        await self._deliver(
            events,
            VoiceEvent(
                "assistant.text.final",
                {"text": response, "interrupted": False},
            ),
            emit=emit,
        )
        await self._deliver(
            events,
            VoiceEvent("assistant.state", {"state": "synthesizing"}),
            emit=emit,
        )

        state = _AudioOutputState()
        try:
            for speech_unit in _speech_units(response):
                await self._synthesize_speech_unit(
                    events,
                    state=state,
                    speech_unit=speech_unit,
                    language=language,
                    emit=emit,
                )
        except asyncio.CancelledError:
            await self._close_partial_output(
                state,
                emit=emit,
                reason="cancelled",
            )
            raise
        except Exception:
            await self._close_partial_output(state, emit=emit, reason="error")
            raise
        await self._end_audio_output(
            events,
            state=state,
            reason="completed",
            emit=emit,
        )
        return events

    async def _complete_streamed_response(
        self,
        events: list[VoiceEvent],
        *,
        stream: AsyncIterator[str],
        language: str,
        emit: VoiceEventEmitter,
    ) -> list[VoiceEvent]:
        state = _AudioOutputState()
        response_parts: list[str] = []
        pending_speech = ""
        synthesis_announced = False
        total_characters = 0
        speech_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=8)

        async def synthesize_queued_speech() -> None:
            while True:
                speech_unit = await speech_queue.get()
                try:
                    if speech_unit is None:
                        return
                    await self._synthesize_speech_unit(
                        events,
                        state=state,
                        speech_unit=speech_unit,
                        language=language,
                        emit=emit,
                    )
                finally:
                    speech_queue.task_done()

        synthesis_task = asyncio.create_task(synthesize_queued_speech())
        try:
            async for delta in stream:
                if synthesis_task.done():
                    await synthesis_task
                if not isinstance(delta, str):
                    raise ValueError("conversation stream returned invalid text")
                if not delta:
                    continue
                total_characters += len(delta)
                if total_characters > 2 * 1024 * 1024:
                    raise ValueError("conversation stream is too large")
                response_parts.append(delta)
                pending_speech += delta
                await self._deliver(
                    events,
                    VoiceEvent("assistant.text.delta", {"text": delta}),
                    emit=emit,
                )
                ready, pending_speech = _take_complete_speech_units(
                    pending_speech
                )
                if ready and not synthesis_announced:
                    await self._deliver(
                        events,
                        VoiceEvent(
                            "assistant.state",
                            {"state": "synthesizing"},
                        ),
                        emit=emit,
                    )
                    synthesis_announced = True
                for speech_unit in ready:
                    await speech_queue.put(speech_unit)

            response = "".join(response_parts).strip()
            if not response:
                raise ValueError("conversation stream returned no text")
            await self._deliver(
                events,
                VoiceEvent(
                    "assistant.text.final",
                    {"text": response, "interrupted": False},
                ),
                emit=emit,
            )
            remaining = pending_speech.strip()
            if remaining:
                if not synthesis_announced:
                    await self._deliver(
                        events,
                        VoiceEvent(
                            "assistant.state",
                            {"state": "synthesizing"},
                        ),
                        emit=emit,
                    )
                await speech_queue.put(remaining)
            await speech_queue.put(None)
            await synthesis_task
            await self._end_audio_output(
                events,
                state=state,
                reason="completed",
                emit=emit,
            )
        except asyncio.CancelledError:
            synthesis_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await synthesis_task
            await self._close_partial_output(
                state,
                emit=emit,
                reason="cancelled",
            )
            raise
        except Exception:
            synthesis_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await synthesis_task
            await self._close_partial_output(state, emit=emit, reason="error")
            raise
        return events

    async def _synthesize_speech_unit(
        self,
        events: list[VoiceEvent],
        speech_unit: str,
        *,
        state: _AudioOutputState,
        language: str,
        emit: VoiceEventEmitter | None,
    ) -> None:
        output = await self._tts.synthesize(
            speech_unit,
            language=language,
        )
        current_format = (output.sample_rate_hz, output.channels)
        if state.output_format is None:
            state.output_format = current_format
        elif state.output_format != current_format:
            raise ValueError("TTS output format changed within one response")
        if not state.started:
            await self._deliver(
                events,
                VoiceEvent(
                    "assistant.state",
                    {"state": "speaking"},
                ),
                emit=emit,
            )
            state.started = True
        bytes_per_second = output.sample_rate_hz * output.channels * 2
        for offset in range(
            0,
            len(output.pcm_s16le),
            self._output_chunk_bytes,
        ):
            chunk = output.pcm_s16le[
                offset : offset + self._output_chunk_bytes
            ]
            duration_ms = max(
                1,
                round(len(chunk) * 1_000 / bytes_per_second),
            )
            await self._deliver(
                events,
                VoiceEvent(
                    "audio.output.chunk",
                    {
                        "audio_stream_id": str(state.stream_id),
                        "chunk_index": state.chunk_index,
                        "encoding": "pcm_s16le",
                        "sample_rate_hz": output.sample_rate_hz,
                        "channels": output.channels,
                        "duration_ms": duration_ms,
                        "data_base64": base64.b64encode(chunk).decode("ascii"),
                    },
                ),
                emit=emit,
            )
            state.chunk_index += 1

    async def _end_audio_output(
        self,
        events: list[VoiceEvent],
        *,
        state: _AudioOutputState,
        reason: str,
        emit: VoiceEventEmitter | None,
    ) -> None:
        await self._deliver(
            events,
            VoiceEvent(
                "audio.output.end",
                {
                    "audio_stream_id": str(state.stream_id),
                    "reason": reason,
                },
            ),
            emit=emit,
        )

    async def _close_partial_output(
        self,
        state: _AudioOutputState,
        *,
        emit: VoiceEventEmitter | None,
        reason: str,
    ) -> None:
        if not state.started or emit is None:
            return
        try:
            await emit(
                VoiceEvent(
                    "audio.output.end",
                    {
                        "audio_stream_id": str(state.stream_id),
                        "reason": reason,
                    },
                )
            )
        except Exception:
            pass

    @staticmethod
    async def _deliver(
        events: list[VoiceEvent],
        event: VoiceEvent,
        *,
        emit: VoiceEventEmitter | None,
    ) -> None:
        if emit is None:
            events.append(event)
        else:
            await emit(event)


_HARD_SPEECH_BOUNDARY = re.compile(
    r"(?:(?<=[.!?\u3002\uff01\uff1f])\s+|\n{2,})"
)
_STREAM_SPEECH_BOUNDARY = _HARD_SPEECH_BOUNDARY
_CLAUSE_SPEECH_BOUNDARY = re.compile(r"[,，、;；:：]\s*")
_WORD_SPEECH_BOUNDARY = re.compile(r"\s+")
_MIN_STREAM_UNIT_CHARACTERS = 18
_MAX_STREAM_UNIT_CHARACTERS = 52


def _speech_units(text: str) -> tuple[str, ...]:
    units = tuple(
        part.strip()
        for part in _HARD_SPEECH_BOUNDARY.split(text.strip())
        if part.strip()
    )
    if not units:
        raise ValueError("conversation model returned no speech units")
    return units


def _take_complete_speech_units(text: str) -> tuple[tuple[str, ...], str]:
    units: list[str] = []
    start = 0
    for boundary in _STREAM_SPEECH_BOUNDARY.finditer(text):
        unit = text[start : boundary.start()].strip()
        if unit:
            units.append(unit)
            start = boundary.end()
    pending = text[start:]
    while len(pending.strip()) >= _MAX_STREAM_UNIT_CHARACTERS:
        split_at = None
        for pattern in (_CLAUSE_SPEECH_BOUNDARY, _WORD_SPEECH_BOUNDARY):
            for boundary in pattern.finditer(
                pending,
                _MIN_STREAM_UNIT_CHARACTERS,
                _MAX_STREAM_UNIT_CHARACTERS + 1,
            ):
                split_at = boundary.end()
            if split_at is not None:
                break
        if split_at is None:
            split_at = _MAX_STREAM_UNIT_CHARACTERS
        unit = pending[:split_at].strip()
        if unit:
            units.append(unit)
        pending = pending[split_at:]
    return tuple(units), pending
