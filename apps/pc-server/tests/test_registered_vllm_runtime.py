from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from local_voice_agent_server.application.model_router import ModelId
from local_voice_agent_server.application.model_switch import RuntimeProcessError
from local_voice_agent_server.infrastructure.registered_vllm_runtime import (
    RegisteredVllmRuntimeAdapter,
    RegisteredVllmSettings,
    RuntimeCommandResult,
)


API_KEY = "test-only-vllm-runtime-key-with-32-characters"


def settings(tmp_path: Path) -> RegisteredVllmSettings:
    start = tmp_path / "start-vllm.sh"
    stop = tmp_path / "stop-vllm.sh"
    start.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    stop.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    return RegisteredVllmSettings(
        api_key=API_KEY,
        base_url="http://127.0.0.1:46322",
        start_script=start,
        stop_script=stop,
        status_path=tmp_path / "status" / "vllm.json",
        evidence_directory=tmp_path / "evidence",
    )


def test_start_uses_only_registered_script_and_closed_model_profile(
    tmp_path: Path,
) -> None:
    observed = {}

    async def runner(argv, environment, timeout):
        observed.update(
            {
                "argv": argv,
                "environment": dict(environment),
                "timeout": timeout,
            }
        )
        return RuntimeCommandResult(0, "ready", "")

    runtime_settings = settings(tmp_path)
    adapter = RegisteredVllmRuntimeAdapter(
        runtime_settings,
        command_runner=runner,
    )

    receipt = asyncio.run(adapter.start(ModelId.GEMMA4_31B))

    assert observed["argv"] == (
        "bash",
        str(runtime_settings.start_script),
    )
    assert observed["environment"]["LVA_VLLM_MODEL_SIZE"] == "31b"
    assert observed["environment"]["LVA_VLLM_MTP_MODE"] == "off"
    assert observed["environment"]["LVA_VLLM_API_KEY"] == API_KEY
    assert "LVA_DATABASE_URL" not in observed["environment"]
    assert receipt.model_id is ModelId.GEMMA4_31B
    assert receipt.action == "start"
    assert Path(receipt.evidence_path).is_file()
    assert API_KEY not in Path(receipt.evidence_path).read_text(encoding="utf-8")


def test_health_matches_status_pid_and_exact_api_model(tmp_path: Path) -> None:
    runtime_settings = settings(tmp_path)
    runtime_settings.status_path.parent.mkdir(parents=True)
    runtime_settings.status_path.write_text(
        json.dumps(
            {
                "state": "ready",
                "pid": os.getpid(),
                "port": 46322,
                "model_size": "12b",
                "model_id": "gemma4-12b",
            }
        ),
        encoding="utf-8",
    )
    requested: list[tuple[str, str | None]] = []

    def http_get(url: str, api_key: str | None, timeout: float) -> bytes:
        assert timeout == 5
        requested.append((url, api_key))
        if url.endswith("/health"):
            return b""
        return b'{"data":[{"id":"gemma4-12b"}]}'

    adapter = RegisteredVllmRuntimeAdapter(
        runtime_settings,
        http_get=http_get,
    )

    receipt = asyncio.run(adapter.health_check(ModelId.GEMMA4_12B))

    assert requested == [
        ("http://127.0.0.1:46322/health", None),
        ("http://127.0.0.1:46322/v1/models", API_KEY),
    ]
    assert receipt.action == "health"
    evidence = json.loads(Path(receipt.evidence_path).read_text(encoding="utf-8"))
    assert evidence["success"] is True
    assert evidence["details"]["model_id"] == "gemma4-12b"
    assert adapter.observe_ready_model() is ModelId.GEMMA4_12B


def test_health_rejects_wrong_served_model_and_records_failure(
    tmp_path: Path,
) -> None:
    runtime_settings = settings(tmp_path)
    runtime_settings.status_path.parent.mkdir(parents=True)
    runtime_settings.status_path.write_text(
        json.dumps(
            {
                "state": "ready",
                "pid": os.getpid(),
                "port": 46322,
                "model_size": "31b",
                "model_id": "gemma4-31b",
            }
        ),
        encoding="utf-8",
    )
    adapter = RegisteredVllmRuntimeAdapter(
        runtime_settings,
        http_get=lambda *_: b'{"data":[{"id":"gemma4-12b"}]}',
    )

    with pytest.raises(RuntimeProcessError) as raised:
        asyncio.run(adapter.health_check(ModelId.GEMMA4_31B))

    assert raised.value.code == "VLLM_HEALTH_FAILED"
    evidence = json.loads(
        Path(raised.value.evidence_path).read_text(encoding="utf-8")
    )
    assert evidence["success"] is False
    assert evidence["details"]["error"] == "ValueError"


def test_command_failure_redacts_api_key_from_evidence(tmp_path: Path) -> None:
    async def runner(*_):
        return RuntimeCommandResult(
            7,
            f"unsafe echo {API_KEY}",
            f"failure {API_KEY}",
        )

    adapter = RegisteredVllmRuntimeAdapter(
        settings(tmp_path),
        command_runner=runner,
    )

    with pytest.raises(RuntimeProcessError) as raised:
        asyncio.run(adapter.start(ModelId.GEMMA4_12B))

    assert raised.value.code == "VLLM_START_FAILED"
    evidence_text = Path(raised.value.evidence_path).read_text(encoding="utf-8")
    assert API_KEY not in evidence_text
    assert evidence_text.count("<redacted>") == 2


def test_stop_requires_closed_listener_after_registered_script(
    tmp_path: Path,
) -> None:
    observed = {}

    async def runner(argv, environment, timeout):
        del timeout
        observed["argv"] = argv
        observed["environment"] = dict(environment)
        return RuntimeCommandResult(0, "stopped", "")

    runtime_settings = settings(tmp_path)
    adapter = RegisteredVllmRuntimeAdapter(
        runtime_settings,
        command_runner=runner,
        port_probe=lambda host, port: False,
    )

    receipt = asyncio.run(adapter.stop(ModelId.GEMMA4_12B))

    assert observed["argv"] == (
        "bash",
        str(runtime_settings.stop_script),
    )
    assert observed["environment"]["LVA_VLLM_EXPECTED_MODEL_SIZE"] == "12b"
    assert receipt.action == "stop"


def test_settings_reject_external_runtime_url(tmp_path: Path) -> None:
    start = tmp_path / "start"
    stop = tmp_path / "stop"
    start.write_text("", encoding="utf-8")
    stop.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="loopback"):
        RegisteredVllmSettings(
            api_key=API_KEY,
            base_url="http://example.com:46322",
            start_script=start,
            stop_script=stop,
            status_path=tmp_path / "status.json",
            evidence_directory=tmp_path / "evidence",
        )
