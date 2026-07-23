"""Hash-guarded UTF-8 file mutation and exact rollback."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any
from uuid import UUID

from .digests import canonical_json
from .errors import (
    MutationPreconditionFailed,
    PatchRejected,
    RollbackRejected,
)
from .workspaces import (
    ResolvedWorkspacePath,
    WorkspaceRegistry,
    _is_link_or_reparse,
)


MAX_MUTATION_BYTES = 1024 * 1024
_HUNK = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?: .*)?$"
)


class FileMutationExecutor:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRegistry,
        backup_root: Path,
    ) -> None:
        self._workspaces = workspaces
        self._backup_root = Path(backup_root)
        if not self._backup_root.is_absolute():
            raise RollbackRejected("backup root must be absolute")
        try:
            self._backup_root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise RollbackRejected("backup root cannot be prepared") from error
        _assert_safe_directory(self._backup_root)

    def write_file(
        self,
        *,
        execution_id: str,
        workspace_id: str,
        relative_path: str,
        expected_sha256: str | None,
        content: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        del idempotency_key
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_MUTATION_BYTES:
            raise MutationPreconditionFailed("content exceeds mutation limit")
        return self._replace(
            execution_id=execution_id,
            workspace_id=workspace_id,
            relative_path=relative_path,
            expected_sha256=expected_sha256,
            replacement=encoded,
            operation="write_file",
        )

    def apply_patch(
        self,
        *,
        execution_id: str,
        workspace_id: str,
        relative_path: str,
        expected_sha256: str,
        patch: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        del idempotency_key
        target = self._workspaces.resolve_file_target(
            workspace_id,
            relative_path,
        )
        before = _read_regular_file(target)
        _require_hash(before, expected_sha256)
        try:
            original = before.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PatchRejected("patch target is not UTF-8") from error
        replacement = _apply_unified_patch(original, patch).encode("utf-8")
        if len(replacement) > MAX_MUTATION_BYTES:
            raise PatchRejected("patched content exceeds mutation limit")
        return self._replace(
            execution_id=execution_id,
            workspace_id=workspace_id,
            relative_path=relative_path,
            expected_sha256=expected_sha256,
            replacement=replacement,
            operation="apply_patch",
        )

    def rollback_file_change(
        self,
        *,
        execution_id: str,
        workspace_id: str,
        relative_path: str,
        backup_id: str,
        expected_current_sha256: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        del idempotency_key
        metadata, content = self._load_backup(backup_id)
        if (
            metadata["workspace_id"] != workspace_id
            or metadata["relative_path"] != relative_path
        ):
            raise RollbackRejected("backup binding does not match target")
        if metadata["after_sha256"] != expected_current_sha256:
            raise RollbackRejected("rollback current hash does not match backup")
        target = self._workspaces.resolve_file_target(
            workspace_id,
            relative_path,
        )
        current = _read_regular_file(target)
        try:
            _require_hash(current, expected_current_sha256)
        except MutationPreconditionFailed as error:
            raise RollbackRejected(
                "rollback rejected because the current hash changed"
            ) from error
        self._store_backup(
            execution_id=execution_id,
            target=target,
            before=current,
            after=content,
            existed_before=True,
            operation="rollback_file_change",
        )
        if metadata["existed_before"]:
            if content is None:
                raise RollbackRejected("backup content is unavailable")
            _atomic_replace(target, content, expected_current_sha256)
            final_sha256 = _sha256(content)
            action = "restored"
        else:
            _unlink_exact(target, expected_current_sha256)
            final_sha256 = None
            action = "removed_created_file"
        return {
            "workspace_id": workspace_id,
            "relative_path": target.relative_path,
            "operation": "rollback_file_change",
            "action": action,
            "rolled_back_backup_id": backup_id,
            "backup_id": execution_id,
            "before_sha256": expected_current_sha256,
            "after_sha256": final_sha256,
        }

    def _replace(
        self,
        *,
        execution_id: str,
        workspace_id: str,
        relative_path: str,
        expected_sha256: str | None,
        replacement: bytes,
        operation: str,
    ) -> dict[str, Any]:
        target = self._workspaces.resolve_file_target(
            workspace_id,
            relative_path,
        )
        existed = target.path.exists()
        before = _read_regular_file(target) if existed else None
        if expected_sha256 is None:
            if existed:
                raise MutationPreconditionFailed(
                    "target exists but creation was requested"
                )
        else:
            if before is None:
                raise MutationPreconditionFailed("target does not exist")
            _require_hash(before, expected_sha256)
        before_sha256 = _sha256(before) if before is not None else None
        after_sha256 = _sha256(replacement)
        backup_id = self._store_backup(
            execution_id=execution_id,
            target=target,
            before=before,
            after=replacement,
            existed_before=existed,
            operation=operation,
        )
        _atomic_replace(target, replacement, before_sha256)
        persisted = _read_regular_file(target)
        if _sha256(persisted) != after_sha256:
            raise MutationPreconditionFailed(
                "post-write hash verification failed"
            )
        diff = _bounded_diff(
            target.relative_path,
            before or b"",
            replacement,
        )
        return {
            "workspace_id": workspace_id,
            "relative_path": target.relative_path,
            "operation": operation,
            "created": not existed,
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "backup_id": backup_id,
            "diff": diff,
        }

    def _store_backup(
        self,
        *,
        execution_id: str,
        target: ResolvedWorkspacePath,
        before: bytes | None,
        after: bytes | None,
        existed_before: bool,
        operation: str,
    ) -> str:
        backup_id = _canonical_uuid(execution_id)
        _assert_safe_directory(self._backup_root)
        directory = self._backup_root / backup_id
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError as error:
            raise RollbackRejected("backup already exists") from error
        except OSError as error:
            raise RollbackRejected("backup directory cannot be created") from error
        if before is not None:
            _write_exclusive(directory / "before.bin", before)
        metadata = {
            "schema_version": "1.0",
            "backup_id": backup_id,
            "workspace_id": target.workspace.workspace_id,
            "relative_path": target.relative_path,
            "operation": operation,
            "existed_before": existed_before,
            "before_sha256": _sha256(before) if before is not None else None,
            "after_sha256": _sha256(after) if after is not None else None,
        }
        _write_exclusive(
            directory / "metadata.json",
            canonical_json(metadata) + b"\n",
        )
        return backup_id

    def _load_backup(
        self,
        backup_id: str,
    ) -> tuple[dict[str, Any], bytes | None]:
        canonical = _canonical_uuid(backup_id)
        directory = self._backup_root / canonical
        _assert_safe_directory(directory)
        metadata_path = directory / "metadata.json"
        metadata_bytes = _read_bounded_file(metadata_path, 64 * 1024)
        try:
            metadata = json.loads(metadata_bytes)
        except json.JSONDecodeError as error:
            raise RollbackRejected("backup metadata is invalid") from error
        expected_keys = {
            "schema_version",
            "backup_id",
            "workspace_id",
            "relative_path",
            "operation",
            "existed_before",
            "before_sha256",
            "after_sha256",
        }
        if (
            not isinstance(metadata, dict)
            or set(metadata) != expected_keys
            or metadata["schema_version"] != "1.0"
            or metadata["backup_id"] != canonical
            or not isinstance(metadata["existed_before"], bool)
        ):
            raise RollbackRejected("backup metadata is invalid")
        content = None
        if metadata["existed_before"]:
            content = _read_bounded_file(
                directory / "before.bin",
                MAX_MUTATION_BYTES,
            )
            if _sha256(content) != metadata["before_sha256"]:
                raise RollbackRejected("backup content hash mismatch")
        return metadata, content


def _read_regular_file(target: ResolvedWorkspacePath) -> bytes:
    try:
        path_stat = target.path.lstat()
        if _is_link_or_reparse(target.path, path_stat):
            raise MutationPreconditionFailed("target link is forbidden")
        if not stat.S_ISREG(path_stat.st_mode):
            raise MutationPreconditionFailed("target is not a regular file")
        if path_stat.st_size > MAX_MUTATION_BYTES:
            raise MutationPreconditionFailed("target exceeds mutation limit")
        with target.path.open("rb", buffering=0) as stream:
            opened = os.fstat(stream.fileno())
            content = stream.read(MAX_MUTATION_BYTES + 1)
        repeated = target.path.lstat()
    except OSError as error:
        raise MutationPreconditionFailed("target changed during read") from error
    if (
        len(content) > MAX_MUTATION_BYTES
        or not os.path.samestat(path_stat, opened)
        or not os.path.samestat(opened, repeated)
    ):
        raise MutationPreconditionFailed("target changed during read")
    return content


def _atomic_replace(
    target: ResolvedWorkspacePath,
    content: bytes,
    expected_sha256: str | None,
) -> None:
    parent = target.path.parent
    parent_before = parent.stat(follow_symlinks=False)
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".lva-write-",
            suffix=".partial",
            dir=parent,
        )
        with os.fdopen(descriptor, "wb", buffering=0) as stream:
            stream.write(content)
            os.fsync(stream.fileno())
        if expected_sha256 is None:
            os.link(temporary_name, target.path)
            Path(temporary_name).unlink()
            temporary_name = None
        else:
            current = _read_regular_file(target)
            _require_hash(current, expected_sha256)
            parent_after = parent.stat(follow_symlinks=False)
            if not os.path.samestat(parent_before, parent_after):
                raise MutationPreconditionFailed("target parent changed")
            os.replace(temporary_name, target.path)
            temporary_name = None
    except FileExistsError as error:
        raise MutationPreconditionFailed("target appeared during create") from error
    except OSError as error:
        raise MutationPreconditionFailed("atomic file replacement failed") from error
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _unlink_exact(
    target: ResolvedWorkspacePath,
    expected_sha256: str,
) -> None:
    current = _read_regular_file(target)
    _require_hash(current, expected_sha256)
    try:
        target.path.unlink()
    except OSError as error:
        raise RollbackRejected("created file rollback failed") from error


def _apply_unified_patch(original: str, patch: str) -> str:
    if len(patch.encode("utf-8")) > MAX_MUTATION_BYTES:
        raise PatchRejected("patch exceeds mutation limit")
    newline = "\r\n" if "\r\n" in original else "\n"
    trailing_newline = original.endswith(("\n", "\r"))
    source = original.splitlines()
    patch_lines = patch.splitlines()
    result: list[str] = []
    source_index = 0
    patch_index = 0
    hunk_count = 0
    while patch_index < len(patch_lines):
        line = patch_lines[patch_index]
        if line.startswith(("--- ", "+++ ", "diff ", "index ")):
            patch_index += 1
            continue
        match = _HUNK.match(line)
        if match is None:
            raise PatchRejected("patch contains unsupported syntax")
        hunk_count += 1
        old_start = int(match.group("old_start"))
        old_count = int(match.group("old_count") or "1")
        new_count = int(match.group("new_count") or "1")
        target_index = max(0, old_start - 1)
        if target_index < source_index or target_index > len(source):
            raise PatchRejected("patch hunk location is invalid")
        result.extend(source[source_index:target_index])
        source_index = target_index
        patch_index += 1
        consumed = 0
        produced = 0
        while patch_index < len(patch_lines) and not patch_lines[
            patch_index
        ].startswith("@@ "):
            item = patch_lines[patch_index]
            if item == r"\ No newline at end of file":
                raise PatchRejected("no-newline patch markers are unsupported")
            if not item or item[0] not in {" ", "+", "-"}:
                raise PatchRejected("patch hunk line is invalid")
            marker, text = item[0], item[1:]
            if marker in {" ", "-"}:
                if source_index >= len(source) or source[source_index] != text:
                    raise PatchRejected("patch context does not match target")
                source_index += 1
                consumed += 1
            if marker in {" ", "+"}:
                result.append(text)
                produced += 1
            patch_index += 1
        if consumed != old_count or produced != new_count:
            raise PatchRejected("patch hunk counts do not match")
    if hunk_count == 0:
        raise PatchRejected("patch contains no hunks")
    result.extend(source[source_index:])
    rendered = newline.join(result)
    if trailing_newline:
        rendered += newline
    return rendered


def _bounded_diff(relative_path: str, before: bytes, after: bytes) -> str:
    try:
        before_text = before.decode("utf-8")
        after_text = after.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MutationPreconditionFailed("mutation content is not UTF-8") from error
    diff = "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
        )
    )
    if len(diff.encode("utf-8")) > 2 * MAX_MUTATION_BYTES:
        return diff.encode("utf-8")[: 2 * MAX_MUTATION_BYTES].decode(
            "utf-8",
            errors="ignore",
        )
    return diff


def _read_bounded_file(path: Path, limit: int) -> bytes:
    try:
        path_stat = path.lstat()
        if _is_link_or_reparse(path, path_stat):
            raise RollbackRejected("backup links are forbidden")
        if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_size > limit:
            raise RollbackRejected("backup file is invalid")
        content = path.read_bytes()
    except OSError as error:
        raise RollbackRejected("backup file is unavailable") from error
    if len(content) > limit:
        raise RollbackRejected("backup file exceeds limit")
    return content


def _write_exclusive(path: Path, content: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb", buffering=0) as stream:
            stream.write(content)
            os.fsync(stream.fileno())
    except OSError as error:
        raise RollbackRejected("backup file cannot be written") from error


def _assert_safe_directory(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            current_stat = current.lstat()
        except OSError as error:
            raise RollbackRejected("backup directory is unavailable") from error
        if _is_link_or_reparse(current, current_stat):
            raise RollbackRejected("backup directory links are forbidden")
    if not path.is_dir():
        raise RollbackRejected("backup path is not a directory")


def _sha256(content: bytes | None) -> str:
    return hashlib.sha256(content or b"").hexdigest()


def _require_hash(content: bytes, expected_sha256: str) -> None:
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[a-f0-9]{64}",
        expected_sha256,
    ):
        raise MutationPreconditionFailed("expected hash is invalid")
    if _sha256(content) != expected_sha256:
        raise MutationPreconditionFailed("target hash precondition failed")


def _canonical_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise RollbackRejected("backup identifier is invalid") from error
    if str(parsed) != value.lower():
        raise RollbackRejected("backup identifier is not canonical")
    return str(parsed)
