from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from threading import Event
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from local_voice_agent_server.api import (
    ServerSettings,
    _ready_model_name,
    create_app,
)
from local_voice_agent_server.application.model_router import ModelId
from local_voice_agent_server.application.model_switch import (
    ModelSwitchCoordinator,
    RuntimeActionReceipt,
)
from local_voice_agent_server.application.session_events import OutboundEvent
from local_voice_agent_server.domain.model_runtime import (
    ModelRuntime,
    ModelRuntimeState,
)


TOKEN = "test-only-pairing-token-with-32-chars"


def client() -> TestClient:
    return TestClient(create_app(ServerSettings(pairing_token=TOKEN)))


def event(*, session_id: str, sequence: int = 0) -> dict:
    return {
        "schema_version": "1.0",
        "type": "audio.input.start",
        "session_id": session_id,
        "request_id": str(uuid4()),
        "sequence": sequence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "audio_stream_id": str(uuid4()),
            "encoding": "pcm_s16le",
            "sample_rate_hz": 16000,
            "channels": 1,
        },
    }


def client_event(
    *,
    event_type: str,
    session_id: str,
    request_id: str,
    sequence: int,
    payload: dict,
) -> dict:
    return {
        "schema_version": "1.0",
        "type": event_type,
        "session_id": session_id,
        "request_id": request_id,
        "sequence": sequence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


class SuccessfulRuntimePort:
    def __init__(self) -> None:
        self.calls = []

    async def start(self, model_id: ModelId) -> RuntimeActionReceipt:
        self.calls.append(("start", model_id))
        return self._receipt("start", model_id)

    async def health_check(self, model_id: ModelId) -> RuntimeActionReceipt:
        self.calls.append(("health", model_id))
        return self._receipt("health", model_id)

    async def stop(self, model_id: ModelId) -> RuntimeActionReceipt:
        self.calls.append(("stop", model_id))
        return self._receipt("stop", model_id)

    @staticmethod
    def _receipt(action: str, model_id: ModelId) -> RuntimeActionReceipt:
        return RuntimeActionReceipt(
            model_id=model_id,
            action=action,
            evidence_path=f"/evidence/{model_id.value}-{action}.json",
        )


def model_coordinator() -> tuple[ModelSwitchCoordinator, SuccessfulRuntimePort]:
    port = SuccessfulRuntimePort()
    coordinator = ModelSwitchCoordinator(
        process_port=port,
        runtimes={
            ModelId.GEMMA4_12B: ModelRuntime(
                model_id=ModelId.GEMMA4_12B.value,
                state=ModelRuntimeState.READY,
            ),
            ModelId.GEMMA4_31B: ModelRuntime(
                model_id=ModelId.GEMMA4_31B.value,
            ),
        },
    )
    return coordinator, port


def test_health_is_read_only_and_does_not_disclose_secrets() -> None:
    response = client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "component": "pc-server"}
    assert TOKEN not in response.text


def test_agent_status_requires_pairing_token() -> None:
    response = client().get("/v1/status/agents")
    assert response.status_code == 401
    assert TOKEN not in response.text


def test_agent_status_returns_only_provider_contract() -> None:
    expected = {
        "schema_version": "1.0",
        "adapter_id": "process:codex:123",
        "status": {"agent": "codex"},
        "provenance": {},
        "observed_at": "2026-07-23T15:00:00+00:00",
    }
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        agent_status_provider=lambda: [expected],
    )
    response = TestClient(app).get(
        "/v1/status/agents",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "agents": [expected],
    }


def test_model_status_and_switch_require_pairing_token() -> None:
    coordinator, _ = model_coordinator()
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        model_switch_coordinator=coordinator,
    )
    api = TestClient(app)

    assert api.get("/v1/models/status").status_code == 401
    assert api.post(
        "/v1/models/switch",
        json={
            "request_id": str(uuid4()),
            "idempotency_key": str(uuid4()),
            "target_model": "gemma4-31b",
        },
    ).status_code == 401


