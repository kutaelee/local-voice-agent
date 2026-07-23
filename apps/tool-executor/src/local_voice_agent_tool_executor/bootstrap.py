"""Environment composition root for the standalone Tool Executor process."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
from typing import Any

from fastapi import FastAPI
from jsonschema import Draft202012Validator
import yaml

from .api import ExecutorApiSettings, create_app
from .audit import AuditEvidenceStore
from .browser import BrowserAutomation
from .errors import WorkspaceConfigurationError
from .executor import ReadOnlyToolExecutor
from .service import BoundExecutionService
from .system import WindowsSystemInspector
from .workspaces import (
    Workspace,
    WorkspaceAccess,
    WorkspacePlatform,
    WorkspaceRegistry,
)
from .windows_ui import WindowsUiAutomation


def create_app_from_environment() -> FastAPI:
    token = _required_environment("LVA_TOOL_EXECUTOR_TOKEN")
    repo_root = Path(_required_environment("LVA_REPO_ROOT"))
    audit_log = Path(_required_environment("LVA_TOOL_EXECUTOR_AUDIT_LOG"))
    evidence_dir = Path(
        _required_environment("LVA_TOOL_EXECUTOR_EVIDENCE_DIR")
    )
    backup_dir = Path(
        _required_environment("LVA_TOOL_EXECUTOR_BACKUP_DIR")
    )
    if not repo_root.is_absolute() or not repo_root.is_dir():
        raise RuntimeError("LVA_REPO_ROOT must be an existing absolute directory")

    workspaces = load_workspaces(
        config_path=repo_root / "configs/workspaces.yaml",
        schema_path=repo_root / "configs/schemas/workspaces.schema.json",
    )
    git_executable: Path | None = None
    if any(workspace.git_enabled for workspace in workspaces):
        discovered = shutil.which("git")
        if discovered is None:
            raise RuntimeError("registered Git workspaces require git")
        git_executable = Path(discovered).resolve(strict=True)

    executor = ReadOnlyToolExecutor(
        workspaces=WorkspaceRegistry(workspaces),
        definitions_dir=repo_root / "packages/tool-registry/definitions",
        definition_schema_path=(
            repo_root / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
        git_executable=git_executable,
        backup_root=backup_dir,
        browser=(
            BrowserAutomation(
                artifact_root=evidence_dir / "computer-use" / "browser",
            )
            if os.name == "nt"
            and os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
            else None
        ),
        windows_ui=(
            WindowsUiAutomation(
                artifact_root=evidence_dir / "computer-use" / "windows-ui",
            )
            if os.name == "nt"
            else None
        ),
        system_inspector=WindowsSystemInspector() if os.name == "nt" else None,
    )
    service = BoundExecutionService(
        executor=executor,
        audit_store=AuditEvidenceStore(
            audit_log=audit_log,
            evidence_dir=evidence_dir,
        ),
    )
    return create_app(
        settings=ExecutorApiSettings(ipc_token=token),
        service=service,
    )


def load_workspaces(
    *,
    config_path: Path,
    schema_path: Path,
) -> tuple[Workspace, ...]:
    config = _read_yaml_object(config_path)
    schema = _read_json_object(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(config),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise WorkspaceConfigurationError(
            f"workspace config schema invalid at {list(errors[0].absolute_path)}"
        )

    host_platform = (
        WorkspacePlatform.WINDOWS_NATIVE
        if os.name == "nt"
        else WorkspacePlatform.WSL_LINUX
    )
    loaded: list[Workspace] = []
    seen: set[str] = set()
    for record in config["workspaces"]:
        workspace_id = record["id"]
        if workspace_id in seen:
            raise WorkspaceConfigurationError(
                f"duplicate workspace id: {workspace_id}"
            )
        seen.add(workspace_id)
        platform = WorkspacePlatform(record["platform"])
        _validate_root_policy(
            root=record["root"],
            platform=platform,
            access=WorkspaceAccess(record["access"]),
        )
        if platform is not host_platform:
            continue
        loaded.append(
            Workspace(
                workspace_id=workspace_id,
                platform=platform,
                root=Path(record["root"]),
                access=WorkspaceAccess(record["access"]),
                git_enabled=record["git"],
            )
        )
    return tuple(loaded)


def _validate_root_policy(
    *,
    root: str,
    platform: WorkspacePlatform,
    access: WorkspaceAccess,
) -> None:
    if any(character in root for character in "*?[") or "\x00" in root:
        raise WorkspaceConfigurationError("workspace root contains unsafe syntax")
    if platform is WorkspacePlatform.WINDOWS_NATIVE:
        path = PureWindowsPath(root)
        if not path.is_absolute() or not path.drive or ".." in path.parts:
            raise WorkspaceConfigurationError("invalid Windows workspace root")
        if len(path.parts) <= 1:
            raise WorkspaceConfigurationError("Windows drive root is forbidden")
        folded = str(path).casefold().rstrip("\\/")
        user_profile = os.environ.get("USERPROFILE")
        if (
            user_profile
            and folded
            == str(PureWindowsPath(user_profile)).casefold().rstrip("\\/")
        ):
            raise WorkspaceConfigurationError("user profile root is forbidden")
        if access is WorkspaceAccess.READ_WRITE:
            protected = (
                PureWindowsPath("D:/"),
                PureWindowsPath("E:/backup"),
                PureWindowsPath("E:/transfer"),
            )
            for protected_root in protected:
                try:
                    path.relative_to(protected_root)
                except ValueError:
                    continue
                raise WorkspaceConfigurationError(
                    "protected Windows write root is forbidden"
                )
        return

    path = PurePosixPath(root)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or len(path.parts) < 4
        or path.parts[1] != "home"
        or path.parts[3] != "src"
    ):
        raise WorkspaceConfigurationError(
            "WSL workspace must be under /home/<user>/src"
        )


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _read_yaml_object(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise WorkspaceConfigurationError(
            f"cannot read workspace config: {path}"
        ) from error
    if not isinstance(value, dict):
        raise WorkspaceConfigurationError("workspace config must be an object")
    return value


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkspaceConfigurationError(
            f"cannot read workspace schema: {path}"
        ) from error
    if not isinstance(value, dict):
        raise WorkspaceConfigurationError("workspace schema must be an object")
    return value
