"""Runtime workspace allowlist and path-boundary enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path, PureWindowsPath
import re
import stat
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from .errors import (
    WorkspaceConfigurationError,
    WorkspaceNotFound,
    WorkspacePathNotFound,
    WorkspacePathRejected,
    WorkspaceTypeMismatch,
)


_WORKSPACE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")
_WINDOWS_RESERVED = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class WorkspacePlatform(str, Enum):
    WINDOWS_NATIVE = "windows_native"
    WSL_LINUX = "wsl_linux"


class WorkspaceAccess(str, Enum):
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"


@dataclass(frozen=True, slots=True)
class Workspace:
    workspace_id: str
    platform: WorkspacePlatform
    root: Path
    access: WorkspaceAccess
    git_enabled: bool = False

    def __post_init__(self) -> None:
        if not _WORKSPACE_ID.fullmatch(self.workspace_id):
            raise WorkspaceConfigurationError(
                f"invalid workspace id: {self.workspace_id!r}"
            )
        raw_root = Path(self.root)
        if not raw_root.is_absolute():
            raise WorkspaceConfigurationError(
                f"{self.workspace_id}: root must be absolute"
            )
        try:
            root_stat = raw_root.lstat()
        except OSError as error:
            raise WorkspaceConfigurationError(
                f"{self.workspace_id}: root is unavailable"
            ) from error
        if _is_link_or_reparse(raw_root, root_stat):
            raise WorkspaceConfigurationError(
                f"{self.workspace_id}: root cannot be a link or reparse point"
            )
        if not stat.S_ISDIR(root_stat.st_mode):
            raise WorkspaceConfigurationError(
                f"{self.workspace_id}: root is not a directory"
            )
        resolved = raw_root.resolve(strict=True)
        if resolved == Path(resolved.anchor):
            raise WorkspaceConfigurationError(
                f"{self.workspace_id}: filesystem root is too broad"
            )
        object.__setattr__(self, "root", resolved)


@dataclass(frozen=True, slots=True)
class ResolvedWorkspacePath:
    workspace: Workspace
    relative_path: str
    path: Path


class WorkspaceRegistry:
    def __init__(self, workspaces: Iterable[Workspace]) -> None:
        indexed: dict[str, Workspace] = {}
        for workspace in workspaces:
            if workspace.workspace_id in indexed:
                raise WorkspaceConfigurationError(
                    f"duplicate workspace id: {workspace.workspace_id}"
                )
            indexed[workspace.workspace_id] = workspace
        self._workspaces: Mapping[str, Workspace] = MappingProxyType(indexed)

    def __len__(self) -> int:
        return len(self._workspaces)

    def get(self, workspace_id: str) -> Workspace:
        try:
            return self._workspaces[workspace_id]
        except KeyError as error:
            raise WorkspaceNotFound(workspace_id) from error

    def normalize_relative(
        self,
        workspace_id: str,
        relative_path: str,
        *,
        allow_root: bool = True,
    ) -> str:
        workspace = self.get(workspace_id)
        parts = _parse_relative_path(relative_path, workspace.platform)
        if not parts:
            if allow_root:
                return "."
            raise WorkspacePathRejected("workspace root is not a file path")
        return "/".join(parts)

    def resolve_existing(
        self,
        workspace_id: str,
        relative_path: str,
        *,
        expected_kind: Literal["any", "file", "directory"] = "any",
    ) -> ResolvedWorkspacePath:
        workspace = self.get(workspace_id)
        parts = _parse_relative_path(relative_path, workspace.platform)
        candidate = workspace.root.joinpath(*parts)
        _assert_no_link_segments(workspace.root, candidate)
        try:
            resolved = candidate.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError) as error:
            raise WorkspacePathNotFound(relative_path) from error
        except OSError as error:
            raise WorkspacePathRejected(relative_path) from error

        if not resolved.is_relative_to(workspace.root):
            raise WorkspacePathRejected("resolved path escapes workspace")
        _assert_no_link_segments(workspace.root, candidate)

        try:
            path_stat = candidate.stat(follow_symlinks=False)
        except OSError as error:
            raise WorkspacePathNotFound(relative_path) from error
        if expected_kind == "file" and not stat.S_ISREG(path_stat.st_mode):
            raise WorkspaceTypeMismatch("expected a regular file")
        if expected_kind == "directory" and not stat.S_ISDIR(path_stat.st_mode):
            raise WorkspaceTypeMismatch("expected a directory")

        normalized = "." if not parts else "/".join(parts)
        return ResolvedWorkspacePath(
            workspace=workspace,
            relative_path=normalized,
            path=resolved,
        )

    def resolve_file_target(
        self,
        workspace_id: str,
        relative_path: str,
    ) -> ResolvedWorkspacePath:
        workspace = self.get(workspace_id)
        if workspace.access is not WorkspaceAccess.READ_WRITE:
            raise WorkspacePathRejected("workspace is not writable")
        normalized = self.normalize_relative(
            workspace_id,
            relative_path,
            allow_root=False,
        )
        parts = tuple(normalized.split("/"))
        parent_relative = "/".join(parts[:-1]) or "."
        parent = self.resolve_existing(
            workspace_id,
            parent_relative,
            expected_kind="directory",
        )
        candidate = parent.path / parts[-1]
        try:
            candidate_stat = candidate.lstat()
        except FileNotFoundError:
            candidate_stat = None
        except OSError as error:
            raise WorkspacePathRejected(relative_path) from error
        if candidate_stat is not None:
            if _is_link_or_reparse(candidate, candidate_stat):
                raise WorkspacePathRejected("links and reparse points are forbidden")
            if not stat.S_ISREG(candidate_stat.st_mode):
                raise WorkspaceTypeMismatch("expected a regular file target")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(workspace.root):
                raise WorkspacePathRejected("resolved path escapes workspace")
            candidate = resolved
        return ResolvedWorkspacePath(
            workspace=workspace,
            relative_path=normalized,
            path=candidate,
        )


def _parse_relative_path(
    value: str,
    platform: WorkspacePlatform,
) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise WorkspacePathRejected("relative path must contain 1-1024 characters")
    if "\x00" in value:
        raise WorkspacePathRejected("NUL is forbidden")

    windows_view = PureWindowsPath(value)
    if windows_view.is_absolute() or windows_view.drive or windows_view.anchor:
        raise WorkspacePathRejected("absolute or drive-relative path is forbidden")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/"):
        raise WorkspacePathRejected("absolute path is forbidden")
    if normalized == ".":
        return ()

    parts = tuple(normalized.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise WorkspacePathRejected("empty, dot, and traversal segments are forbidden")

    if platform is WorkspacePlatform.WINDOWS_NATIVE:
        for part in parts:
            if ":" in part:
                raise WorkspacePathRejected("Windows alternate streams are forbidden")
            if part.endswith((" ", ".")):
                raise WorkspacePathRejected(
                    "Windows trailing spaces and dots are forbidden"
                )
            device_name = part.rstrip(" .").split(".", 1)[0].casefold()
            if device_name in _WINDOWS_RESERVED:
                raise WorkspacePathRejected("Windows reserved names are forbidden")
    return parts


def _assert_no_link_segments(root: Path, candidate: Path) -> None:
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise WorkspacePathRejected("lexical path escapes workspace") from error

    current = root
    for part in relative.parts:
        current = current / part
        try:
            current_stat = current.lstat()
        except FileNotFoundError as error:
            raise WorkspacePathNotFound(str(relative)) from error
        except OSError as error:
            raise WorkspacePathRejected(str(relative)) from error
        if _is_link_or_reparse(current, current_stat):
            raise WorkspacePathRejected("links and reparse points are forbidden")


def _is_link_or_reparse(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode) or path.is_symlink():
        return True
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)
