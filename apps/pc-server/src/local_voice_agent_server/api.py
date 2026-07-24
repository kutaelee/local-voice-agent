"""FastAPI composition root with a fail-closed authenticated WebSocket."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .protocol.envelope import EventEnvelope
from .application.session_events import (
    SessionEventHandler,
    UnavailableSessionEventHandler,
    VoiceSessionEventHandler,
)
from .application.execute_tool import ExecuteQueuedTool
from .application.model_router import ModelId
from .application.model_switch import (
    ModelActivityBarrier,
    ModelSwitchCoordinator,
    ModelSwitchEvent,
)
from .application.tool_execution_lifecycle import DurableToolExecutionLifecycle
from .application.tool_planner import ToolPlanner
from .application.voice_turn import VoiceTurnService
from .infrastructure.audio_workers import (
    SttWorkerAdapter,
    TtsWorkerAdapter,
    UnixJsonWorkerClient,
    VadWorkerAdapter,
)
from .infrastructure.vllm_conversation import VllmConversationAdapter
from .infrastructure.registered_vllm_runtime import (
    RegisteredVllmRuntimeAdapter,
    RegisteredVllmSettings,
)
from .infrastructure.status_adapters import AgentStatusManager
from .infrastructure.tool_agent_conversation import ToolAgentConversation
from .infrastructure.tool_executor_client import (
    HttpToolExecutionAdapter,
    ToolExecutorClientSettings,
)
from .infrastructure.tool_registry import ToolRegistry
from .infrastructure.persistence import PostgresStateStore
from .infrastructure.voice_profiles import (
    VOICE_STYLES,
    VoiceProfileError,
    VoiceProfileStore,
    VoiceSettings,
)
from .domain.model_runtime import ModelRuntime, ModelRuntimeState
from .protocol.client_events import (
    AudioInputEndPayload,
    ApprovalResponsePayload,
    ClientPayload,
    validate_client_payload,
)

LOGGER = logging.getLogger(__name__)


ClientEventType = Literal[
    "audio.input.chunk",
    "audio.input.start",
    "audio.input.end",
    "tool.approval.response",
    "operation.cancel.requested",
    "error",
]


class ClientEnvelope(BaseModel):
    """Closed client-to-server control envelope."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    type: ClientEventType
    session_id: UUID
    request_id: UUID
    sequence: int = Field(ge=0)
    timestamp: datetime
    payload: dict[str, Any]

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        return value


@dataclass(frozen=True, slots=True)
class ServerSettings:
    pairing_token: str

    def __post_init__(self) -> None:
        if len(self.pairing_token) < 32:
            raise ValueError("pairing token must contain at least 32 characters")
        if self.pairing_token == "CHANGE_ME":
            raise ValueError("placeholder pairing token is forbidden")

    @classmethod
    def from_environment(cls) -> "ServerSettings":
        token = os.environ.get("LVA_PAIRING_TOKEN", "")
        if not token:
            raise RuntimeError("LVA_PAIRING_TOKEN is required")
        return cls(pairing_token=token)


class ModelSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    idempotency_key: UUID
    target_model: Literal["gemma4-12b", "gemma4-31b"]


class CreateVoiceProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    wav_base64: str = Field(min_length=1, max_length=12_000_000)
    rights_confirmed: Literal[True]
    local_processing_consent: Literal[True]
    reference_text: str | None = Field(default=None, min_length=1, max_length=1_000)
    style: str = Field(default="neutral", min_length=1, max_length=16)

    @field_validator("style")
    @classmethod
    def style_must_be_supported(cls, value: str) -> str:
        if value not in VOICE_STYLES:
            raise ValueError("unsupported voice style")
        return value


class UpdateVoiceSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=1, max_length=64)
    playback_rate: float = Field(ge=0.85, le=1.25)
    exaggeration: float = Field(ge=0.25, le=1.0)
    cfg_weight: float = Field(ge=0.0, le=1.0)
    temperature: float = Field(ge=0.5, le=1.2)


