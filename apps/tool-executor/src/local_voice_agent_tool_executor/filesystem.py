"""Bounded read-only filesystem adapter."""

from __future__ import annotations

from contextlib import contextmanager
import codecs
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import stat
from typing import Any, BinaryIO, Iterator

from .errors import (
    TextDecodingError,
    WorkspacePathChanged,
    WorkspacePathRejected,
    WorkspaceTypeMismatch,
)
from .workspaces import (
    ResolvedWorkspacePath,
    WorkspaceRegistry,
    _is_link_or_reparse,
)


MAX_READ_BYTES = 1_048_576
MAX_DIRECTORY_ENTRIES_SCANNED = 20_000
MAX_SEARCH_FILE_BYTES = 1_048_576
HASH_CHUNK_BYTES = 1_048_576


class ReadOnlyFilesystem:
    def __init__(self, workspaces: WorkspaceRegistry) -> None:
        self._workspaces = workspaces

    def list_files(
        self,
        *,
        workspace_id: str,
        relative_path: str = ".",
        max_depth: int = 2,
        limit: int = 500,
    ) -> dict[str, Any]:
        root = self._workspaces.resolve_existing(
            workspace_id,
            relative_path,
            expected_kind="directory",
        )
        entries, scan_truncated = self._collect_entries(
            root,
            max_depth=max_depth,
            scan_limit=limit,
        )
        return {
            "workspace_id": workspace_id,
            "relative_path": root.relative_path,
            "entries": entries,
            "truncated": scan_truncated,
        }

    def search_files(
        self,
        *,
        workspace_id: str,
        query: str,
        relative_path: str = ".",
        mode: str = "name",
        max_results: int = 100,
    ) -> dict[str, Any]:
        root = self._workspaces.resolve_existing(
            workspace_id,
            relative_path,
            expected_kind="directory",
        )
        entries, scan_truncated = self._collect_entries(
            root,
            max_depth=8,
            scan_limit=MAX_DIRECTORY_ENTRIES_SCANNED,
        )
        folded_query = query.casefold()
        matches: list[dict[str, Any]] = []
        skipped_non_utf8 = 0
        skipped_oversized = 0

        for entry in entries:
            if entry["kind"] != "file":
                continue
            if mode == "name":
                if folded_query in Path(entry["relative_path"]).name.casefold():
                    matches.append({"relative_path": entry["relative_path"]})
            else:
                resolved = self._workspaces.resolve_existing(
                    workspace_id,
                    entry["relative_path"],
                    expected_kind="file",
                )
                if entry["size_bytes"] > MAX_SEARCH_FILE_BYTES:
                    skipped_oversized += 1
                    continue
                try:
                    with _open_verified(self._workspaces, resolved) as stream:
                        text = stream.read(MAX_SEARCH_FILE_BYTES).decode("utf-8")
                except UnicodeDecodeError:
                    skipped_non_utf8 += 1
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if folded_query in line.casefold():
                        matches.append(
                            {
                                "relative_path": entry["relative_path"],
                                "line": line_number,
                                "snippet": line[:512],
                            }
                        )
                        if len(matches) >= max_results:
                            break
            if len(matches) >= max_results:
                break

        return {
            "workspace_id": workspace_id,
            "relative_path": root.relative_path,
            "mode": mode,
            "matches": matches,
            "truncated": len(matches) >= max_results or scan_truncated,
            "scanned_entries": len(entries),
            "skipped_non_utf8": skipped_non_utf8,
            "skipped_oversized": skipped_oversized,
        }

    def read_file(
        self,
        *,
        workspace_id: str,
        relative_path: str,
        max_bytes: int = 262_144,
    ) -> dict[str, Any]:
        _require_max_bytes(max_bytes)
        resolved = self._workspaces.resolve_existing(
            workspace_id,
            relative_path,
            expected_kind="file",
        )
        with _open_verified(self._workspaces, resolved) as stream:
            size_bytes = os.fstat(stream.fileno()).st_size
            data = stream.read(max_bytes + 1)
        truncated = len(data) > max_bytes
        bounded = data[:max_bytes]
        content = _decode_bounded_utf8(bounded, truncated=truncated)
        returned_bytes = len(content.encode("utf-8"))
        return {
            "workspace_id": workspace_id,
            "relative_path": resolved.relative_path,
            "content": content,
            "size_bytes": size_bytes,
            "returned_bytes": returned_bytes,
            "truncated": truncated,
        }

    def read_file_range(
        self,
        *,
        workspace_id: str,
        relative_path: str,
        start_line: int,
        end_line: int,
        max_bytes: int = 262_144,
    ) -> dict[str, Any]:
        _require_max_bytes(max_bytes)
        if end_line < start_line:
            raise WorkspacePathRejected("end_line must be greater than start_line")
        resolved = self._workspaces.resolve_existing(
            workspace_id,
            relative_path,
            expected_kind="file",
        )
        selected = bytearray()
        last_line = start_line - 1
        truncated = False
        with _open_verified(self._workspaces, resolved) as stream:
            for line_number, line in enumerate(stream, start=1):
                if line_number < start_line:
                    continue
                if line_number > end_line:
                    break
                remaining = max_bytes - len(selected)
                if len(line) > remaining:
                    selected.extend(line[:remaining])
                    last_line = line_number
                    truncated = True
                    break
                selected.extend(line)
                last_line = line_number
        content = _decode_bounded_utf8(bytes(selected), truncated=truncated)
        return {
            "workspace_id": workspace_id,
            "relative_path": resolved.relative_path,
            "start_line": start_line,
            "requested_end_line": end_line,
            "last_line": last_line,
            "content": content,
            "returned_bytes": len(content.encode("utf-8")),
            "truncated": truncated,
        }

    def list_recent_files(
        self,
        *,
        workspace_id: str,
        relative_path: str = ".",
        within_minutes: int = 10_080,
        limit: int = 100,
    ) -> dict[str, Any]:
        root = self._workspaces.resolve_existing(
            workspace_id,
            relative_path,
            expected_kind="directory",
        )
        entries, scan_truncated = self._collect_entries(
            root,
            max_depth=8,
            scan_limit=MAX_DIRECTORY_ENTRIES_SCANNED,
        )
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
        recent = [
            entry
            for entry in entries
            if entry["kind"] == "file"
            and datetime.fromisoformat(entry["modified_at"]) >= cutoff
        ]
        recent.sort(
            key=lambda entry: (entry["modified_at"], entry["relative_path"]),
            reverse=True,
        )
        return {
            "workspace_id": workspace_id,
            "relative_path": root.relative_path,
            "files": recent[:limit],
            "truncated": len(recent) > limit or scan_truncated,
            "scanned_entries": len(entries),
        }

    def calculate_hash(
        self,
        *,
        workspace_id: str,
        relative_path: str,
        algorithm: str = "sha256",
    ) -> dict[str, Any]:
        if algorithm != "sha256":
            raise WorkspacePathRejected("only sha256 is supported")
        resolved = self._workspaces.resolve_existing(
            workspace_id,
            relative_path,
            expected_kind="file",
        )
        digest = hashlib.sha256()
        with _open_verified(self._workspaces, resolved) as stream:
            size_bytes = os.fstat(stream.fileno()).st_size
            while chunk := stream.read(HASH_CHUNK_BYTES):
                digest.update(chunk)
        return {
            "workspace_id": workspace_id,
            "relative_path": resolved.relative_path,
            "algorithm": "sha256",
            "sha256": digest.hexdigest(),
            "size_bytes": size_bytes,
        }

    def _collect_entries(
        self,
        root: ResolvedWorkspacePath,
        *,
        max_depth: int,
        scan_limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        entries: list[dict[str, Any]] = []
        pending: list[tuple[Path, int]] = [(root.path, 0)]
        truncated = False

        while pending:
            directory, parent_depth = pending.pop()
            relative_directory = directory.relative_to(root.workspace.root).as_posix()
            self._workspaces.resolve_existing(
                root.workspace.workspace_id,
                relative_directory or ".",
                expected_kind="directory",
            )
            try:
                children = sorted(
                    os.scandir(directory),
                    key=lambda entry: entry.name.casefold(),
                    reverse=True,
                )
            except OSError as error:
                raise WorkspacePathRejected("directory changed during scan") from error

            for child in children:
                try:
                    child_stat = child.stat(follow_symlinks=False)
                except OSError:
                    continue
                child_path = Path(child.path)
                relative = child_path.relative_to(root.workspace.root).as_posix()
                depth = parent_depth + 1
                if _is_link_or_reparse(child_path, child_stat):
                    kind = "blocked_link"
                elif stat.S_ISDIR(child_stat.st_mode):
                    kind = "directory"
                elif stat.S_ISREG(child_stat.st_mode):
                    kind = "file"
                else:
                    kind = "other"
                entries.append(
                    {
                        "relative_path": relative,
                        "kind": kind,
                        "size_bytes": child_stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            child_stat.st_mtime,
                            tz=timezone.utc,
                        ).isoformat(),
                    }
                )
                if len(entries) >= scan_limit:
                    truncated = True
                    return entries, truncated
                if kind == "directory" and depth < max_depth:
                    pending.append((child_path, depth))
        entries.sort(key=lambda entry: entry["relative_path"].casefold())
        return entries, truncated


