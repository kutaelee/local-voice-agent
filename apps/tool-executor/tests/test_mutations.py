from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from local_voice_agent_tool_executor.errors import (
    MutationPreconditionFailed,
    PatchRejected,
    RollbackRejected,
    WorkspacePathRejected,
)
from local_voice_agent_tool_executor.mutations import FileMutationExecutor
from local_voice_agent_tool_executor.workspaces import (
    Workspace,
    WorkspaceAccess,
    WorkspacePlatform,
    WorkspaceRegistry,
)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@pytest.fixture
def mutations(tmp_path: Path) -> FileMutationExecutor:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return FileMutationExecutor(
        workspaces=WorkspaceRegistry(
            [
                Workspace(
                    workspace_id="repo",
                    platform=(
                        WorkspacePlatform.WINDOWS_NATIVE
                        if os.name == "nt"
                        else WorkspacePlatform.WSL_LINUX
                    ),
                    root=workspace,
                    access=WorkspaceAccess.READ_WRITE,
                )
            ]
        ),
        backup_root=tmp_path / "backups",
    )


def test_create_and_rollback_removes_only_exact_created_file(
    mutations: FileMutationExecutor,
    tmp_path: Path,
) -> None:
    execution_id = str(uuid4())
    idempotency_key = str(uuid4())
    result = mutations.write_file(
        execution_id=execution_id,
        workspace_id="repo",
        relative_path="created.txt",
        expected_sha256=None,
        content="created\n",
        idempotency_key=idempotency_key,
    )
    target = tmp_path / "workspace" / "created.txt"
    assert target.read_text("utf-8") == "created\n"
    assert result["created"] is True
    assert result["backup_id"] == execution_id
    assert "+created" in result["diff"]

    rollback_id = str(uuid4())
    rolled_back = mutations.rollback_file_change(
        execution_id=rollback_id,
        workspace_id="repo",
        relative_path="created.txt",
        backup_id=execution_id,
        expected_current_sha256=result["after_sha256"],
        idempotency_key=str(uuid4()),
    )
    assert not target.exists()
    assert rolled_back["action"] == "removed_created_file"
    assert (tmp_path / "backups" / rollback_id / "before.bin").read_bytes() == (
        b"created\n"
    )


def test_replace_and_rollback_restore_exact_content(
    mutations: FileMutationExecutor,
    tmp_path: Path,
) -> None:
    target = tmp_path / "workspace" / "value.txt"
    target.write_bytes(b"before\n")
    execution_id = str(uuid4())
    changed = mutations.write_file(
        execution_id=execution_id,
        workspace_id="repo",
        relative_path="value.txt",
        expected_sha256=digest(b"before\n"),
        content="after\n",
        idempotency_key=str(uuid4()),
    )
    assert target.read_bytes() == b"after\n"

    rolled_back = mutations.rollback_file_change(
        execution_id=str(uuid4()),
        workspace_id="repo",
        relative_path="value.txt",
        backup_id=execution_id,
        expected_current_sha256=changed["after_sha256"],
        idempotency_key=str(uuid4()),
    )
    assert target.read_bytes() == b"before\n"
    assert rolled_back["after_sha256"] == digest(b"before\n")


def test_hash_mismatch_preserves_file_and_creates_no_backup(
    mutations: FileMutationExecutor,
    tmp_path: Path,
) -> None:
    target = tmp_path / "workspace" / "value.txt"
    target.write_bytes(b"current")
    execution_id = str(uuid4())

    with pytest.raises(MutationPreconditionFailed, match="hash"):
        mutations.write_file(
            execution_id=execution_id,
            workspace_id="repo",
            relative_path="value.txt",
            expected_sha256="0" * 64,
            content="replacement",
            idempotency_key=str(uuid4()),
        )
    assert target.read_bytes() == b"current"
    assert not (tmp_path / "backups" / execution_id).exists()


def test_concurrent_change_invalidates_write_precondition(
    mutations: FileMutationExecutor,
    tmp_path: Path,
) -> None:
    target = tmp_path / "workspace" / "value.txt"
    target.write_bytes(b"planned")
    planned_hash = digest(target.read_bytes())
    target.write_bytes(b"changed concurrently")

    with pytest.raises(MutationPreconditionFailed, match="hash"):
        mutations.write_file(
            execution_id=str(uuid4()),
            workspace_id="repo",
            relative_path="value.txt",
            expected_sha256=planned_hash,
            content="replacement",
            idempotency_key=str(uuid4()),
        )
    assert target.read_bytes() == b"changed concurrently"


