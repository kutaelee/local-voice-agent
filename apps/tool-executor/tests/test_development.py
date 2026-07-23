from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from local_voice_agent_tool_executor.development import DevelopmentToolExecutor
from local_voice_agent_tool_executor.audit import AuditEvidenceStore
from local_voice_agent_tool_executor.errors import (
    DevelopmentToolError,
    ExecutionBindingError,
)
from local_voice_agent_tool_executor.executor import ReadOnlyToolExecutor
from local_voice_agent_tool_executor.service import (
    BoundExecutionService,
    ExecutionCommand,
)
from local_voice_agent_tool_executor.workspaces import (
    CommandProfile,
    Workspace,
    WorkspaceAccess,
    WorkspacePlatform,
    WorkspaceRegistry,
)


def adapter(
    tmp_path: Path,
    *,
    arguments: tuple[str, ...] = ("-c", "print('tests passed')"),
    timeout_seconds: int = 5,
    max_output_bytes: int = 4096,
) -> DevelopmentToolExecutor:
    platform = (
        WorkspacePlatform.WINDOWS_NATIVE
        if sys.platform == "win32"
        else WorkspacePlatform.WSL_LINUX
    )
    workspace = Workspace(
        workspace_id="test_workspace",
        platform=platform,
        root=tmp_path,
        access=WorkspaceAccess.READ_WRITE,
        command_profiles=(
            CommandProfile(
                profile_id="unit-tests",
                kind="test",
                executable_id="python",
                arguments=arguments,
                working_directory_relative=".",
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            ),
        ),
    )
    return DevelopmentToolExecutor(
        workspaces=WorkspaceRegistry((workspace,)),
        executables={"python": Path(sys.executable)},
        artifact_root=tmp_path / "evidence",
    )


def test_registered_test_profile_and_bound_log(tmp_path: Path) -> None:
    executor = adapter(tmp_path)
    result = executor.execute(
        "run_tests",
        {
            "workspace_id": "test_workspace",
            "profile_id": "unit-tests",
            "idempotency_key": str(uuid4()),
        },
    )
    assert result["succeeded"] is True
    assert result["exit_code"] == 0
    assert "tests passed" in result["output_tail"]
    evidence = executor.execute(
        "inspect_test_log",
        {
            "workspace_id": "test_workspace",
            "evidence_id": result["evidence_id"],
            "offset_bytes": 0,
            "max_bytes": 4096,
        },
    )
    assert evidence["eof"] is True
    assert "tests passed" in evidence["text"]


def test_unknown_profile_fails_closed(tmp_path: Path) -> None:
    executor = adapter(tmp_path)
    with pytest.raises(DevelopmentToolError, match="not registered"):
        executor.execute(
            "run_tests",
            {
                "workspace_id": "test_workspace",
                "profile_id": "arbitrary-command",
                "idempotency_key": str(uuid4()),
            },
        )


def test_output_limit_stops_success_claim(tmp_path: Path) -> None:
    executor = adapter(
        tmp_path,
        arguments=("-c", "print('x' * 10000)"),
        max_output_bytes=128,
    )
    result = executor.execute(
        "run_tests",
        {
            "workspace_id": "test_workspace",
            "profile_id": "unit-tests",
            "idempotency_key": str(uuid4()),
        },
    )
    assert result["succeeded"] is False
    assert result["output_limited"] is True
    assert result["output_bytes"] <= 128


def test_registered_child_timeout_stops_success_claim_and_records_evidence(
    tmp_path: Path,
) -> None:
    executor = adapter(
        tmp_path,
        arguments=("-c", "import time; time.sleep(10)"),
        timeout_seconds=1,
    )
    result = executor.execute(
        "run_tests",
        {
            "workspace_id": "test_workspace",
            "profile_id": "unit-tests",
            "idempotency_key": str(uuid4()),
        },
    )
    assert result["succeeded"] is False
    assert result["timed_out"] is True
    assert result["exit_code"] != 0
    metadata = (
        tmp_path / "evidence" / f"{result['evidence_id']}.json"
    ).read_text(encoding="utf-8")
    assert '"timed_out":true' in metadata


def test_log_workspace_binding_fails_closed(tmp_path: Path) -> None:
    executor = adapter(tmp_path)
    result = executor.execute(
        "run_tests",
        {
            "workspace_id": "test_workspace",
            "profile_id": "unit-tests",
            "idempotency_key": str(uuid4()),
        },
    )
    with pytest.raises(DevelopmentToolError, match="binding"):
        executor.execute(
            "inspect_test_log",
            {
                "workspace_id": "another_workspace",
                "evidence_id": result["evidence_id"],
            },
        )


def test_registered_test_profile_requires_exact_approval_via_service(
    tmp_path: Path,
) -> None:
    platform = (
        WorkspacePlatform.WINDOWS_NATIVE
        if sys.platform == "win32"
        else WorkspacePlatform.WSL_LINUX
    )
    workspace = Workspace(
        workspace_id="repo",
        platform=platform,
        root=tmp_path,
        access=WorkspaceAccess.READ_WRITE,
        command_profiles=(
            CommandProfile(
                profile_id="unit-tests",
                kind="test",
                executable_id="python",
                arguments=("-c", "print('approval-bound test')"),
                working_directory_relative=".",
                timeout_seconds=5,
                max_output_bytes=4096,
            ),
        ),
    )
    registry = WorkspaceRegistry((workspace,))
    development = DevelopmentToolExecutor(
        workspaces=registry,
        executables={"python": Path(sys.executable)},
        artifact_root=tmp_path / "development-evidence",
    )
    definitions = Path(__file__).resolve().parents[3] / "packages/tool-registry"
    executor = ReadOnlyToolExecutor(
        workspaces=registry,
        definitions_dir=definitions / "definitions",
        definition_schema_path=definitions / "schemas/tool-definition.schema.json",
        development=development,
    )
    service = BoundExecutionService(
        executor=executor,
        audit_store=AuditEvidenceStore(
            audit_log=tmp_path / "runtime/audit.jsonl",
            evidence_dir=tmp_path / "runtime/evidence",
        ),
    )
    now = datetime.now(timezone.utc)
    idempotency_key = str(uuid4())
    arguments = {
        "workspace_id": "repo",
        "profile_id": "unit-tests",
        "idempotency_key": idempotency_key,
    }
    digest = executor.validate_arguments("run_tests", arguments)
    request = ExecutionCommand(
        execution_id=str(uuid4()),
        session_id=str(uuid4()),
        request_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        idempotency_key=idempotency_key,
        tool_name="run_tests",
        arguments=arguments,
        normalized_arguments_sha256=digest,
        tool_definition_sha256=executor.definition_sha256("run_tests"),
        risk_level=1,
        requested_at=now,
        expires_at=now + timedelta(minutes=2),
    )
    with pytest.raises(ExecutionBindingError, match="approval"):
        service.execute(request, now=now)

    approved = replace(
        request,
        approval_id=str(uuid4()),
        approval_arguments_sha256=digest,
        approval_expires_at=now + timedelta(minutes=1),
    )
    response = service.execute(approved, now=now)
    assert response["status"] == "succeeded"
    assert response["result"]["result"]["succeeded"] is True