@dataclass(slots=True)
class _SessionReplayState:
    last_server_sequence: int = -1
    last_client_sequence: int = -1
    connected: bool = False
    events: deque[dict[str, object]] = field(default_factory=deque)
    event_bytes: int = 0
    replay_floor_sequence: int = -1

    def append(self, event: dict[str, object]) -> None:
        encoded_bytes = len(
            json.dumps(
                event,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        sequence = int(event["sequence"])
        if encoded_bytes > 4 * 1024 * 1024:
            self.events.clear()
            self.event_bytes = 0
            self.replay_floor_sequence = sequence
            return
        self.events.append(event)
        self.event_bytes += encoded_bytes
        while len(self.events) > 256 or self.event_bytes > 4 * 1024 * 1024:
            removed = self.events.popleft()
            self.event_bytes -= len(
                json.dumps(
                    removed,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            self.replay_floor_sequence = int(removed["sequence"])


NON_REPLAYABLE_EVENT_TYPES = frozenset(
    {
        "assistant.text.delta",
        "audio.output.chunk",
        "audio.output.end",
        "transcript.user.partial",
    }
)


def _authorized(websocket: WebSocket, expected_token: str) -> bool:
    authorization = websocket.headers.get("authorization", "")
    expected = f"Bearer {expected_token}"
    return hmac.compare_digest(authorization, expected)


def _authorized_request(request: Request, expected_token: str) -> bool:
    authorization = request.headers.get("authorization", "")
    return hmac.compare_digest(authorization, f"Bearer {expected_token}")


def create_app(
    settings: ServerSettings,
    *,
    event_handler: SessionEventHandler | None = None,
    agent_status_provider: Callable[[], list[dict[str, object]]] | None = None,
    state_store: PostgresStateStore | None = None,
    model_switch_coordinator: ModelSwitchCoordinator | None = None,
    voice_profile_store: VoiceProfileStore | None = None,
    reconnect_grace_seconds: float = 120,
) -> FastAPI:
    if not 0.01 <= reconnect_grace_seconds <= 600:
        raise ValueError("reconnect grace period is invalid")
    handler = event_handler or UnavailableSessionEventHandler()
    switch_subscribers: set[
        Callable[[UUID, ModelSwitchEvent], Awaitable[None]]
    ] = set()
    switch_subscribers_lock = asyncio.Lock()
    session_states: OrderedDict[UUID, _SessionReplayState] = OrderedDict()
    session_states_lock = asyncio.Lock()
    disconnect_cleanup_tasks: dict[UUID, asyncio.Task[None]] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            cleanup_tasks = tuple(disconnect_cleanup_tasks.values())
            for task in cleanup_tasks:
                task.cancel()
            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            if state_store is not None:
                await state_store.close()

    app = FastAPI(
        title="Local Voice Agent PC Server",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "pc-server"}

    @app.get("/v1/status/agents")
    async def agent_status(request: Request) -> dict[str, object]:
        authorization = request.headers.get("authorization", "")
        if not hmac.compare_digest(
            authorization,
            f"Bearer {settings.pairing_token}",
        ):
            raise HTTPException(status_code=401, detail="invalid pairing token")
        if agent_status_provider is None:
            raise HTTPException(
                status_code=503,
                detail="agent status adapter is unavailable",
            )
        try:
            agents = await asyncio.to_thread(agent_status_provider)
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="agent status observation failed",
            ) from error
        return {
            "schema_version": "1.0",
            "agents": agents,
        }

    @app.get("/v1/models/status")
    async def model_status(request: Request) -> dict[str, object]:
        if not _authorized_request(request, settings.pairing_token):
            raise HTTPException(status_code=401, detail="invalid pairing token")
        if model_switch_coordinator is None:
            raise HTTPException(
                status_code=503,
                detail="model runtime coordinator is unavailable",
            )
        runtimes = model_switch_coordinator.runtimes
        return {
            "schema_version": "1.0",
            "runtimes": [
                {
                    "model_id": model_id.value,
                    "state": runtime.state.value,
                    "version": runtime.version,
                    "failure_code": (
                        runtime.events[-1].failure_code
                        if runtime.events
                        and runtime.events[-1].failure_code is not None
                        else None
                    ),
                }
                for model_id, runtime in runtimes.items()
            ],
        }

    @app.get("/v1/voice/profiles")
    async def voice_profiles(request: Request) -> dict[str, object]:
        if not _authorized_request(request, settings.pairing_token):
            raise HTTPException(status_code=401, detail="invalid pairing token")
        if voice_profile_store is None:
            raise HTTPException(
                status_code=503,
                detail="voice profile store is unavailable",
            )
        try:
            profiles = await asyncio.to_thread(voice_profile_store.list_profiles)
            voice_settings = await asyncio.to_thread(
                voice_profile_store.get_settings
            )
        except VoiceProfileError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return {
            "schema_version": "1.0",
            "profiles": [profile.to_dict() for profile in profiles],
            "settings": voice_settings.to_dict(),
        }

    @app.post("/v1/voice/profiles", status_code=201)
    async def create_voice_profile(
        payload: CreateVoiceProfileRequest,
        request: Request,
    ) -> dict[str, object]:
        if not _authorized_request(request, settings.pairing_token):
            raise HTTPException(status_code=401, detail="invalid pairing token")
        if voice_profile_store is None:
            raise HTTPException(
                status_code=503,
                detail="voice profile store is unavailable",
            )
        try:
            profile = await asyncio.to_thread(
                voice_profile_store.create_profile,
                name=payload.name,
                wav_base64=payload.wav_base64,
                rights_confirmed=payload.rights_confirmed,
                local_processing_consent=payload.local_processing_consent,
                reference_text=payload.reference_text,
                style=payload.style,
            )
        except VoiceProfileError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "schema_version": "1.0",
            "profile": profile.to_dict(),
        }

    @app.put("/v1/voice/settings")
    async def update_voice_settings(
        payload: UpdateVoiceSettingsRequest,
        request: Request,
    ) -> dict[str, object]:
        if not _authorized_request(request, settings.pairing_token):
            raise HTTPException(status_code=401, detail="invalid pairing token")
        if voice_profile_store is None:
            raise HTTPException(
                status_code=503,
                detail="voice profile store is unavailable",
            )
        try:
            voice_settings = VoiceSettings(
                profile_id=payload.profile_id,
                playback_rate=payload.playback_rate,
                exaggeration=payload.exaggeration,
                cfg_weight=payload.cfg_weight,
                temperature=payload.temperature,
            )
            updated = await asyncio.to_thread(
                voice_profile_store.update_settings,
                voice_settings,
            )
        except VoiceProfileError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "schema_version": "1.0",
            "settings": updated.to_dict(),
        }

    @app.post("/v1/models/switch")
    async def switch_model(
        payload: ModelSwitchRequest,
        request: Request,
    ) -> dict[str, object]:
        if not _authorized_request(request, settings.pairing_token):
            raise HTTPException(status_code=401, detail="invalid pairing token")
        if model_switch_coordinator is None:
            raise HTTPException(
                status_code=503,
                detail="model runtime coordinator is unavailable",
            )

        async def broadcast(event: ModelSwitchEvent) -> None:
            async with switch_subscribers_lock:
                subscribers = tuple(switch_subscribers)
            failed: list[Callable[[UUID, ModelSwitchEvent], Awaitable[None]]] = []
            for subscriber in subscribers:
                try:
                    await asyncio.wait_for(
                        subscriber(payload.request_id, event),
                        timeout=2,
                    )
                except Exception:
                    failed.append(subscriber)
            if failed:
                async with switch_subscribers_lock:
                    for subscriber in failed:
                        switch_subscribers.discard(subscriber)

        try:
            result = await model_switch_coordinator.switch(
                ModelId(payload.target_model),
                idempotency_key=payload.idempotency_key,
                emit=broadcast,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail="model switch idempotency conflict",
            ) from error
        return {
            "schema_version": "1.0",
            "request_id": str(payload.request_id),
            "requested_model": result.requested_model.value,
            "ready_model": (
                result.ready_model.value
                if result.ready_model is not None
                else None
            ),
            "changed": result.changed,
            "degraded": result.degraded,
            "failure_code": result.failure_code,
            "duration_ms": result.duration_ms,
            "replayed": result.replayed,
        }

    @app.websocket("/v1/sessions/{session_id}/events")
    async def session_events(websocket: WebSocket, session_id: UUID) -> None:
        if not _authorized(websocket, settings.pairing_token):
            await websocket.close(code=4401, reason="invalid pairing token")
            return

        encoded_resume = websocket.query_params.get("after_sequence")
        resume_after: int | None = None
        if encoded_resume is not None:
            try:
                resume_after = int(encoded_resume)
            except ValueError:
                await websocket.close(code=4400, reason="invalid resume sequence")
                return
            if resume_after < -1:
                await websocket.close(code=4400, reason="invalid resume sequence")
                return

        if state_store is not None:
            try:
                await state_store.ensure_session(session_id)
            except Exception:
                await websocket.close(code=1013, reason="durable session unavailable")
                return

        rejection: tuple[int, str] | None = None
        replay: list[dict[str, object]] = []
        async with session_states_lock:
            replay_state = session_states.get(session_id)
            if replay_state is None:
                if resume_after is not None and resume_after >= 0:
                    rejection = (4410, "replay window expired")
                elif len(session_states) >= 1_024:
                    removable = next(
                        (
                            key
                            for key, state in session_states.items()
                            if not state.connected
                            and key not in disconnect_cleanup_tasks
                        ),
                        None,
                    )
                    if removable is None:
                        rejection = (1013, "session capacity reached")
                    else:
                        session_states.pop(removable, None)
                if rejection is None:
                    replay_state = _SessionReplayState(
                        last_server_sequence=(
                            resume_after
                            if resume_after is not None
                            else -1
                        )
                    )
                    session_states[session_id] = replay_state
            elif replay_state.connected:
                rejection = (4409, "session already connected")
            elif resume_after is None:
                rejection = (4409, "resume sequence is required")
            elif resume_after > replay_state.last_server_sequence:
                rejection = (4400, "resume sequence is ahead")
            elif resume_after < replay_state.replay_floor_sequence:
                rejection = (4410, "replay window expired")

            if rejection is None:
                assert replay_state is not None
                replay_state.connected = True
                session_states.move_to_end(session_id)
                prior_cleanup = disconnect_cleanup_tasks.pop(
                    session_id,
                    None,
                )
                if prior_cleanup is not None:
                    prior_cleanup.cancel()
                if resume_after is not None:
                    replay = [
                        event
                        for event in replay_state.events
                        if int(event["sequence"]) > resume_after
                    ]

        if rejection is not None:
            await websocket.close(code=rejection[0], reason=rejection[1])
            return

        assert replay_state is not None
        await websocket.accept()
        send_lock = asyncio.Lock()
        background_tasks: set[asyncio.Task[None]] = set()
        for replayed in replay:
            await websocket.send_json(replayed)

        async def send_event(
            *,
            event_type: str,
            request_id: UUID,
            payload: dict[str, object],
        ) -> None:
            async with send_lock:
                async with session_states_lock:
                    replay_state.last_server_sequence += 1
                    envelope = EventEnvelope.create(
                        type=event_type,
                        session_id=session_id,
                        request_id=request_id,
                        sequence=replay_state.last_server_sequence,
                        payload=payload,
                    )
                    serialized = envelope.to_dict()
                    if event_type not in NON_REPLAYABLE_EVENT_TYPES:
                        replay_state.append(serialized)
                await websocket.send_json(serialized)

        await send_event(
            event_type="assistant.state",
            request_id=uuid4(),
            payload={
                "state": (
                    "reconnecting"
                    if resume_after is not None
                    else "connecting"
                ),
                "detail": (
                    "session replay complete"
                    if resume_after is not None
                    else "authenticated"
                ),
            },
        )

        async def emit_model_switch(
            request_id: UUID,
            event: ModelSwitchEvent,
        ) -> None:
            await send_event(
                event_type=event.type,
                request_id=request_id,
                payload=event.payload,
            )

        if model_switch_coordinator is not None:
            async with switch_subscribers_lock:
                switch_subscribers.add(emit_model_switch)

        async def send_error(
            *,
            request_id: UUID,
            error_code: str,
            message: str,
        ) -> None:
            await send_event(
                event_type="error",
                request_id=request_id,
                payload={
                    "error_code": error_code,
                    "message": message,
                    "component": "api_gateway",
                    "retryable": False,
                },
            )

        async def dispatch(
            *,
            request_id: UUID,
            event_type: str,
            payload: ClientPayload,
        ) -> None:
            async def emit(item: Any) -> None:
                await send_event(
                    event_type=item.type,
                    request_id=request_id,
                    payload=item.payload,
                )

            try:
                outbound = await handler.handle(
                    session_id=session_id,
                    request_id=request_id,
                    event_type=event_type,
                    payload=payload,
                    emit=emit,
                )
                for item in outbound:
                    await emit(item)
            except asyncio.CancelledError:
                return
            except Exception:
                LOGGER.exception(
                    "session event handler failed session_id=%s request_id=%s event_type=%s",
                    session_id,
                    request_id,
                    event_type,
                )
                await send_error(
                    request_id=request_id,
                    error_code="EVENT_HANDLER_FAILED",
                    message="The session event worker failed.",
                )

        try:
            while True:
                raw = await websocket.receive_json()
                try:
                    incoming = ClientEnvelope.model_validate(raw)
                except ValidationError:
                    await send_error(
                        request_id=uuid4(),
                        error_code="SCHEMA_INVALID",
                        message="Client event does not match the closed envelope.",
                    )
                    continue

                try:
                    payload: ClientPayload = validate_client_payload(
                        incoming.type,
                        incoming.payload,
                    )
                except (ValidationError, ValueError):
                    await send_error(
                        request_id=incoming.request_id,
                        error_code="PAYLOAD_INVALID",
                        message="Client event payload does not match its closed schema.",
                    )
                    continue

                if incoming.session_id != session_id:
                    await send_error(
                        request_id=incoming.request_id,
                        error_code="SESSION_MISMATCH",
                        message="Envelope session does not match the path.",
                    )
                    continue

                if incoming.sequence <= replay_state.last_client_sequence:
                    await send_error(
                        request_id=incoming.request_id,
                        error_code="SEQUENCE_REPLAY",
                        message="Client sequence must increase monotonically.",
                    )
                    continue

                replay_state.last_client_sequence = incoming.sequence
                if (
                    isinstance(payload, AudioInputEndPayload)
                    and payload.reason in {"vad_end", "client_stop"}
                ) or isinstance(payload, ApprovalResponsePayload):
                    task = asyncio.create_task(
                        dispatch(
                            request_id=incoming.request_id,
                            event_type=incoming.type,
                            payload=payload,
                        )
                    )
                    background_tasks.add(task)
                    task.add_done_callback(background_tasks.discard)
                else:
                    await dispatch(
                        request_id=incoming.request_id,
                        event_type=incoming.type,
                        payload=payload,
                    )
        except WebSocketDisconnect:
            for task in background_tasks:
                task.cancel()
            await handler.disconnect(
                session_id=session_id,
                preserve_pending_approval=True,
            )
            if background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)
            return
        finally:
            async with session_states_lock:
                replay_state.connected = False

            async def expire_session() -> None:
                cleanup_task = asyncio.current_task()
                try:
                    await asyncio.sleep(reconnect_grace_seconds)
                    async with session_states_lock:
                        current = session_states.get(session_id)
                        if current is None or current.connected:
                            return
                    await handler.disconnect(session_id=session_id)
                    async with session_states_lock:
                        current = session_states.get(session_id)
                        if current is replay_state and not current.connected:
                            session_states.pop(session_id, None)
                finally:
                    if disconnect_cleanup_tasks.get(session_id) is cleanup_task:
                        disconnect_cleanup_tasks.pop(session_id, None)

            existing_cleanup = disconnect_cleanup_tasks.pop(session_id, None)
            if existing_cleanup is not None:
                existing_cleanup.cancel()
            disconnect_cleanup_tasks[session_id] = asyncio.create_task(
                expire_session()
            )
            if model_switch_coordinator is not None:
                async with switch_subscribers_lock:
                    switch_subscribers.discard(emit_model_switch)

    return app


