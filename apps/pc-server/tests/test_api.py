from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
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
from local_voice_agent_server.application.salon_calls import SalonCallCoordinator
from local_voice_agent_server.application.salon_speech import SalonSpeechService
from local_voice_agent_server.application.session_events import OutboundEvent
from local_voice_agent_server.application.voice_turn import SynthesizedAudio
from local_voice_agent_server.domain.model_runtime import (
    ModelRuntime,
    ModelRuntimeState,
)
from local_voice_agent_server.domain.salon_booking import SalonReservationService
from local_voice_agent_server.infrastructure.file_reservations import (
    FileReservationStore,
)
from local_voice_agent_server.infrastructure.salon_config import load_salon_policy


TOKEN = "test-only-pairing-token-with-32-chars"
REPO_ROOT = Path(__file__).resolve().parents[3]


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


def test_qa_portal_is_local_static_content_without_secrets() -> None:
    response = client().get("/qa")
    assert response.status_code == 200
    assert "Voice QA Console" in response.text
    assert TOKEN not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers[
        "content-security-policy"
    ]
    assert client().get("/qa/app.js").status_code == 200
    assert client().get("/qa/styles.css").status_code == 200
    assert client().get("/qa/pcm-worklet.js").status_code == 200


def test_qa_websocket_ticket_requires_pairing_token() -> None:
    response = client().post("/v1/qa/ws-ticket", json={})
    assert response.status_code == 401
    assert TOKEN not in response.text


