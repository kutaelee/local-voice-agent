from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from local_voice_agent_tool_executor.errors import (
    WorkspaceConfigurationError,
    WorkspaceNotFound,
    WorkspacePathRejected,
    WorkspaceTypeMismatch,
)
from local_voice_agent_tool_executor.workspaces import (
    Workspace,
    WorkspaceAccess,
    WorkspacePlatform,
    WorkspaceRegistry,
)


def workspace(
    root: Path,
    *,
    platform: WorkspacePlatform = WorkspacePlatform.WSL_LINUX,
) -> Workspace:
    return Workspace(
        workspace_id="repo",
        platform=platform,
        root=root,
        access=WorkspaceAccess.READ_ONLY,
    )


def create_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            pytest.fail(f"failed to create test junction: {completed.stderr}")
        return
    link.symlink_to(target, target_is_directory=True)


def test_registry_rejects_unknown_and_duplicate_workspaces(tmp_path: Path) -> None:
    registered = workspace(tmp_path)
    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRegistry([registered, registered])
    registry = WorkspaceRegistry([registered])
    with pytest.raises(WorkspaceNotFound):
        registry.get("missing")


def test_workspace_rejects_filesystem_root_and_link_root(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceConfigurationError):
        workspace(Path("/"))

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    create_directory_link(linked, real)
    with pytest.raises(WorkspaceConfigurationError):
        workspace(linked)


@pytest.mark.parametrize(
    "relative_path",
    [
        "../outside.txt",
        r"..\outside.txt",
        "/etc/passwd",
        r"C:\Windows\system.ini",
        r"C:relative.txt",
        r"\\server\share\file.txt",
        "nested//file.txt",
        "nested/./file.txt",
    ],
)
def test_resolver_rejects_absolute_traversal_and_ambiguous_paths(
    tmp_path: Path,
    relative_path: str,
) -> None:
    registry = WorkspaceRegistry([workspace(tmp_path)])
    with pytest.raises(WorkspacePathRejected):
        registry.resolve_existing("repo", relative_path)


@pytest.mark.parametrize(
    "relative_path",
    [
        "notes.txt:secret",
        "CON",
        "aux.txt",
        "trailing.",
        "trailing ",
    ],
)
def test_windows_resolver_rejects_ads_devices_and_ambiguous_names(
    tmp_path: Path,
    relative_path: str,
) -> None:
    registry = WorkspaceRegistry(
        [workspace(tmp_path, platform=WorkspacePlatform.WINDOWS_NATIVE)]
    )
    with pytest.raises(WorkspacePathRejected):
        registry.resolve_existing("repo", relative_path)


def test_resolver_rejects_internal_and_escaping_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "inside"
    inside.mkdir()
    (inside / "file.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file.txt").write_text("outside", encoding="utf-8")
    create_directory_link(root / "internal-link", inside)
    create_directory_link(root / "escape-link", outside)
    registry = WorkspaceRegistry([workspace(root)])

    for relative_path in ("internal-link/file.txt", "escape-link/file.txt"):
        with pytest.raises(WorkspacePathRejected):
            registry.resolve_existing(
                "repo",
                relative_path,
                expected_kind="file",
            )


def test_resolver_enforces_expected_kind(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    file_path = tmp_path / "file.txt"
    file_path.write_text("text", encoding="utf-8")
    registry = WorkspaceRegistry([workspace(tmp_path)])

    with pytest.raises(WorkspaceTypeMismatch):
        registry.resolve_existing("repo", "directory", expected_kind="file")
    with pytest.raises(WorkspaceTypeMismatch):
        registry.resolve_existing("repo", "file.txt", expected_kind="directory")


def test_resolver_accepts_normalized_existing_file(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    target = nested / "file.txt"
    target.write_text("ok", encoding="utf-8")
    registry = WorkspaceRegistry([workspace(tmp_path)])

    resolved = registry.resolve_existing(
        "repo",
        "nested/file.txt",
        expected_kind="file",
    )

    assert resolved.path == target.resolve()
    assert resolved.relative_path == "nested/file.txt"
    assert os.path.samefile(resolved.workspace.root, tmp_path)
