from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess

import pytest

from local_voice_agent_tool_executor import (
    ReadOnlyToolExecutor,
    Workspace,
    WorkspaceAccess,
    WorkspacePlatform,
    WorkspaceRegistry,
)
from local_voice_agent_tool_executor.errors import (
    GitCommandFailed,
    GitWorkspaceRejected,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def run_git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        [shutil.which("git") or "git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


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


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.name", "Tool Executor Test")
    run_git(repo, "config", "user.email", "tool-executor@example.invalid")
    (repo / "tracked.txt").write_bytes(b"one\ntwo\nthree\n")
    (repo / "--stat").write_text("literal path\n", encoding="utf-8")
    run_git(repo, "add", "--", "tracked.txt", "--stat")
    run_git(repo, "commit", "-m", "initial")
    return repo


@pytest.fixture
def git_executor(git_repo: Path) -> ReadOnlyToolExecutor:
    git_path = shutil.which("git")
    assert git_path is not None
    workspaces = WorkspaceRegistry(
        [
            Workspace(
                workspace_id="repo",
                platform=(
                    WorkspacePlatform.WINDOWS_NATIVE
                    if os.name == "nt"
                    else WorkspacePlatform.WSL_LINUX
                ),
                root=git_repo,
                access=WorkspaceAccess.READ_ONLY,
                git_enabled=True,
            )
        ]
    )
    return ReadOnlyToolExecutor(
        workspaces=workspaces,
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
        git_executable=Path(git_path).resolve(),
    )


def test_git_status_observes_untracked_without_optional_locks(
    git_executor: ReadOnlyToolExecutor,
    git_repo: Path,
) -> None:
    (git_repo / "untracked.txt").write_text("new", encoding="utf-8")

    included = git_executor.execute(
        "git_status",
        {"workspace_id": "repo", "include_untracked": True},
    )["result"]
    excluded = git_executor.execute(
        "git_status",
        {"workspace_id": "repo", "include_untracked": False},
    )["result"]

    assert "? untracked.txt" in included["output"]
    assert "untracked.txt" not in excluded["output"]
    assert included["nul_delimited"] is True


def test_git_diff_is_bounded_and_literal_pathspec_safe(
    git_executor: ReadOnlyToolExecutor,
    git_repo: Path,
) -> None:
    (git_repo / "--stat").write_text(
        "literal path changed with enough bytes to truncate\n",
        encoding="utf-8",
    )
    result = git_executor.execute(
        "git_diff",
        {
            "workspace_id": "repo",
            "relative_path": "--stat",
            "max_bytes": 32,
        },
    )["result"]

    assert result["truncated"] is True
    assert result["output_bytes"] > 32
    assert len(result["output"].encode("utf-8")) <= 32


def test_git_diff_disables_repository_external_diff_driver(
    git_executor: ReadOnlyToolExecutor,
    git_repo: Path,
) -> None:
    (git_repo / ".gitattributes").write_text(
        "tracked.txt diff=evil\n",
        encoding="utf-8",
    )
    run_git(
        git_repo,
        "config",
        "diff.evil.command",
        "definitely-not-a-real-executable",
    )
    run_git(git_repo, "add", "--", ".gitattributes")
    run_git(git_repo, "commit", "-m", "add diff attributes")
    (git_repo / "tracked.txt").write_bytes(b"one\nchanged\nthree\n")

    result = git_executor.execute(
        "git_diff",
        {"workspace_id": "repo", "relative_path": "tracked.txt"},
    )["result"]

    assert "changed" in result["output"]


def test_git_staged_diff_and_stat_are_observable(
    git_executor: ReadOnlyToolExecutor,
    git_repo: Path,
) -> None:
    (git_repo / "tracked.txt").write_bytes(b"one\nstaged\nthree\n")
    run_git(git_repo, "add", "--", "tracked.txt")

    diff = git_executor.execute(
        "git_diff",
        {"workspace_id": "repo", "staged": True},
    )["result"]
    summary = git_executor.execute(
        "git_diff_stat",
        {"workspace_id": "repo", "staged": True},
    )["result"]

    assert "staged" in diff["output"]
    assert "tracked.txt" in summary["output"]


def test_git_log_branch_show_and_blame_use_resolved_commit(
    git_executor: ReadOnlyToolExecutor,
    git_repo: Path,
) -> None:
    head = run_git(git_repo, "rev-parse", "HEAD")

    log = git_executor.execute(
        "git_log",
        {"workspace_id": "repo", "revision": "HEAD", "max_count": 1},
    )["result"]
    branch = git_executor.execute(
        "git_branch",
        {"workspace_id": "repo"},
    )["result"]
    shown = git_executor.execute(
        "git_show",
        {
            "workspace_id": "repo",
            "revision": "HEAD",
            "relative_path": "tracked.txt",
        },
    )["result"]
    blamed = git_executor.execute(
        "git_blame",
        {
            "workspace_id": "repo",
            "relative_path": "tracked.txt",
            "start_line": 2,
            "end_line": 2,
            "revision": head,
        },
    )["result"]

    assert head in log["output"]
    assert "main" in branch["output"]
    assert "tracked.txt" in shown["output"]
    assert head in blamed["output"]


def test_read_only_git_commands_do_not_change_index(
    git_executor: ReadOnlyToolExecutor,
    git_repo: Path,
) -> None:
    index = git_repo / ".git" / "index"
    before = index.read_bytes()
    before_mtime = index.stat().st_mtime_ns

    for tool_name, arguments in (
        ("git_status", {"workspace_id": "repo"}),
        ("git_diff", {"workspace_id": "repo"}),
        ("git_log", {"workspace_id": "repo", "max_count": 1}),
        ("git_branch", {"workspace_id": "repo"}),
    ):
        git_executor.execute(tool_name, arguments)

    assert index.read_bytes() == before
    assert index.stat().st_mtime_ns == before_mtime


def test_revision_option_injection_is_rejected_as_unknown_revision(
    git_executor: ReadOnlyToolExecutor,
) -> None:
    with pytest.raises(GitCommandFailed):
        git_executor.execute(
            "git_show",
            {"workspace_id": "repo", "revision": "--help"},
        )


def test_git_requires_enabled_workspace_and_internal_git_directory(
    tmp_path: Path,
) -> None:
    git_path = shutil.which("git")
    assert git_path is not None
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / ".git").write_text("gitdir: ../outside\n", encoding="utf-8")

    disabled = ReadOnlyToolExecutor(
        workspaces=WorkspaceRegistry(
            [
                Workspace(
                    workspace_id="plain",
                    platform=(
                        WorkspacePlatform.WINDOWS_NATIVE
                        if os.name == "nt"
                        else WorkspacePlatform.WSL_LINUX
                    ),
                    root=plain,
                    access=WorkspaceAccess.READ_ONLY,
                    git_enabled=False,
                )
            ]
        ),
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
        git_executable=Path(git_path).resolve(),
    )
    enabled = ReadOnlyToolExecutor(
        workspaces=WorkspaceRegistry(
            [
                Workspace(
                    workspace_id="plain",
                    platform=(
                        WorkspacePlatform.WINDOWS_NATIVE
                        if os.name == "nt"
                        else WorkspacePlatform.WSL_LINUX
                    ),
                    root=plain,
                    access=WorkspaceAccess.READ_ONLY,
                    git_enabled=True,
                )
            ]
        ),
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
        git_executable=Path(git_path).resolve(),
    )

    with pytest.raises(GitWorkspaceRejected):
        disabled.execute("git_status", {"workspace_id": "plain"})
    with pytest.raises(GitWorkspaceRejected):
        enabled.execute("git_status", {"workspace_id": "plain"})


@pytest.mark.parametrize("unsafe_kind", ["alternates", "include", "link"])
def test_git_rejects_external_metadata_paths(
    git_executor: ReadOnlyToolExecutor,
    git_repo: Path,
    unsafe_kind: str,
) -> None:
    if unsafe_kind == "alternates":
        (git_repo / ".git" / "objects" / "info" / "alternates").write_text(
            "../outside-objects\n",
            encoding="utf-8",
        )
    elif unsafe_kind == "include":
        with (git_repo / ".git" / "config").open("a", encoding="utf-8") as stream:
            stream.write("\n[include]\n\tpath = ../outside-config\n")
    else:
        outside = git_repo.parent / "outside-metadata"
        outside.mkdir()
        create_directory_link(git_repo / ".git" / "linked", outside)

    with pytest.raises(GitWorkspaceRejected):
        git_executor.execute("git_status", {"workspace_id": "repo"})


def test_git_tools_fail_closed_when_adapter_is_not_configured(
    tmp_path: Path,
) -> None:
    executor = ReadOnlyToolExecutor(
        workspaces=WorkspaceRegistry(
            [
                Workspace(
                    workspace_id="repo",
                    platform=WorkspacePlatform.WSL_LINUX,
                    root=tmp_path,
                    access=WorkspaceAccess.READ_ONLY,
                )
            ]
        ),
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
    )
    with pytest.raises(GitWorkspaceRejected):
        executor.execute("git_status", {"workspace_id": "repo"})
