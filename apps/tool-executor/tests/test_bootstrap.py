from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from local_voice_agent_tool_executor.bootstrap import load_workspaces
from local_voice_agent_tool_executor.errors import WorkspaceConfigurationError
from local_voice_agent_tool_executor.workspaces import WorkspaceAccess


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA = REPO_ROOT / "configs/schemas/workspaces.schema.json"


def write_config(path: Path, workspaces: list[dict]) -> None:
    path.write_text(
        yaml.safe_dump(
            {"schema_version": "1.0", "workspaces": workspaces},
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def record(*, workspace_id: str, root: str, platform: str) -> dict:
    return {
        "id": workspace_id,
        "platform": platform,
        "root": root,
        "access": "read_only",
        "git": False,
        "command_profiles": [],
    }


def test_checked_in_workspace_config_is_host_scoped() -> None:
    loaded = load_workspaces(
        config_path=REPO_ROOT / "configs/workspaces.yaml",
        schema_path=SCHEMA,
    )
    if os.name == "nt":
        assert tuple(workspace.workspace_id for workspace in loaded) == (
            "local_voice_agent",
        )
        assert all(
            workspace.access is WorkspaceAccess.READ_ONLY
            for workspace in loaded
        )
    else:
        assert loaded == ()


def test_loader_accepts_only_current_host_platform(
    tmp_path: Path,
) -> None:
    config = tmp_path / "workspaces.yaml"
    created_wsl_root: Path | None = None
    if os.name == "nt":
        current = record(
            workspace_id="current",
            root=str(tmp_path / "current"),
            platform="windows_native",
        )
        other = record(
            workspace_id="other",
            root="/home/test/src/other",
            platform="wsl_linux",
        )
    else:
        current_root = Path.home() / "src" / f"lva-test-{tmp_path.name}"
        created_wsl_root = current_root
        current = record(
            workspace_id="current",
            root=str(current_root),
            platform="wsl_linux",
        )
        other = record(
            workspace_id="other",
            root="C:/Dev/Repos/other",
            platform="windows_native",
        )
    Path(current["root"]).mkdir(parents=True)
    write_config(config, [current, other])

    try:
        loaded = load_workspaces(config_path=config, schema_path=SCHEMA)
    finally:
        if created_wsl_root is not None:
            created_wsl_root.rmdir()

    assert tuple(workspace.workspace_id for workspace in loaded) == ("current",)


@pytest.mark.parametrize(
    ("root", "platform"),
    [
        ("C:/", "windows_native"),
        ("C:/Dev/*", "windows_native"),
        ("/mnt/c/project", "wsl_linux"),
        ("/home/user/other/project", "wsl_linux"),
    ],
)
def test_loader_rejects_broad_or_noncanonical_roots(
    tmp_path: Path,
    root: str,
    platform: str,
) -> None:
    config = tmp_path / "workspaces.yaml"
    write_config(
        config,
        [record(workspace_id="unsafe", root=root, platform=platform)],
    )
    with pytest.raises(WorkspaceConfigurationError):
        load_workspaces(config_path=config, schema_path=SCHEMA)


def test_loader_rejects_duplicate_ids_even_across_platforms(
    tmp_path: Path,
) -> None:
    config = tmp_path / "workspaces.yaml"
    write_config(
        config,
        [
            record(
                workspace_id="duplicate",
                root="C:/Dev/Repos/one",
                platform="windows_native",
            ),
            record(
                workspace_id="duplicate",
                root="/home/user/src/two",
                platform="wsl_linux",
            ),
        ],
    )
    with pytest.raises(WorkspaceConfigurationError):
        load_workspaces(config_path=config, schema_path=SCHEMA)