def create_app_from_environment() -> FastAPI:
    """Uvicorn factory; startup fails if no non-placeholder token is set."""

    state_store = _state_store_from_environment()
    model_activity_barrier = ModelActivityBarrier()
    model_switch_coordinator = _model_switch_coordinator_from_environment(
        activity_barrier=model_activity_barrier,
    )
    voice_profile_store = _voice_profile_store_from_environment()
    return create_app(
        ServerSettings.from_environment(),
        event_handler=_event_handler_from_environment(
            state_store=state_store,
            model_switch_coordinator=model_switch_coordinator,
            model_activity_barrier=model_activity_barrier,
            voice_profile_store=voice_profile_store,
        ),
        agent_status_provider=_agent_status_provider_from_environment(),
        state_store=state_store,
        model_switch_coordinator=model_switch_coordinator,
        voice_profile_store=voice_profile_store,
    )


def _model_switch_coordinator_from_environment(
    *,
    activity_barrier: ModelActivityBarrier | None = None,
) -> ModelSwitchCoordinator | None:
    if os.environ.get("LVA_RUNTIME_SWITCH_ENABLED", "0") != "1":
        return None
    api_key = os.environ.get("LVA_VLLM_API_KEY", "")
    settings = RegisteredVllmSettings(
        api_key=api_key,
        base_url=os.environ.get(
            "LVA_VLLM_RUNTIME_URL",
            "http://127.0.0.1:46322",
        ),
        start_script=Path(
            "/mnt/c/Dev/Repos/local-voice-agent/scripts/start-vllm.sh"
        ),
        stop_script=Path(
            "/mnt/c/Dev/Repos/local-voice-agent/scripts/stop-vllm.sh"
        ),
        status_path=Path(
            "/mnt/e/Data/LocalVoiceAgent/runtime/status/vllm.json"
        ),
        evidence_directory=Path(
            "/mnt/e/Data/LocalVoiceAgent/runtime/evidence/model-switch"
        ),
    )
    adapter = RegisteredVllmRuntimeAdapter(settings)
    ready_model = adapter.observe_ready_model()
    runtimes = {
        model_id: ModelRuntime(
            model_id=model_id.value,
            state=(
                ModelRuntimeState.READY
                if ready_model is model_id
                else ModelRuntimeState.UNLOADED
            ),
        )
        for model_id in (ModelId.GEMMA4_12B, ModelId.GEMMA4_31B)
    }
    return ModelSwitchCoordinator(
        process_port=adapter,
        runtimes=runtimes,
        activity_barrier=activity_barrier,
    )