def test_model_switch_broadcasts_progress_to_connected_session() -> None:
    coordinator, port = model_coordinator()
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        model_switch_coordinator=coordinator,
    )
    session_id = uuid4()
    request_id = uuid4()
    idempotency_key = uuid4()
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(app) as api:
        status = api.get("/v1/models/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["runtimes"][0]["state"] == "READY"

        with api.websocket_connect(
            f"/v1/sessions/{session_id}/events",
            headers=headers,
        ) as websocket:
            websocket.receive_json()
            response = api.post(
                "/v1/models/switch",
                headers=headers,
                json={
                    "request_id": str(request_id),
                    "idempotency_key": str(idempotency_key),
                    "target_model": "gemma4-31b",
                },
            )
            progress = [websocket.receive_json() for _ in range(5)]

    assert response.status_code == 200
    assert response.json()["ready_model"] == "gemma4-31b"
    assert response.json()["degraded"] is False
    assert response.json()["replayed"] is False
    assert _ready_model_name(coordinator, default="gemma4-12b") == "gemma4-31b"
    assert port.calls == [
        ("stop", ModelId.GEMMA4_12B),
        ("start", ModelId.GEMMA4_31B),
        ("health", ModelId.GEMMA4_31B),
    ]
    assert [item["type"] for item in progress] == [
        "model.switch.started",
        "model.switch.started",
        "model.switch.started",
        "model.switch.started",
        "model.switch.completed",
    ]
    assert all(item["request_id"] == str(request_id) for item in progress)
    assert [item["sequence"] for item in progress] == [1, 2, 3, 4, 5]


def test_model_switch_rejects_conflicting_idempotency_reuse() -> None:
    coordinator, _ = model_coordinator()
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        model_switch_coordinator=coordinator,
    )
    headers = {"Authorization": f"Bearer {TOKEN}"}
    key = str(uuid4())
    with TestClient(app) as api:
        first = api.post(
            "/v1/models/switch",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "idempotency_key": key,
                "target_model": "gemma4-31b",
            },
        )
        conflict = api.post(
            "/v1/models/switch",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "idempotency_key": key,
                "target_model": "gemma4-12b",
            },
        )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "model switch idempotency conflict"


def test_short_pairing_token_is_rejected() -> None:
    with pytest.raises(ValueError):
        ServerSettings(pairing_token="short")


def test_websocket_rejects_missing_pairing_token() -> None:
    session_id = uuid4()
    with pytest.raises(WebSocketDisconnect) as raised:
        with client().websocket_connect(f"/v1/sessions/{session_id}/events"):
            pass
    assert raised.value.code == 4401


def test_websocket_rejects_invalid_pairing_token() -> None:
    session_id = uuid4()
    with pytest.raises(WebSocketDisconnect) as raised:
        with client().websocket_connect(
            f"/v1/sessions/{session_id}/events",
            headers={
                "Authorization": (
                    "Bearer wrong-token-with-at-least-32-characters"
                )
            },
        ):
            pass
    assert raised.value.code == 4401


def test_websocket_accepts_bearer_token_and_sends_state() -> None:
    session_id = uuid4()
    with client().websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as websocket:
        message = websocket.receive_json()
    assert message["type"] == "assistant.state"
    assert message["session_id"] == str(session_id)
    assert message["payload"]["state"] == "connecting"


def test_websocket_reconnect_replays_gap_and_resumes_sequence() -> None:
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        reconnect_grace_seconds=1,
    )
    session_id = uuid4()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as api:
        with api.websocket_connect(
            f"/v1/sessions/{session_id}/events",
            headers=headers,
        ) as websocket:
            connected = websocket.receive_json()
            assert connected["sequence"] == 0
            invalid = event(session_id=str(session_id), sequence=0)
            invalid["unexpected"] = True
            websocket.send_json(invalid)
            error = websocket.receive_json()
            assert error["sequence"] == 1
            assert error["payload"]["error_code"] == "SCHEMA_INVALID"

        with api.websocket_connect(
            (
                f"/v1/sessions/{session_id}/events"
                "?after_sequence=0"
            ),
            headers=headers,
        ) as websocket:
            replayed = websocket.receive_json()
            resumed = websocket.receive_json()

    assert replayed == error
    assert resumed["sequence"] == 2
    assert resumed["payload"]["state"] == "reconnecting"


def test_websocket_reconnect_does_not_replay_text_deltas() -> None:
    class StreamingHandler:
        async def handle(self, **_: object) -> list[OutboundEvent]:
            return [
                OutboundEvent("assistant.text.delta", {"text": "partial"}),
                OutboundEvent(
                    "assistant.text.final",
                    {"text": "complete", "interrupted": False},
                ),
            ]

        async def disconnect(self, **_: object) -> None:
            return None

    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        event_handler=StreamingHandler(),
        reconnect_grace_seconds=1,
    )
    session_id = uuid4()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as api:
        with api.websocket_connect(
            f"/v1/sessions/{session_id}/events",
            headers=headers,
        ) as websocket:
            assert websocket.receive_json()["sequence"] == 0
            websocket.send_json(event(session_id=str(session_id)))
            assert websocket.receive_json()["type"] == "assistant.text.delta"
            final = websocket.receive_json()
            assert final["type"] == "assistant.text.final"
            assert final["sequence"] == 2

        with api.websocket_connect(
            (
                f"/v1/sessions/{session_id}/events"
                "?after_sequence=0"
            ),
            headers=headers,
        ) as websocket:
            replayed = websocket.receive_json()
            resumed = websocket.receive_json()

    assert replayed == final
    assert resumed["sequence"] == 3


