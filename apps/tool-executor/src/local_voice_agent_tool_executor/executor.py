"""Fail-closed dispatcher for the supported Level 0 filesystem tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .contracts import ReadToolContracts
from .filesystem import ReadOnlyFilesystem
from .workspaces import WorkspaceRegistry


class ReadOnlyToolExecutor:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRegistry,
        definitions_dir: Path,
        definition_schema_path: Path,
    ) -> None:
        self._contracts = ReadToolContracts.load(
            definitions_dir=definitions_dir,
            definition_schema_path=definition_schema_path,
        )
        self._filesystem = ReadOnlyFilesystem(workspaces)

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(arguments)
        self._contracts.validate(tool_name, normalized)
        handler = getattr(self._filesystem, tool_name)
        return {
            "tool_name": tool_name,
            "status": "succeeded",
            "result": handler(**normalized),
        }