def _state_store_from_environment() -> PostgresStateStore | None:
    if os.environ.get("LVA_TOOLS_ENABLED", "0") != "1":
        return None
    database_url = os.environ.get("LVA_DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("LVA_DATABASE_URL is required when tools are enabled")
    return PostgresStateStore.from_url(database_url)


def _agent_status_provider_from_environment(
) -> Callable[[], list[dict[str, object]]]:
    workspace = Path(
        os.environ.get(
            "LVA_WORKSPACE_ROOT",
            "/mnt/c/Dev/Repos/local-voice-agent",
        )
    )
    if not workspace.is_absolute() or not workspace.is_dir():
        raise RuntimeError("LVA_WORKSPACE_ROOT must be an existing absolute path")
    manager = AgentStatusManager()

    def observe() -> list[dict[str, object]]:
        return [item.to_dict() for item in manager.observe(workspace)]

    return observe


def _voice_profile_store_from_environment() -> VoiceProfileStore:
    return VoiceProfileStore(
        Path(
            os.environ.get(
                "LVA_VOICE_PROFILE_ROOT",
                "/mnt/e/Data/LocalVoiceAgent/voice-profiles",
            )
        )
    )


def _event_handler_from_environment(
    *,
    state_store: PostgresStateStore | None = None,
    model_switch_coordinator: ModelSwitchCoordinator | None = None,
    model_activity_barrier: ModelActivityBarrier | None = None,
    voice_profile_store: VoiceProfileStore | None = None,
) -> SessionEventHandler:
    if os.environ.get("LVA_VOICE_ENABLED", "0") != "1":
        return UnavailableSessionEventHandler()
    worker_token = os.environ.get("LVA_AUDIO_WORKER_TOKEN", "")
    vllm_api_key = os.environ.get("LVA_VLLM_API_KEY", "")
    vllm_model = os.environ.get("LVA_VLLM_MODEL", "")
    if len(worker_token) < 32 or len(vllm_api_key) < 32 or not vllm_model:
        raise RuntimeError("voice worker and vLLM credentials are required")
    stt = SttWorkerAdapter(
        UnixJsonWorkerClient(
            socket_path=Path(
                os.environ.get(
                    "LVA_STT_SOCKET",
                    "/home/kutae/.local/share/local-voice-agent/run/stt.sock",
                )
            ),
            token=worker_token,
            timeout_seconds=60,
        )
    )
    vad = VadWorkerAdapter(
        UnixJsonWorkerClient(
            socket_path=Path(
                os.environ.get(
                    "LVA_VAD_SOCKET",
                    "/home/kutae/.local/share/local-voice-agent/run/vad.sock",
                )
            ),
            token=worker_token,
            timeout_seconds=10,
        )
    )
    tts = TtsWorkerAdapter(
        UnixJsonWorkerClient(
            socket_path=Path(
                os.environ.get(
                    "LVA_TTS_SOCKET",
                    "/home/kutae/.local/share/local-voice-agent/run/tts.sock",
                )
            ),
            token=worker_token,
            timeout_seconds=180,
        ),
        options_provider=(
            voice_profile_store.synthesis_options
            if voice_profile_store is not None
            else None
        ),
    )
    base_url = os.environ.get(
        "LVA_VLLM_BASE_URL",
        "http://127.0.0.1:46322/v1",
    )
    tools_enabled = os.environ.get("LVA_TOOLS_ENABLED", "0") == "1"
    registry: ToolRegistry | None = None
    planner: ToolPlanner | None = None
    tool_executor: ExecuteQueuedTool | None = None
    tool_lifecycle: DurableToolExecutionLifecycle | None = None
    if tools_enabled:
        executor_token = os.environ.get("LVA_TOOL_EXECUTOR_TOKEN", "")
        repo_root = Path(
            os.environ.get(
                "LVA_REPO_ROOT",
                "/mnt/c/Dev/Repos/local-voice-agent",
            )
        )
        if len(executor_token) < 32 or not repo_root.is_absolute():
            raise RuntimeError("tool executor credentials and repo root are required")
        registry = ToolRegistry.load(
            definitions_dir=repo_root / "packages/tool-registry/definitions",
            definition_schema_path=(
                repo_root
                / "packages/tool-registry/schemas/tool-definition.schema.json"
            ),
            disabled_tools={"restricted_shell"},
        )
        planner = ToolPlanner(registry)
        tool_executor = ExecuteQueuedTool(
            HttpToolExecutionAdapter(
                ToolExecutorClientSettings(
                    base_url=os.environ.get(
                        "LVA_TOOL_EXECUTOR_URL",
                        "http://127.0.0.1:46323",
                    ),
                    ipc_token=executor_token,
                    allowed_wsl_gateway=(
                        os.environ.get("LVA_WINDOWS_HOST_IP") or None
                    ),
                )
            )
        )
        if state_store is None:
            raise RuntimeError("durable state is required when tools are enabled")
        tool_lifecycle = DurableToolExecutionLifecycle(
            store=state_store,
            executor=tool_executor,
        )

    def turn_factory(
        session_id: UUID,
        request_id: UUID,
    ) -> VoiceTurnService:
        selected_model = _ready_model_name(
            model_switch_coordinator,
            default=vllm_model,
        )
        if (
            tools_enabled
            and registry is not None
            and planner is not None
            and tool_executor is not None
            and tool_lifecycle is not None
        ):
            conversation = ToolAgentConversation(
                base_url=base_url,
                model=selected_model,
                api_key=vllm_api_key,
                session_id=session_id,
                request_id=request_id,
                registry=registry,
                planner=planner,
                executor=tool_executor,
                lifecycle=tool_lifecycle,
            )
        else:
            conversation = VllmConversationAdapter(
                base_url=base_url,
                model=selected_model,
                api_key=vllm_api_key,
            )
        return VoiceTurnService(
            stt=stt,
            conversation=conversation,
            tts=tts,
            vad=vad,
        )

    return VoiceSessionEventHandler(
        turn_factory,
        model_activity_barrier=model_activity_barrier,
    )


def _ready_model_name(
    coordinator: ModelSwitchCoordinator | None,
    *,
    default: str,
) -> str:
    if coordinator is None:
        return default
    ready = [
        model_id.value
        for model_id, runtime in coordinator.runtimes.items()
        if runtime.state is ModelRuntimeState.READY
    ]
    if len(ready) > 1:
        raise RuntimeError("multiple model runtimes are READY")
    return ready[0] if ready else default
