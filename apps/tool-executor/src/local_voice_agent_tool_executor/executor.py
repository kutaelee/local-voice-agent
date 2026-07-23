"""Fail-closed dispatcher for the supported Level 0 filesystem tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .contracts import FILESYSTEM_READ_TOOLS, ReadToolContracts
from .errors import GitWorkspaceRejected
from .filesystem import ReadOnlyFilesystem
from .git import ReadOnlyGit
from .workspaces import WorkspaceRegistry


class ReadOnlyToolExecutor:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRegistry,
        definitions_dir: Path,
        definition_schema_path: Path,
        git_executable: Path | None = None,
    ) -> None:
        self._contracts = ReadToolContracts.load(
            definitions_dir=definitions_dir,
            definition_schema_path=definition_schema_path,
        )
        self._filesystem = ReadOnlyFilesystem(workspaces)
        self._git = (
            ReadOnlyGit(
                workspaces=workspaces,
                contracts=self._contracts,
                git_executable=git_executable,
            )
            if git_executable is not None
            else None
        )

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(arguments)
        self._contracts.validate(tool_name, normalized)
        if tool_name in FILESYSTEM_READ_TOOLS:
            handler = getattr(self._filesystem, tool_name)
        else:
            if self._git is None:
                raise GitWorkspaceRejected("Git adapter is not configured")
            handler = getattr(self._git, tool_name)
        return {
            "tool_name": tool_name,
            "status": "succeeded",
            "result": handler(**normalized),
        }

    def validate_arguments(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> str:
        return self._contracts.validate(tool_name, arguments)

    def definition_sha256(self, tool_name: str) -> str:
        return self._contracts.definition_sha256(tool_name)
