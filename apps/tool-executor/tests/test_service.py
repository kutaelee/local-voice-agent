from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
import pytest

from local_voice_agent_tool_executor import (
    ReadOnlyToolExecutor,
    Workspace,
    WorkspaceAccess,
    WorkspacePlatform,
    WorkspaceRegistry,
)
from local_voice_agent_tool_executor.audit import AuditEvidenceStore
from local_voice_agent_tool_executor.errors import (
    ExecutionBindingError,
    ExecutionExpired,
    EvidenceWriteError,
    IdempotencyConflict,
    WorkspacePathNotFound,
)
from local_voice_agent_tool_executor.service import (
    BoundExecutionService,
    ExecutionCommand,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def create_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            pytest.fail(f"failed to create test junction: {completed.stderr}")
        return
    link.symlink_to(target, target_is_directory=True)


@pytest.fixture
def executor(tmp_path: Path) -> ReadOnlyToolExecutor:
    return ReadOnlyToolExecutor(
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


@pytest.fixture
def store(tmp_path: Path) -> AuditEvidenceStore:
    return AuditEvidenceStore(
        audit_log=tmp_path / "runtime/audit/tool-executor.jsonl",
        evidence_dir=tmp_path / "runtime/evidence",
    )


def command(
    executor: ReadOnlyToolExecutor,
    *,
    arguments: dict | None = None,
    now: datetime | None = None,
) -> ExecutionCommand:
    observed = now or datetime.now(timezone.utc)
    values = arguments or {
        "workspace_id": "repo",
        "relative_path": "secret.txt",
    }
    return ExecutionCommand(
        execution_id=str(uuid4()),
        session_id=str(uuid4()),
        request_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        idempotency_key=str(uuid4()),
        tool_name="read_file",
        arguments=values,
        normalized_arguments_sha256=executor.validate_arguments(
            "read_file",
            values,
        ),
        tool_definition_sha256=executor.definition_sha256("read_file"),
        risk_level=0,
        requested_at=observed,
        expires_at=observed + timedelta(minutes=2),
    )


def test_success_writes_schema_valid_metadata_without_result_content(
    executor: ReadOnlyToolExecutor,
    store: AuditEvidenceStore,
    tmp_path: Path,
) -> None:
    secret = "not-persisted-secret-content"
    (tmp_path / "secret.txt").write_text(secret, encoding="utf-8")
    service = BoundExecutionService(executor=executor, audit_store=store)
    request = command(executor)

    response = service.execute(request, now=request.requested_at)

    assert response["result"]["result"]["content"] == secret
    evidence = tmp_path / "runtime/evidence" / f"{request.execution_id}.json"
    audit = tmp_path / "runtime/audit/tool-executor.jsonl"
    persisted = evidence.read_text(encoding="utf-8") + audit.read_text(
        encoding="utf-8"
    )
    assert secret not in persisted
    assert "secret.txt" not in persisted

    schema = json.loads(
        (
            REPO_ROOT / "packages/observability/schemas/log-event.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )
    events = [
        json.loads(line)
        for line in audit.read_text(encoding="utf-8").splitlines()
    ]
    assert len(events) == 2
    for event in events:
        validator.validate(event)
    evidence_value = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_value["result_sha256"] == response["result_sha256"]
    assert evidence_value["status"] == "succeeded"


def test_exact_duplicate_returns_cached_result_and_conflict_is_rejected(
    executor: ReadOnlyToolExecutor,
    store: AuditEvidenceStore,
    tmp_path: Path,
) -> None:
    (tmp_path / "secret.txt").write_text("value", encoding="utf-8")
    service = BoundExecutionService(executor=executor, audit_store=store)
    request = command(executor)

    first = service.execute(request, now=request.requested_at)
    duplicate = service.execute(request, now=request.requested_at)
    expired_duplicate = service.execute(request, now=request.expires_at)

    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    assert duplicate["result_sha256"] == first["result_sha256"]
    assert expired_duplicate["duplicate"] is True
    audit_lines = (
        tmp_path / "runtime/audit/tool-executor.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 2

    changed = replace(request, execution_id=str(uuid4()))
    with pytest.raises(IdempotencyConflict):
        service.execute(changed, now=request.requested_at)


@pytest.mark.parametrize(
    "field",
    ["normalized_arguments_sha256", "tool_definition_sha256"],
)
def test_binding_digest_mismatch_is_rejected_before_audit(
    executor: ReadOnlyToolExecutor,
    store: AuditEvidenceStore,
    tmp_path: Path,
    field: str,
) -> None:
    (tmp_path / "secret.txt").write_text("value", encoding="utf-8")
    request = replace(command(executor), **{field: "0" * 64})
    service = BoundExecutionService(executor=executor, audit_store=store)

    with pytest.raises(ExecutionBindingError):
        service.execute(request, now=request.requested_at)
    assert not (tmp_path / "runtime/audit/tool-executor.jsonl").exists()


def test_expired_and_noncanonical_ids_are_rejected_before_execution(
    executor: ReadOnlyToolExecutor,
    store: AuditEvidenceStore,
    tmp_path: Path,
) -> None:
    (tmp_path / "secret.txt").write_text("value", encoding="utf-8")
    service = BoundExecutionService(executor=executor, audit_store=store)
    request = command(executor)
    with pytest.raises(ExecutionExpired):
        service.execute(request, now=request.expires_at)
    with pytest.raises(ExecutionBindingError):
        service.execute(
            replace(request, execution_id="../escape"),
            now=request.requested_at,
        )


def test_failed_tool_call_records_only_error_metadata(
    executor: ReadOnlyToolExecutor,
    store: AuditEvidenceStore,
    tmp_path: Path,
) -> None:
    service = BoundExecutionService(executor=executor, audit_store=store)
    request = command(
        executor,
        arguments={
            "workspace_id": "repo",
            "relative_path": "missing-private-name.txt",
        },
    )

    with pytest.raises(WorkspacePathNotFound):
        service.execute(request, now=request.requested_at)
    with pytest.raises(WorkspacePathNotFound):
        service.execute(request, now=request.requested_at)

    evidence = json.loads(
        (
            tmp_path / "runtime/evidence" / f"{request.execution_id}.json"
        ).read_text(encoding="utf-8")
    )
    audit = (
        tmp_path / "runtime/audit/tool-executor.jsonl"
    ).read_text(encoding="utf-8")
    assert evidence["status"] == "failed"
    assert evidence["error_code"] == "WORKSPACE_PATH_NOT_FOUND"
    assert "missing-private-name.txt" not in audit
    assert "missing-private-name.txt" not in json.dumps(evidence)
    assert len(audit.splitlines()) == 2


def test_evidence_is_no_replace_and_storage_links_are_rejected(
    tmp_path: Path,
) -> None:
    store = AuditEvidenceStore(
        audit_log=tmp_path / "safe/audit.jsonl",
        evidence_dir=tmp_path / "safe/evidence",
    )
    execution_id = str(uuid4())
    store.write_evidence(
        execution_id=execution_id,
        evidence={"status": "succeeded"},
    )
    with pytest.raises(EvidenceWriteError):
        store.write_evidence(
            execution_id=execution_id,
            evidence={"status": "overwritten"},
        )
    persisted = json.loads(
        (tmp_path / "safe/evidence" / f"{execution_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted == {"status": "succeeded"}

    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    create_directory_link(linked, outside)
    with pytest.raises(EvidenceWriteError):
        AuditEvidenceStore(
            audit_log=linked / "audit.jsonl",
            evidence_dir=tmp_path / "other-evidence",
        )