def test_qa_loopback_bootstrap_issues_memory_only_browser_session() -> None:
    expected = {
        "runtime": {
            "state": "ready",
            "model_id": "gemma4-12b",
            "mtp_mode": "off",
        },
        "workers": {"vad": True, "stt": True, "tts": True},
    }
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        qa_runtime_status_provider=lambda: expected,
    )
    api = TestClient(
        app,
        base_url="http://127.0.0.1:46326",
        client=("127.0.0.1", 50_000),
        headers={"user-agent": "qa-browser-test"},
    )

    assert api.post("/v1/qa/bootstrap", json={}).status_code == 403
    issued = api.post(
        "/v1/qa/bootstrap",
        headers={"Origin": "http://127.0.0.1:46326"},
        json={},
    )
    assert issued.status_code == 200
    assert issued.headers["cache-control"] == "no-store"
    access_token = issued.json()["access_token"]
    assert len(access_token) >= 32
    assert access_token != TOKEN
    assert TOKEN not in issued.text

    runtime = api.get(
        "/v1/qa/runtime-status",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert runtime.status_code == 200
    assert runtime.json() == {"schema_version": "1.0", **expected}
    ticket = api.post(
        "/v1/qa/ws-ticket",
        headers={"Authorization": f"Bearer {access_token}"},
        json={},
    )
    assert ticket.status_code == 200
    assert TOKEN not in ticket.text


def test_qa_loopback_bootstrap_rejects_remote_and_cross_origin_requests() -> None:
    app = create_app(ServerSettings(pairing_token=TOKEN))
    remote = TestClient(
        app,
        base_url="http://192.168.200.94:46321",
        client=("192.168.200.50", 50_000),
    )
    assert (
        remote.post(
            "/v1/qa/bootstrap",
            headers={"Origin": "http://192.168.200.94:46321"},
            json={},
        ).status_code
        == 403
    )

    loopback = TestClient(
        app,
        base_url="http://127.0.0.1:46326",
        client=("127.0.0.1", 50_000),
    )
    assert (
        loopback.post(
            "/v1/qa/bootstrap",
            headers={"Origin": "http://attacker.invalid"},
            json={},
        ).status_code
        == 403
    )


def test_qa_browser_session_is_bound_to_client_fingerprint() -> None:
    app = create_app(ServerSettings(pairing_token=TOKEN))
    original = TestClient(
        app,
        base_url="http://127.0.0.1:46326",
        client=("127.0.0.1", 50_000),
        headers={"user-agent": "qa-browser-one"},
    )
    issued = original.post(
        "/v1/qa/bootstrap",
        headers={"Origin": "http://127.0.0.1:46326"},
        json={},
    )
    access_token = issued.json()["access_token"]

    changed_browser = TestClient(
        app,
        base_url="http://127.0.0.1:46326",
        client=("127.0.0.1", 50_000),
        headers={"user-agent": "qa-browser-two"},
    )
    rejected = changed_browser.post(
        "/v1/qa/ws-ticket",
        headers={"Authorization": f"Bearer {access_token}"},
        json={},
    )
    assert rejected.status_code == 401


def test_qa_runtime_status_is_authenticated_and_bounded() -> None:
    expected = {
        "runtime": {
            "state": "ready",
            "model_id": "gemma4-12b",
            "mtp_mode": "off",
        },
        "workers": {"vad": True, "stt": True, "tts": True},
    }
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        qa_runtime_status_provider=lambda: expected,
    )
    api = TestClient(app)

    assert api.get("/v1/qa/runtime-status").status_code == 401
    response = api.get(
        "/v1/qa/runtime-status",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json() == {"schema_version": "1.0", **expected}


def test_qa_websocket_ticket_is_single_use() -> None:
    session_id = uuid4()
    with client() as api:
        issued = api.post(
            "/v1/qa/ws-ticket",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={},
        )
        assert issued.status_code == 200
        ticket = issued.json()["ticket"]
        assert TOKEN not in issued.text
        protocols = ["lva.qa.v1", f"lva.ticket.{ticket}"]

        with api.websocket_connect(
            f"/v1/sessions/{session_id}/events",
            subprotocols=protocols,
        ) as websocket:
            assert websocket.accepted_subprotocol == "lva.qa.v1"
            assert websocket.receive_json()["type"] == "assistant.state"

        with pytest.raises(WebSocketDisconnect) as rejected:
            with api.websocket_connect(
                f"/v1/sessions/{uuid4()}/events",
                subprotocols=protocols,
            ):
                pass
        assert rejected.value.code == 4401


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


def test_websocket_runs_salon_text_call_without_voice_or_model(
    tmp_path: Path,
) -> None:
    policy = load_salon_policy(REPO_ROOT / "configs" / "salon-booking.json")
    now = lambda: datetime(2026, 7, 25, 9, 0, tzinfo=policy.timezone)
    coordinator = SalonCallCoordinator(
        reservations=SalonReservationService(
            policy=policy,
            repository=FileReservationStore(
                data_path=tmp_path / "reservations.json",
                backup_root=tmp_path / "backup",
            ),
            now=now,
        ),
        now=now,
    )
    session_id = uuid4()
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        salon_call_coordinator=coordinator,
    )
    with TestClient(app).websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "assistant.state"
        websocket.send_json(
            client_event(
                event_type="salon.call.start",
                session_id=str(session_id),
                request_id=str(uuid4()),
                sequence=0,
                payload={"channel": "web_qa"},
            )
        )
        assert websocket.receive_json()["type"] == "salon.call.started"
        assert websocket.receive_json()["type"] == "salon.assistant.message"
        assert websocket.receive_json()["type"] == "assistant.state"
        websocket.send_json(
            client_event(
                event_type="salon.call.message",
                session_id=str(session_id),
                request_id=str(uuid4()),
                sequence=1,
                payload={"text": "커트 가격은 얼마예요?"},
            )
        )
        answer = websocket.receive_json()
    assert answer["type"] == "salon.assistant.message"
    assert "25,000원" in answer["payload"]["text"]

    table = TestClient(app).get(
        "/v1/salon/reservations",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert table.status_code == 200
    body = table.json()
    assert body["schema_version"] == "1.0"
    assert body["reservations"] == []
    assert {item["category"] for item in body["menu"]} >= {"커트", "염색", "펌"}
    assert all(item["staff"] for item in body["menu"])


def test_websocket_can_attach_tts_to_salon_text_reply(tmp_path: Path) -> None:
    class FakeTts:
        async def synthesize(
            self,
            text: str,
            *,
            language: str,
        ) -> SynthesizedAudio:
            assert "윤슬 헤어" in text
            assert language == "ko"
            return SynthesizedAudio(
                pcm_s16le=b"\x01\x00" * 480,
                sample_rate_hz=24_000,
                channels=1,
            )

    policy = load_salon_policy(REPO_ROOT / "configs" / "salon-booking.json")
    now = lambda: datetime(2026, 7, 25, 9, 0, tzinfo=policy.timezone)
    coordinator = SalonCallCoordinator(
        reservations=SalonReservationService(
            policy=policy,
            repository=FileReservationStore(
                data_path=tmp_path / "reservations.json",
                backup_root=tmp_path / "backup",
            ),
            now=now,
        ),
        now=now,
    )
    session_id = uuid4()
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        salon_call_coordinator=coordinator,
        salon_speech_service=SalonSpeechService(tts=FakeTts()),
    )

    with TestClient(app).websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(
            client_event(
                event_type="salon.call.start",
                session_id=str(session_id),
                request_id=str(uuid4()),
                sequence=0,
                payload={"channel": "web_qa"},
            )
        )
        received = []
        while not any(item["type"] == "audio.output.end" for item in received):
            received.append(websocket.receive_json())

    types = [item["type"] for item in received]
    assert types[:3] == [
        "salon.call.started",
        "salon.assistant.message",
        "assistant.state",
    ]
    assert "audio.output.chunk" in types
    assert types[-1] == "audio.output.end"


