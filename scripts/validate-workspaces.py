#!/usr/bin/env python3
"""Validate workspace roots and registered-command configuration."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from jsonschema import Draft202012Validator
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_GLOB_CHARS = frozenset("*?[")
PROTECTED_WINDOWS_WRITE_ROOTS = (
    PureWindowsPath("D:/"),
    PureWindowsPath("E:/backup"),
    PureWindowsPath("E:/transfer"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def is_relative_to(path: PureWindowsPath, parent: PureWindowsPath) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_windows_root(root: str, access: str) -> None:
    path = PureWindowsPath(root)
    require(path.is_absolute() and bool(path.drive), f"not absolute: {root}")
    require(not any(char in root for char in FORBIDDEN_GLOB_CHARS), f"glob: {root}")
    require(".." not in path.parts, f"traversal: {root}")
    require(len(path.parts) > 1, f"drive root: {root}")
    require(
        str(path).casefold() != r"c:\users\kutae",
        f"user profile root: {root}",
    )
    if access == "read_write":
        folded = PureWindowsPath(str(path).casefold())
        for protected in PROTECTED_WINDOWS_WRITE_ROOTS:
            protected_folded = PureWindowsPath(str(protected).casefold())
            require(
                not is_relative_to(folded, protected_folded),
                f"protected write root: {root}",
            )


def validate_wsl_root(root: str) -> None:
    path = PurePosixPath(root)
    require(path.is_absolute(), f"not absolute: {root}")
    require(not any(char in root for char in FORBIDDEN_GLOB_CHARS), f"glob: {root}")
    require(".." not in path.parts, f"traversal: {root}")
    require(len(path.parts) >= 4, f"broad WSL root: {root}")
    require(
        path.parts[1] == "home" and path.parts[3] == "src",
        f"Linux workspace must be under /home/<user>/src: {root}",
    )


def validate_semantics(config: dict) -> None:
    workspace_ids: set[str] = set()
    for workspace in config["workspaces"]:
        workspace_id = workspace["id"]
        require(workspace_id not in workspace_ids, f"duplicate workspace: {workspace_id}")
        workspace_ids.add(workspace_id)
        if workspace["platform"] == "windows_native":
            validate_windows_root(workspace["root"], workspace["access"])
        else:
            validate_wsl_root(workspace["root"])

        profile_ids: set[str] = set()
        for profile in workspace["command_profiles"]:
            profile_id = profile["id"]
            require(
                profile_id not in profile_ids,
                f"{workspace_id}: duplicate command profile {profile_id}",
            )
            profile_ids.add(profile_id)
            cwd = PurePosixPath(profile["working_directory_relative"])
            require(not cwd.is_absolute(), f"{workspace_id}: absolute command cwd")
            require(".." not in cwd.parts, f"{workspace_id}: command cwd traversal")


def must_reject(config: dict, name: str) -> None:
    try:
        validate_semantics(config)
    except ValueError:
        return
    raise ValueError(f"{name} was accepted")


def main() -> int:
    schema = json.loads(
        (REPO_ROOT / "configs/schemas/workspaces.schema.json").read_text(
            encoding="utf-8"
        )
    )
    config = yaml.safe_load(
        (REPO_ROOT / "configs/workspaces.yaml").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(config)
    validate_semantics(config)

    def sample(root: str, platform: str = "windows_native") -> dict:
        return {
            "schema_version": "1.0",
            "workspaces": [
                {
                    "id": "invalid",
                    "platform": platform,
                    "root": root,
                    "access": "read_write",
                    "git": False,
                    "command_profiles": [],
                }
            ],
        }

    must_reject(sample("C:/"), "drive root")
    must_reject(sample("C:/Users/kutae"), "user profile root")
    must_reject(sample("D:/active"), "backup drive write root")
    must_reject(sample("E:/backup/project"), "protected backup write root")
    must_reject(sample("C:/Dev/*"), "wildcard root")
    must_reject(sample("/mnt/c/project", "wsl_linux"), "WSL mounted drive root")

    print(
        json.dumps(
            {
                "configured_workspaces": len(config["workspaces"]),
                "invalid_root_cases_rejected": 6,
                "status": "workspace_config_validation_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