def test_rollback_failure_preserves_concurrent_content_and_backup(
    mutations: FileMutationExecutor,
    tmp_path: Path,
) -> None:
    target = tmp_path / "workspace" / "value.txt"
    target.write_bytes(b"before")
    backup_id = str(uuid4())
    changed = mutations.write_file(
        execution_id=backup_id,
        workspace_id="repo",
        relative_path="value.txt",
        expected_sha256=digest(b"before"),
        content="after",
        idempotency_key=str(uuid4()),
    )
    target.write_bytes(b"new concurrent work")

    with pytest.raises(RollbackRejected, match="current hash"):
        mutations.rollback_file_change(
            execution_id=str(uuid4()),
            workspace_id="repo",
            relative_path="value.txt",
            backup_id=backup_id,
            expected_current_sha256=changed["after_sha256"],
            idempotency_key=str(uuid4()),
        )
    assert target.read_bytes() == b"new concurrent work"
    assert (tmp_path / "backups" / backup_id / "metadata.json").is_file()


def test_apply_patch_verifies_context_and_is_rollbackable(
    mutations: FileMutationExecutor,
    tmp_path: Path,
) -> None:
    target = tmp_path / "workspace" / "value.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    before_hash = digest(target.read_bytes())
    patch = (
        "--- a/value.txt\n"
        "+++ b/value.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " alpha\n"
        "-beta\n"
        "+gamma\n"
    )
    result = mutations.apply_patch(
        execution_id=str(uuid4()),
        workspace_id="repo",
        relative_path="value.txt",
        expected_sha256=before_hash,
        patch=patch,
        idempotency_key=str(uuid4()),
    )
    assert target.read_text("utf-8") == "alpha\ngamma\n"
    assert "-beta" in result["diff"]
    assert "+gamma" in result["diff"]

    with pytest.raises(PatchRejected, match="context"):
        mutations.apply_patch(
            execution_id=str(uuid4()),
            workspace_id="repo",
            relative_path="value.txt",
            expected_sha256=result["after_sha256"],
            patch=patch,
            idempotency_key=str(uuid4()),
        )
    assert target.read_text("utf-8") == "alpha\ngamma\n"


def test_read_only_workspace_rejects_mutation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = FileMutationExecutor(
        workspaces=WorkspaceRegistry(
            [
                Workspace(
                    workspace_id="repo",
                    platform=(
                        WorkspacePlatform.WINDOWS_NATIVE
                        if os.name == "nt"
                        else WorkspacePlatform.WSL_LINUX
                    ),
                    root=workspace,
                    access=WorkspaceAccess.READ_ONLY,
                )
            ]
        ),
        backup_root=tmp_path / "backups",
    )
    with pytest.raises(WorkspacePathRejected, match="not writable"):
        executor.write_file(
            execution_id=str(uuid4()),
            workspace_id="repo",
            relative_path="value.txt",
            expected_sha256=None,
            content="value",
            idempotency_key=str(uuid4()),
        )


def test_backup_metadata_contains_hashes_but_not_file_content(
    mutations: FileMutationExecutor,
    tmp_path: Path,
) -> None:
    target = tmp_path / "workspace" / "private.txt"
    target.write_text("private-value", encoding="utf-8")
    execution_id = str(uuid4())
    result = mutations.write_file(
        execution_id=execution_id,
        workspace_id="repo",
        relative_path="private.txt",
        expected_sha256=digest(b"private-value"),
        content="replacement",
        idempotency_key=str(uuid4()),
    )
    metadata_text = (
        tmp_path / "backups" / execution_id / "metadata.json"
    ).read_text("utf-8")
    metadata = json.loads(metadata_text)
    assert "private-value" not in metadata_text
    assert metadata["before_sha256"] == digest(b"private-value")
    assert metadata["after_sha256"] == result["after_sha256"]


def test_symlink_target_is_rejected(
    mutations: FileMutationExecutor,
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("file symlink creation requires elevated Windows policy")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "workspace" / "link.txt"
    link.symlink_to(outside)
    with pytest.raises(WorkspacePathRejected):
        mutations.write_file(
            execution_id=str(uuid4()),
            workspace_id="repo",
            relative_path="link.txt",
            expected_sha256=digest(b"outside"),
            content="changed",
            idempotency_key=str(uuid4()),
        )
