from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest

from local_voice_agent_server.application.tool_planner import ToolPlanner
from local_voice_agent_server.infrastructure.tool_executor_client import (
    HttpToolExecutionAdapter,
    ToolExecutorClientError,
    ToolExecutorClientSettings,
)
from local_voice_agent_server.infrastructure.tool_registry import ToolRegistry
from local_voice_agent_server.domain.tool_execution import ToolExecutionState


REPO_ROOT = Path(__file__).resolve().parents[3]
TOKEN = "test-only-executor-token-with-32-characters"


def make_plan(tool_name: str = "read_file"):
    registry = ToolRegistry.load(
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT
            / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
    )
    arguments = (
        {"workspace_id": "repo", "relative_path": "README.md"}
        if tool_name == "read_file"
        else {
            "workspace_id": "repo",
            "relative_path": "notes.txt",
            "expected_sha256": None,
            "content": "draft",
        }
    )
    return ToolPlanner(registry).plan(
        session_id=str(uuid4()),
        request_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        tool_name=tool_name,
        arguments=arguments,
        idempotency_key=str(uuid4()),
        precondition_version=0,
    )


def running_plan():
    plan = make_plan()
    running = plan.execution.transition(
        ToolExecutionState.RUNNING,
        expected_version=plan.execution.version,
        reason="test_dispatch",
    )
    return replace(plan, execution=running)


def success_response(execution_id: str) -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0",
            "execution_id": execution_id,
            "status": "succeeded",
            "duplicate": False,
            "result": {"content": "safe"},
            "result_sha256": "a" * 64,
            "evidence_id": str(uuid4()),
        }
    ).encode()


def test_adapter_binds_exact_running_plan_and_token() -> None:
    plan = running_plan()
    captured: dict = {}

    def transport(url, body, headers, timeout, max_response):
        captured.update(
            url=url,
            payload=json.loads(body),
            headers=headers,
            timeout=timeout,
            max_response=max_response,
        )
        return success_response(plan.execution.execution_id)

    adapter = HttpToolExecutionAdapter(
        ToolExecutorClientSettings(
            base_url="http://127.0.0.1:8790",
            ipc_token=TOKEN,
        ),
        transport=transport,
    )
    receipt = adapter.execute(
        plan,
        requested_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )

    assert receipt.result == {"content": "safe"}
    assert captured["url"] == "http://127.0.0.1:8790/v1/executions"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert captured["payload"]["arguments"] == dict(plan.normalized_arguments)
    assert (
        captured["payload"]["normalized_arguments_sha256"]
        == plan.execution.normalized_arguments_sha256
    )
    assert (
        captured["payload"]["tool_definition_sha256"]
        == plan.policy.tool_definition_sha256
    )
    assert captured["payload"]["risk_level"] == 0
    assert captured["payload"]["expires_at"] == "2026-07-23T00:02:00+00:00"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://0.0.0.0:8790",
        "http://localhost:8790",
        "https://127.0.0.1:8790",
        "http://127.0.0.1:8790/unexpected",
    ],
)
def test_settings_reject_non_loopback_or_ambiguous_url(base_url: str) -> None:
    with pytest.raises(ValueError):
        ToolExecutorClientSettings(base_url=base_url, ipc_token=TOKEN)


def test_adapter_rejects_non_level_zero_plan_before_transport() -> None:
    called = False

    def transport(*_args):
        nonlocal called
        called = True
        return b"{}"

    adapter = HttpToolExecutionAdapter(
        ToolExecutorClientSettings(
            base_url="http://127.0.0.1:8790",
            ipc_token=TOKEN,
        ),
        transport=transport,
    )
    with pytest.raises(ToolExecutorClientError):
        adapter.execute(make_plan("write_file"))
    assert called is False


def test_adapter_rejects_response_for_other_execution() -> None:
    adapter = HttpToolExecutionAdapter(
        ToolExecutorClientSettings(
            base_url="http://127.0.0.1:8790",
            ipc_token=TOKEN,
        ),
        transport=lambda *_args: success_response(str(uuid4())),
    )
    with pytest.raises(ToolExecutorClientError):
        adapter.execute(running_plan())


def test_adapter_rejects_response_with_unknown_fields() -> None:
    plan = running_plan()
    value = json.loads(success_response(plan.execution.execution_id))
    value["unexpected"] = True
    adapter = HttpToolExecutionAdapter(
        ToolExecutorClientSettings(
            base_url="http://127.0.0.1:8790",
            ipc_token=TOKEN,
        ),
        transport=lambda *_args: json.dumps(value).encode(),
    )
    with pytest.raises(ToolExecutorClientError):
        adapter.execute(plan)
