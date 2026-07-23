"""Session event dispatch ports and the voice-input application adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol
from uuid import UUID

from ..domain.audio_stream import AudioStreamError
from ..protocol.client_events import (
    AudioInputChunkPayload,
    AudioInputEndPayload,
    AudioInputStartPayload,
    ApprovalResponsePayload,
    ClientPayload,
    OperationCancelPayload,
)
from .model_switch import ModelActivityBarrier
from .voice_turn import VoiceEvent, VoiceTurnService


@dataclass(frozen=True, slots=True)
class OutboundEvent:
    type: str
    payload: dict[str, object]


OutboundEmitter = Callable[[OutboundEvent], Awaitable[None]]


class SessionEventHandler(Protocol):
    async def handle(
        self,
        *,
        session_id: UUID,
        request_id: UUID,
        event_type: str,
        payload: ClientPayload,
        emit: OutboundEmitter | None = None,
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
        emit: OutboundEmitter | None = None,
    ) -> list[OutboundEvent]:
        del session_id, request_id, event_type, payload, emit
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

    def __init__(
        self,
        voice_turn_factory: Callable[[UUID, UUID], VoiceTurnService],
        *,
        model_activity_barrier: ModelActivityBarrier | None = None,
    ) -> None:
        self._voice_turn_factory = voice_turn_factory
        self._model_activity_barrier = model_activity_barrier
        self._usage_sessions: set[UUID] = set()
        self._active: dict[UUID, VoiceTurnService] = {}
        self._processing: dict[
            UUID,
            tuple[UUID, VoiceTurnService, asyncio.Task[object]],
        ] = {}
        self._pending_approval: dict[
            UUID,
            tuple[UUID, VoiceTurnService],
        ] = {}
        self._cancel_results: dict[
            tuple[UUID, UUID],
            list[OutboundEvent],
        ] = {}

    async def handle(
        self,
        *,
        session_id: UUID,
        request_id: UUID,
        event_type: str,
        payload: ClientPayload,
        emit: OutboundEmitter | None = None,
    ) -> list[OutboundEvent]:
        del event_type
        try:
            if isinstance(payload, AudioInputStartPayload):
                if (
                    session_id in self._active
                    or session_id in self._processing
                    or session_id in self._pending_approval
                ):
                    raise AudioStreamError(
                        "an audio stream or response is already active"
                    )
                await self._acquire_usage(session_id)
                try:
                    if (
                        session_id in self._active
                        or session_id in self._processing
                        or session_id in self._pending_approval
                    ):
                        raise AudioStreamError(
                            "an audio stream or response is already active"
                        )
                    turn = self._voice_turn_factory(session_id, request_id)
                    self._active[session_id] = turn
                    events = turn.start(
                        stream_id=payload.audio_stream_id,
                        encoding=payload.encoding,
                        sample_rate_hz=payload.sample_rate_hz,
                        channels=payload.channels,
                    )
                except BaseException:
                    self._active.pop(session_id, None)
                    await self._release_usage(session_id)
                    raise
                return _outbound(events)

            turn = self._active.get(session_id)
            if isinstance(payload, AudioInputChunkPayload):
                if turn is None:
                    raise AudioStreamError("no audio stream is active")
                events = await turn.append_with_vad(
                    stream_id=payload.audio_stream_id,
                    chunk_index=payload.chunk_index,
                    encoding=payload.encoding,
                    data=payload.decoded_data(),
                    duration_ms=payload.duration_ms,
                )
                return _outbound(events)
            if isinstance(payload, AudioInputEndPayload):
                if turn is None:
                    raise AudioStreamError("no audio stream is active")
                if payload.reason in {"barge_in", "disconnect"}:
                    try:
                        events = turn.cancel(stream_id=payload.audio_stream_id)
                        await turn.close_vad(stream_id=payload.audio_stream_id)
                    finally:
                        self._active.pop(session_id, None)
                        await self._release_usage(session_id)
                else:
                    current = asyncio.current_task()
                    if current is None:
                        raise RuntimeError("voice response task is unavailable")
                    self._active.pop(session_id, None)
                    self._processing[session_id] = (
                        request_id,
                        turn,
                        current,
                    )
                    try:
                        events = await turn.finish(
                            stream_id=payload.audio_stream_id,
                            emit=_voice_emitter(emit),
                        )
                        if turn.pending_approval_id is not None:
                            self._pending_approval[session_id] = (
                                request_id,
                                turn,
                            )
                    finally:
                        registered = self._processing.get(session_id)
                        if registered is not None and registered[2] is current:
                            self._processing.pop(session_id, None)
                        if session_id not in self._pending_approval:
                            await self._release_usage(session_id)
                return _outbound(events)
            if isinstance(payload, ApprovalResponsePayload):
                return await self._continue_after_approval(
                    session_id=session_id,
                    request_id=request_id,
                    payload=payload,
                    emit=emit,
                )
            if isinstance(payload, OperationCancelPayload):
                return await self._cancel_response(
                    session_id=session_id,
                    payload=payload,
                )
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
            stream_id = turn.stream_id
            try:
                turn.cancel_active()
                if stream_id is not None:
                    await turn.close_vad(stream_id=stream_id)
            finally:
                await self._release_usage(session_id)
        processing = self._processing.get(session_id)
        if processing is not None:
            stream_id = processing[1].stream_id
            try:
                processing[1].cancel_active()
                processing[2].cancel()
                if stream_id is not None:
                    await processing[1].close_vad(stream_id=stream_id)
                if processing[2] is not asyncio.current_task():
                    await asyncio.gather(processing[2], return_exceptions=True)
            finally:
                self._processing.pop(session_id, None)
                await self._release_usage(session_id)
        pending = self._pending_approval.pop(session_id, None)
        if pending is not None:
            try:
                await pending[1].cancel_pending_approval()
            finally:
                await self._release_usage(session_id)
        self._cancel_results = {
            key: value
            for key, value in self._cancel_results.items()
            if key[0] != session_id
        }

    async def _cancel_response(
        self,
        *,
        session_id: UUID,
        payload: OperationCancelPayload,
    ) -> list[OutboundEvent]:
        cache_key = (session_id, payload.idempotency_key)
        cached = self._cancel_results.get(cache_key)
        if cached is not None:
            return cached
        status = "not_found"
        final_state = "unknown"
        summary = "No matching active operation was found."
        processing = self._processing.get(session_id)
        if (
            payload.target_kind == "assistant_response"
            and processing is not None
            and processing[0] == payload.target_id
        ):
            self._processing.pop(session_id, None)
            stream_id = processing[1].stream_id
            processing[1].cancel_active()
            processing[2].cancel()
            if stream_id is not None:
                await processing[1].close_vad(stream_id=stream_id)
            status = "cancellation_requested"
            final_state = "interrupted"
            summary = (
                "The response task was cancelled and any later output "
                "will be discarded."
            )
        pending = self._pending_approval.get(session_id)
        if (
            status == "not_found"
            and payload.target_kind == "assistant_response"
            and pending is not None
            and pending[0] == payload.target_id
        ):
            self._pending_approval.pop(session_id, None)
            try:
                await pending[1].cancel_pending_approval()
            finally:
                await self._release_usage(session_id)
            status = "cancelled"
            final_state = "interrupted"
            summary = "The pending approval and response were cancelled."
        result = [
            OutboundEvent(
                "operation.cancel.result",
                {
                    "target_kind": payload.target_kind,
                    "target_id": str(payload.target_id),
                    "status": status,
                    "final_state": final_state,
                    "summary": summary,
                    "evidence_id": None,
                },
            )
        ]
        if status in {"cancelled", "cancellation_requested"}:
            result.append(
                OutboundEvent(
                    "assistant.state",
                    {"state": "interrupted"},
                )
            )
        if len(self._cancel_results) >= 128:
            self._cancel_results.pop(next(iter(self._cancel_results)))
        self._cancel_results[cache_key] = result
        return result

    async def _continue_after_approval(
        self,
        *,
        session_id: UUID,
        request_id: UUID,
        payload: ApprovalResponsePayload,
        emit: OutboundEmitter | None,
    ) -> list[OutboundEvent]:
        pending = self._pending_approval.get(session_id)
        if pending is None:
            raise ValueError("no tool approval is pending")
        original_request_id, turn = pending
        if turn.pending_approval_id != payload.approval_id:
            raise ValueError("approval identifier does not match")
        current = asyncio.current_task()
        if current is None:
            raise RuntimeError("approval continuation task is unavailable")
        self._pending_approval.pop(session_id, None)
        self._processing[session_id] = (
            original_request_id,
            turn,
            current,
        )
        try:
            events = await turn.continue_after_approval(
                approval_id=payload.approval_id,
                approved=payload.decision == "approve",
                arguments_digest=payload.arguments_digest,
                reason=payload.reason,
                emit=_voice_emitter(emit),
            )
            if turn.pending_approval_id is not None:
                self._pending_approval[session_id] = (
                    request_id,
                    turn,
                )
            return _outbound(events)
        finally:
            registered = self._processing.get(session_id)
            if registered is not None and registered[2] is current:
                self._processing.pop(session_id, None)
            if session_id not in self._pending_approval:
                await self._release_usage(session_id)

    async def _acquire_usage(self, session_id: UUID) -> None:
        if session_id in self._usage_sessions:
            raise RuntimeError("model usage is already held for session")
        if self._model_activity_barrier is not None:
            await self._model_activity_barrier.acquire_usage()
        self._usage_sessions.add(session_id)

    async def _release_usage(self, session_id: UUID) -> None:
        if session_id not in self._usage_sessions:
            return
        self._usage_sessions.remove(session_id)
        if self._model_activity_barrier is not None:
            await self._model_activity_barrier.release_usage()


def _outbound(events: list[VoiceEvent]) -> list[OutboundEvent]:
    return [OutboundEvent(event.type, event.payload) for event in events]


def _voice_emitter(
    emit: OutboundEmitter | None,
) -> Callable[[VoiceEvent], Awaitable[None]] | None:
    if emit is None:
        return None

    async def adapted(event: VoiceEvent) -> None:
        await emit(OutboundEvent(event.type, event.payload))

    return adapted
