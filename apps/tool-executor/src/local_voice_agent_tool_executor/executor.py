"""Fail-closed dispatcher for the supported filesystem and Git tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .browser import BROWSER_TOOLS, BrowserAutomation
from .contracts import (
    FILESYSTEM_MUTATION_TOOLS,
    FILESYSTEM_READ_TOOLS,
    ReadToolContracts,
)
from .errors import (
    GitWorkspaceRejected,
    MutationPreconditionFailed,
    ToolNotSupported,
)
from .filesystem import ReadOnlyFilesystem
from .git import ReadOnlyGit
from .mutations import FileMutationExecutor
from .system import SYSTEM_TOOLS, WindowsSystemInspector
from .windows_ui import UI_TOOLS, WindowsUiAutomation
from .workspaces import WorkspaceRegistry


class ReadOnlyToolExecutor:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRegistry,
        definitions_dir: Path,
        definition_schema_path: Path,
        git_executable: Path | None = None,
        backup_root: Path | None = None,
        browser: BrowserAutomation | None = None,
        windows_ui: WindowsUiAutomation | None = None,
        system_inspector: WindowsSystemInspector | None = None,
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
        self._mutations = (
            FileMutationExecutor(
                workspaces=workspaces,
                backup_root=backup_root,
            )
            if backup_root is not None
            else None
        )
        self._browser = browser
        self._windows_ui = windows_ui
        self._system = system_inspector

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = dict(arguments)
        self._contracts.validate(tool_name, normalized)
        if tool_name in FILESYSTEM_READ_TOOLS:
            handler = getattr(self._filesystem, tool_name)
            result = handler(**normalized)
        elif tool_name in FILESYSTEM_MUTATION_TOOLS:
            if self._mutations is None or execution_id is None:
                raise MutationPreconditionFailed(
                    "mutation adapter is not configured"
                )
            handler = getattr(self._mutations, tool_name)
            result = handler(execution_id=execution_id, **normalized)
        elif tool_name in BROWSER_TOOLS:
            if self._browser is None:
                raise ToolNotSupported("browser adapter is not configured")
            result = self._browser.execute(tool_name, normalized)
        elif tool_name in UI_TOOLS:
            if self._windows_ui is None:
                raise ToolNotSupported("Windows UI adapter is not configured")
            result = self._windows_ui.execute(tool_name, normalized)
        elif tool_name in SYSTEM_TOOLS:
            if self._system is None:
                raise ToolNotSupported(
                    "Windows system inspection adapter is not configured"
                )
            result = self._system.execute(tool_name, normalized)
        else:
            if self._git is None:
                raise GitWorkspaceRejected("Git adapter is not configured")
            handler = getattr(self._git, tool_name)
            result = handler(**normalized)
        return {
            "tool_name": tool_name,
            "status": "succeeded",
            "result": result,
        }

    def validate_arguments(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> str:
        return self._contracts.validate(tool_name, arguments)

    def definition_sha256(self, tool_name: str) -> str:
        return self._contracts.definition_sha256(tool_name)

    def risk_level(self, tool_name: str) -> int:
        return self._contracts.risk_level(tool_name)

    def idempotency(self, tool_name: str) -> str:
        return self._contracts.idempotency(tool_name)
