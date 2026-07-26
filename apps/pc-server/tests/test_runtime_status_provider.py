from __future__ import annotations

import json
from pathlib import Path
import socket
import threading

from local_voice_agent_server.api import (
    _is_audio_worker_healthy,
    _qa_runtime_status_provider_from_environment,
)


TOKEN = "runtime-status-worker-token-1234567890"


def _serve_one_health_request(server: socket.socket) -> None:
    connection, _ = server.accept()
    with connection:
        request = json.loads(connection.recv(16 * 1024))
        assert request["operation"] == "health"
        assert request["token"] == TOKEN
        connection.sendall(b'{"status":"ok","component":"test-worker"}\n')


def test_audio_worker_health_requires_a_live_authenticated_response(
    tmp_path: Path,
) -> None:
    live_path = tmp_path / "live.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(live_path))
        server.listen(1)
        thread = threading.Thread(
            target=_serve_one_health_request,
            args=(server,),
            daemon=True,
        )
        thread.start()
        assert _is_audio_worker_healthy(
            live_path,
            TOKEN,
            expected_component="test-worker",
        )
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert live_path.is_socket()
    assert not _is_audio_worker_healthy(live_path, TOKEN)
    assert not _is_audio_worker_healthy(live_path, "short-token")


def test_runtime_status_provider_rejects_stale_worker_sockets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = {
        "LVA_VAD_SOCKET": tmp_path / "vad.sock",
        "LVA_STT_SOCKET": tmp_path / "stt.sock",
        "LVA_TTS_SOCKET": tmp_path / "tts.sock",
    }
    for name, path in paths.items():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(str(path))
        monkeypatch.setenv(name, str(path))
    monkeypatch.setenv("LVA_AUDIO_WORKER_TOKEN", TOKEN)
    monkeypatch.setenv(
        "LVA_VLLM_STATUS_PATH",
        str(tmp_path / "missing-vllm-status.json"),
    )

    status = _qa_runtime_status_provider_from_environment()()

    assert status["runtime"]["state"] == "unavailable"
    assert status["workers"] == {"vad": False, "stt": False, "tts": False}
    assert status["streaming_tts"] == {
        "configured": False,
        "ready": False,
        "runtime": None,
    }


def test_runtime_status_provider_reports_streaming_tts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LVA_TTS_ADAPTER", "vllm-omni")
    monkeypatch.setenv(
        "LVA_VLLM_OMNI_TTS_URL",
        "http://127.0.0.1:46329",
    )
    monkeypatch.setenv(
        "LVA_VLLM_STATUS_PATH",
        str(tmp_path / "missing-vllm-status.json"),
    )
    monkeypatch.setattr(
        "local_voice_agent_server.api._is_streaming_tts_healthy",
        lambda url: url == "http://127.0.0.1:46329",
    )

    status = _qa_runtime_status_provider_from_environment()()

    assert status["runtime"]["state"] == "unavailable"
    assert status["workers"]["tts"] is True
    assert status["streaming_tts"] == {
        "configured": True,
        "ready": True,
        "runtime": "vllm-omni-0.24.0",
    }
