from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from local_voice_agent_server.api import (
    ServerSettings,
    create_app,
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


def test_short_pairing_token_is_rejected() -> None:
    with pytest.raises(ValueError):
        ServerSettings(pairing_token="short")


def test_websocket_rejects_missing_pairing_token() -> None:
    session_id = uuid4()
    with pytest.raises(WebSocketDisconnect) as raised:
        with client().websocket_connect(f"/v1/sessions/{session_id}/events"):
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
