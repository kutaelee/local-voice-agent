"""FastAPI composition root with a fail-closed authenticated WebSocket."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hmac
import os
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .protocol.envelope import EventEnvelope
from .application.session_events import (
    SessionEventHandler,
    UnavailableSessionEventHandler,
    VoiceSessionEventHandler,
)
from .application.voice_turn import VoiceTurnService
from .infrastructure.audio_workers import (
    SttWorkerAdapter,
    TtsWorkerAdapter,
    UnixJsonWorkerClient,
)
from .infrastructure.vllm_conversation import VllmConversationAdapter
from .infrastructure.status_adapters import AgentStatusManager
from .protocol.client_events import (
    ClientPayload,
    validate_client_payload,
)


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


def _authorized(websocket: WebSocket, expected_token: str) -> bool:
    authorization = websocket.headers.get("authorization", "")
    expected = f"Bearer {expected_token}"
    return hmac.compare_digest(authorization, expected)


async def _send_error(
    websocket: WebSocket,
    *,
    session_id: UUID,
    request_id: UUID,
    sequence: int,
    error_code: str,
    message: str,
) -> None:
    envelope = EventEnvelope.create(
        type="error",
        session_id=session_id,
        request_id=request_id,
        sequence=sequence,
        payload={
            "error_code": error_code,
            "message": message,
            "component": "api_gateway",
            "retryable": False,
        },
    )
    await websocket.send_json(envelope.to_dict())


def create_app(
    settings: ServerSettings,
    *,
    event_handler: SessionEventHandler | None = None,
    agent_status_provider: Callable[[], list[dict[str, object]]] | None = None,
) -> FastAPI:
    handler = event_handler or UnavailableSessionEventHandler()
    app = FastAPI(
        title="Local Voice Agent PC Server",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
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

    @app.websocket("/v1/sessions/{session_id}/events")
    async def session_events(websocket: WebSocket, session_id: UUID) -> None:
        if not _authorized(websocket, settings.pairing_token):
            await websocket.close(code=4401, reason="invalid pairing token")
            return

        await websocket.accept()
        server_sequence = 0
        last_client_sequence = -1
        connected = EventEnvelope.create(
            type="assistant.state",
            session_id=session_id,
            request_id=uuid4(),
            sequence=server_sequence,
            payload={"state": "connecting", "detail": "authenticated"},
        )
        await websocket.send_json(connected.to_dict())

        try:
            while True:
                raw = await websocket.receive_json()
                server_sequence += 1
                try:
                    incoming = ClientEnvelope.model_validate(raw)
                except ValidationError:
                    await _send_error(
                        websocket,
                        session_id=session_id,
                        request_id=uuid4(),
                        sequence=server_sequence,
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
                    await _send_error(
                        websocket,
                        session_id=session_id,
                        request_id=incoming.request_id,
                        sequence=server_sequence,
                        error_code="PAYLOAD_INVALID",
                        message="Client event payload does not match its closed schema.",
                    )
                    continue

                if incoming.session_id != session_id:
                    await _send_error(
                        websocket,
                        session_id=session_id,
                        request_id=incoming.request_id,
                        sequence=server_sequence,
                        error_code="SESSION_MISMATCH",
                        message="Envelope session does not match the path.",
                    )
                    continue

                if incoming.sequence <= last_client_sequence:
                    await _send_error(
                        websocket,
                        session_id=session_id,
                        request_id=incoming.request_id,
                        sequence=server_sequence,
                        error_code="SEQUENCE_REPLAY",
                        message="Client sequence must increase monotonically.",
                    )
                    continue

                last_client_sequence = incoming.sequence
                outbound = await handler.handle(
                    session_id=session_id,
                    request_id=incoming.request_id,
                    event_type=incoming.type,
                    payload=payload,
                )
                for item in outbound:
                    server_sequence += 1
                    envelope = EventEnvelope.create(
                        type=item.type,
                        session_id=session_id,
                        request_id=incoming.request_id,
                        sequence=server_sequence,
                        payload=item.payload,
                    )
                    await websocket.send_json(envelope.to_dict())
        except WebSocketDisconnect:
            await handler.disconnect(session_id=session_id)
            return

    return app


def create_app_from_environment() -> FastAPI:
    """Uvicorn factory; startup fails if no non-placeholder token is set."""

    return create_app(
        ServerSettings.from_environment(),
        event_handler=_event_handler_from_environment(),
        agent_status_provider=_agent_status_provider_from_environment(),
    )


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


def _event_handler_from_environment() -> SessionEventHandler:
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
        )
    )
    conversation = VllmConversationAdapter(
        base_url=os.environ.get("LVA_VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        model=vllm_model,
        api_key=vllm_api_key,
    )
    return VoiceSessionEventHandler(
        lambda: VoiceTurnService(
            stt=stt,
            conversation=conversation,
            tts=tts,
        )
    )