def test_salon_reservation_notification_is_broadcast_to_another_app_session(
    tmp_path: Path,
) -> None:
    policy = load_salon_policy(REPO_ROOT / "configs" / "salon-booking.json")
    now = lambda: datetime(2026, 7, 25, 9, 0, tzinfo=policy.timezone)
    coordinator = SalonCallCoordinator(
        reservations=SalonReservationService(
            policy=policy,
            repository=FileReservationStore(
                data_path=tmp_path / "reservations.json",
                backup_root=tmp_path / "backup",
            ),
            now=now,
        ),
        now=now,
    )
    caller_session = uuid4()
    owner_session = uuid4()
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        salon_call_coordinator=coordinator,
    )
    api = TestClient(app)
    with api.websocket_connect(
        f"/v1/sessions/{owner_session}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as owner:
        owner.receive_json()
        with api.websocket_connect(
            f"/v1/sessions/{caller_session}/events",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as caller:
            caller.receive_json()
            caller.send_json(
                client_event(
                    event_type="salon.call.start",
                    session_id=str(caller_session),
                    request_id=str(uuid4()),
                    sequence=0,
                    payload={"channel": "web_qa"},
                )
            )
            for _ in range(3):
                caller.receive_json()
            caller.send_json(
                client_event(
                    event_type="salon.call.message",
                    session_id=str(caller_session),
                    request_id=str(uuid4()),
                    sequence=1,
                    payload={
                        "text": (
                            "7월 26일 오후 2시에 커트 예약. "
                            "이름은 김규태, 010-1234-5678"
                        )
                    },
                )
            )
            caller.receive_json()
            caller.send_json(
                client_event(
                    event_type="salon.call.message",
                    session_id=str(caller_session),
                    request_id=str(uuid4()),
                    sequence=2,
                    payload={"text": "네"},
                )
            )
            assert caller.receive_json()["type"] == "salon.assistant.message"
            assert caller.receive_json()["type"] == "salon.reservation.updated"
            assert caller.receive_json()["type"] == "salon.owner.notification"
            notification = owner.receive_json()

    assert notification["type"] == "salon.owner.notification"
    assert notification["payload"]["change_type"] == "created"