def test_websocket_disconnect_expires_suspended_session_after_grace() -> None:
    suspended = Event()
    expired = Event()

    class TrackingHandler:
        async def handle(self, **_: object) -> list[OutboundEvent]:
            return []

        async def disconnect(
            self,
            *,
            preserve_pending_approval: bool = False,
            **_: object,
        ) -> None:
            (suspended if preserve_pending_approval else expired).set()

    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        event_handler=TrackingHandler(),
        reconnect_grace_seconds=0.01,
    )
    with TestClient(app) as api:
        with api.websocket_connect(
            f"/v1/sessions/{uuid4()}/events",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as websocket:
            websocket.receive_json()
        assert suspended.wait(1)
        assert expired.wait(1)


def test_websocket_rejects_resume_after_session_expiry() -> None:
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        reconnect_grace_seconds=0.01,
    )
    session_id = uuid4()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as api:
        with api.websocket_connect(
            f"/v1/sessions/{session_id}/events",
            headers=headers,
        ) as websocket:
            connected = websocket.receive_json()
            assert connected["sequence"] == 0

        time.sleep(0.03)
        with pytest.raises(WebSocketDisconnect) as raised:
            with api.websocket_connect(
                (
                    f"/v1/sessions/{session_id}/events"
                    "?after_sequence=0"
                ),
                headers=headers,
            ):
                pass
    assert raised.value.code == 4410


def test_websocket_rejects_unknown_fields() -> None:
    session_id = uuid4()
    value = event(session_id=str(session_id))
    value["unexpected"] = True
    with client().websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(value)
        error = websocket.receive_json()
    assert error["type"] == "error"
    assert error["payload"]["error_code"] == "SCHEMA_INVALID"


def test_websocket_rejects_naive_timestamp() -> None:
    session_id = uuid4()
    value = event(session_id=str(session_id))
    value["timestamp"] = "2026-07-23T18:00:00"
    with client().websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(value)
        error = websocket.receive_json()
    assert error["payload"]["error_code"] == "SCHEMA_INVALID"


def test_websocket_rejects_session_mismatch() -> None:
    session_id = uuid4()
    with client().websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(event(session_id=str(uuid4())))
        error = websocket.receive_json()
    assert error["payload"]["error_code"] == "SESSION_MISMATCH"


def test_websocket_rejects_replayed_sequence() -> None:
    session_id = uuid4()
    with client().websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(event(session_id=str(session_id), sequence=4))
        unavailable = websocket.receive_json()
        assert unavailable["payload"]["error_code"] == "EVENT_HANDLER_UNAVAILABLE"
        websocket.send_json(event(session_id=str(session_id), sequence=4))
        error = websocket.receive_json()
    assert error["payload"]["error_code"] == "SEQUENCE_REPLAY"


def test_websocket_rejects_invalid_event_payload() -> None:
    session_id = uuid4()
    value = event(session_id=str(session_id))
    value["payload"]["unexpected"] = True
    with client().websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(value)
        error = websocket.receive_json()
    assert error["payload"]["error_code"] == "PAYLOAD_INVALID"


def test_websocket_accepts_cancel_while_voice_response_is_processing() -> None:
    class BlockingHandler:
        async def handle(self, **values: object) -> list[OutboundEvent]:
            if values["event_type"] == "audio.input.end":
                await asyncio.Event().wait()
            return [
                OutboundEvent(
                    "operation.cancel.result",
                    {
                        "target_kind": "assistant_response",
                        "target_id": str(response_request_id),
                        "status": "cancellation_requested",
                        "final_state": "interrupted",
                        "summary": "Cancellation accepted.",
                        "evidence_id": None,
                    },
                )
            ]

        async def disconnect(self, **_: object) -> None:
            return None

    session_id = uuid4()
    response_request_id = uuid4()
    stream_id = uuid4()
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        event_handler=BlockingHandler(),
    )
    with TestClient(app).websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(
            client_event(
                event_type="audio.input.end",
                session_id=str(session_id),
                request_id=str(response_request_id),
                sequence=0,
                payload={
                    "audio_stream_id": str(stream_id),
                    "reason": "vad_end",
                },
            )
        )
        websocket.send_json(
            client_event(
                event_type="operation.cancel.requested",
                session_id=str(session_id),
                request_id=str(uuid4()),
                sequence=1,
                payload={
                    "target_kind": "assistant_response",
                    "target_id": str(response_request_id),
                    "reason": "barge_in",
                    "idempotency_key": str(uuid4()),
                },
            )
        )
        result = websocket.receive_json()
    assert result["type"] == "operation.cancel.result"
    assert result["payload"]["status"] == "cancellation_requested"


def test_websocket_forwards_emitted_event_before_returned_events() -> None:
    class StreamingHandler:
        async def handle(
            self,
            *,
            emit,
            **_: object,
        ) -> list[OutboundEvent]:
            await emit(
                OutboundEvent(
                    "assistant.text.delta",
                    {"text": "첫 청크"},
                )
            )
            return [
                OutboundEvent(
                    "assistant.text.final",
                    {"text": "첫 청크 완료", "interrupted": False},
                )
            ]

        async def disconnect(self, **_: object) -> None:
            return None

    session_id = uuid4()
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        event_handler=StreamingHandler(),
    )
    with TestClient(app).websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(event(session_id=str(session_id)))
        streamed = websocket.receive_json()
        terminal = websocket.receive_json()

    assert streamed["type"] == "assistant.text.delta"
    assert terminal["type"] == "assistant.text.final"
    assert streamed["sequence"] < terminal["sequence"]
