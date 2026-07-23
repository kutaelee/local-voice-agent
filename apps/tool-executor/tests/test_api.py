from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from local_voice_agent_tool_executor import (
    ReadOnlyToolExecutor,
    Workspace,
    WorkspaceAccess,
    WorkspacePlatform,
    WorkspaceRegistry,
)
from local_voice_agent_tool_executor.api import ExecutorApiSettings, create_app
from local_voice_agent_tool_executor.audit import AuditEvidenceStore
from local_voice_agent_tool_executor.service import BoundExecutionService


REPO_ROOT = Path(__file__).resolve().parents[3]
TOKEN = "test-only-executor-token-with-32-characters"


def build(tmp_path: Path) -> tuple[TestClient, ReadOnlyToolExecutor]:
    executor = ReadOnlyToolExecutor(
        workspaces=WorkspaceRegistry(
            [
                Workspace(
                    workspace_id="repo",
                    platform=(
                        WorkspacePlatform.WINDOWS_NATIVE
                        if __import__("os").name == "nt"
                        else WorkspacePlatform.WSL_LINUX
                    ),
                    root=tmp_path,
                    access=WorkspaceAccess.READ_ONLY,
                )
            ]
        ),
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
    )
    service = BoundExecutionService(
        executor=executor,
        audit_store=AuditEvidenceStore(
            audit_log=tmp_path / "runtime/audit/tool-executor.jsonl",
            evidence_dir=tmp_path / "runtime/evidence",
        ),
    )
    app = create_app(
        settings=ExecutorApiSettings(ipc_token=TOKEN),
        service=service,
    )
    return TestClient(app), executor


def request_body(
    executor: ReadOnlyToolExecutor,
    *,
    relative_path: str = "file.txt",
) -> dict:
    now = datetime.now(timezone.utc)
    arguments = {
        "workspace_id": "repo",
        "relative_path": relative_path,
    }
    return {
        "schema_version": "1.0",
        "execution_id": str(uuid4()),
        "session_id": str(uuid4()),
        "request_id": str(uuid4()),
        "tool_call_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "tool_name": "read_file",
        "arguments": arguments,
        "normalized_arguments_sha256": executor.validate_arguments(
            "read_file",
            arguments,
        ),
        "tool_definition_sha256": executor.definition_sha256("read_file"),
        "risk_level": 0,
        "requested_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=2)).isoformat(),
    }


def test_health_does_not_disclose_token(tmp_path: Path) -> None:
    client, _executor = build(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "component": "tool-executor"}
    assert TOKEN not in response.text


def test_execution_requires_exact_bearer_before_body_validation(
    tmp_path: Path,
) -> None:
    client, _executor = build(tmp_path)
    response = client.post(
        "/v1/executions",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_closed_schema_and_content_type_are_enforced(tmp_path: Path) -> None:
    client, executor = build(tmp_path)
    body = request_body(executor)
    body["unexpected"] = True
    invalid_schema = client.post(
        "/v1/executions",
        json=body,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    invalid_type = client.post(
        "/v1/executions",
        content=b"{}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "text/plain",
        },
    )
    assert invalid_schema.status_code == 400
    assert invalid_schema.json()["error_code"] == "SCHEMA_INVALID"
    assert invalid_type.status_code == 415


def test_actual_body_size_is_bounded(tmp_path: Path) -> None:
    client, _executor = build(tmp_path)
    response = client.post(
        "/v1/executions",
        content=b"{" + b" " * 70_000 + b"}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 413
    assert response.json()["error_code"] == "REQUEST_TOO_LARGE"


def test_authenticated_bound_execution_returns_receipt(
    tmp_path: Path,
) -> None:
    client, executor = build(tmp_path)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    body = request_body(executor)

    response = client.post(
        "/v1/executions",
        json=body,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    value = response.json()
    assert value["status"] == "succeeded"
    assert value["result"]["result"]["content"] == "hello"
    assert value["evidence_id"] == body["execution_id"]
