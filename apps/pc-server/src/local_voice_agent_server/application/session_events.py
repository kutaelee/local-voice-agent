"""Session event dispatch ports and the voice-input application adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol
from uuid import UUID

from ..domain.audio_stream import AudioStreamError
from ..protocol.client_events import (
    AudioInputChunkPayload,
    AudioInputEndPayload,
    AudioInputStartPayload,
    ClientPayload,
)
from .voice_turn import VoiceEvent, VoiceTurnService


@dataclass(frozen=True, slots=True)
class OutboundEvent:
    type: str
    payload: dict[str, object]


class SessionEventHandler(Protocol):
    async def handle(
        self,
        *,
        session_id: UUID,
        request_id: UUID,
        event_type: str,
        payload: ClientPayload,
    ) -> list[OutboundEvent]: ...

    async def disconnect(self, *, session_id: UUID) -> None: ...


class UnavailableSessionEventHandler:
    async def handle(
        self,
        *,
        session_id: UUID,
        request_id: UUID,
        event_type: str,
        payload: ClientPayload,
    ) -> list[OutboundEvent]:
        del session_id, request_id, event_type, payload
        return [
            OutboundEvent(
                "error",
                {
                    "error_code": "EVENT_HANDLER_UNAVAILABLE",
                    "message": "The session event worker is not configured.",
                    "component": "session_manager",
                    "retryable": True,
                },
            )
        ]

    async def disconnect(self, *, session_id: UUID) -> None:
        del session_id


class VoiceSessionEventHandler:
    """Own one bounded active input turn per authenticated session."""

    def __init__(self, voice_turn_factory: Callable[[], VoiceTurnService]) -> None:
        self._voice_turn_factory = voice_turn_factory
        self._active: dict[UUID, VoiceTurnService] = {}

    async def handle(
        self,
        *,
        session_id: UUID,
        request_id: UUID,
        event_type: str,
        payload: ClientPayload,
    ) -> list[OutboundEvent]:
        del request_id
        try:
            if isinstance(payload, AudioInputStartPayload):
                if session_id in self._active:
                    raise AudioStreamError("an audio stream is already active")
                turn = self._voice_turn_factory()
                self._active[session_id] = turn
                events = turn.start(
                    stream_id=payload.audio_stream_id,
                    encoding=payload.encoding,
                    sample_rate_hz=payload.sample_rate_hz,
                    channels=payload.channels,
                )
                return _outbound(events)

            turn = self._active.get(session_id)
            if turn is None:
                raise AudioStreamError("no audio stream is active")
            if isinstance(payload, AudioInputChunkPayload):
                events = turn.append(
                    stream_id=payload.audio_stream_id,
                    chunk_index=payload.chunk_index,
                    encoding=payload.encoding,
                    data=payload.decoded_data(),
                    duration_ms=payload.duration_ms,
                )
                return _outbound(events)
            if isinstance(payload, AudioInputEndPayload):
                if payload.reason in {"barge_in", "disconnect"}:
                    events = turn.cancel(stream_id=payload.audio_stream_id)
                else:
                    events = await turn.finish(stream_id=payload.audio_stream_id)
                self._active.pop(session_id, None)
                return _outbound(events)
        except (AudioStreamError, ValueError) as error:
            return [
                OutboundEvent(
                    "error",
                    {
                        "error_code": "AUDIO_STREAM_INVALID",
                        "message": str(error),
                        "component": "voice_turn",
                        "retryable": False,
                    },
                )
            ]

        return [
            OutboundEvent(
                "error",
                {
                    "error_code": "EVENT_UNSUPPORTED",
                    "message": "The configured voice handler cannot process this event.",
                    "component": "session_manager",
                    "retryable": False,
                },
            )
        ]

    async def disconnect(self, *, session_id: UUID) -> None:
        turn = self._active.pop(session_id, None)
        if turn is not None:
            turn.cancel_active()


def _outbound(events: list[VoiceEvent]) -> list[OutboundEvent]:
    return [OutboundEvent(event.type, event.payload) for event in events]