@contextmanager
def _open_verified(
    registry: WorkspaceRegistry,
    resolved: ResolvedWorkspacePath,
) -> Iterator[BinaryIO]:
    try:
        pre_open = resolved.path.stat(follow_symlinks=False)
        stream = resolved.path.open("rb", buffering=0)
    except OSError as error:
        raise WorkspacePathChanged(resolved.relative_path) from error
    try:
        opened = os.fstat(stream.fileno())
        repeated = registry.resolve_existing(
            resolved.workspace.workspace_id,
            resolved.relative_path,
            expected_kind="file",
        )
        post_open = repeated.path.stat(follow_symlinks=False)
        if repeated.path != resolved.path:
            raise WorkspacePathChanged(resolved.relative_path)
        if not os.path.samestat(pre_open, opened) or not os.path.samestat(
            opened,
            post_open,
        ):
            raise WorkspacePathChanged(resolved.relative_path)
        if not stat.S_ISREG(opened.st_mode):
            raise WorkspaceTypeMismatch("expected a regular file")
        yield stream
    finally:
        stream.close()


def _require_max_bytes(max_bytes: int) -> None:
    if not 1 <= max_bytes <= MAX_READ_BYTES:
        raise WorkspacePathRejected("max_bytes is outside the executor bound")


def _decode_bounded_utf8(data: bytes, *, truncated: bool) -> str:
    try:
        if not truncated:
            return data.decode("utf-8")
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        return decoder.decode(data, final=False)
    except UnicodeDecodeError as error:
        raise TextDecodingError("file is not valid UTF-8") from error
