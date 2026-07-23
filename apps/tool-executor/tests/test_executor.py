from __future__ import annotations

import hashlib
import os
from pathlib import Path
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
    TextDecodingError,
    ToolArgumentsInvalid,
    ToolNotSupported,
    WorkspacePathRejected,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


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
def executor(tmp_path: Path) -> ReadOnlyToolExecutor:
    workspaces = WorkspaceRegistry(
        [
            Workspace(
                workspace_id="repo",
                platform=WorkspacePlatform.WSL_LINUX,
                root=tmp_path,
                access=WorkspaceAccess.READ_ONLY,
            )
        ]
    )
    return ReadOnlyToolExecutor(
        workspaces=workspaces,
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
    )


def test_executor_revalidates_contract_and_rejects_unsupported_tool(
    executor: ReadOnlyToolExecutor,
) -> None:
    with pytest.raises(ToolArgumentsInvalid):
        executor.execute("read_file", {"workspace_id": "repo"})
    with pytest.raises(ToolArgumentsInvalid):
        executor.execute(
            "read_file",
            {
                "workspace_id": "repo",
                "relative_path": "file.txt",
                "unexpected": True,
            },
        )
    with pytest.raises(ToolNotSupported):
        executor.execute("delete_file", {})


def test_read_file_is_utf8_bounded_without_splitting_codepoint(
    executor: ReadOnlyToolExecutor,
    tmp_path: Path,
) -> None:
    (tmp_path / "korean.txt").write_text("가나다", encoding="utf-8")

    result = executor.execute(
        "read_file",
        {
            "workspace_id": "repo",
            "relative_path": "korean.txt",
            "max_bytes": 4,
        },
    )

    assert result["status"] == "succeeded"
    assert result["result"]["content"] == "가"
    assert result["result"]["returned_bytes"] == 3
    assert result["result"]["size_bytes"] == 9
    assert result["result"]["truncated"] is True


def test_read_file_rejects_non_utf8(
    executor: ReadOnlyToolExecutor,
    tmp_path: Path,
) -> None:
    (tmp_path / "binary.dat").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(TextDecodingError):
        executor.execute(
            "read_file",
            {"workspace_id": "repo", "relative_path": "binary.dat"},
        )


def test_read_file_range_is_inclusive_and_bounded(
    executor: ReadOnlyToolExecutor,
    tmp_path: Path,
) -> None:
    (tmp_path / "lines.txt").write_bytes(b"one\ntwo\nthree\nfour\n")

    result = executor.execute(
        "read_file_range",
        {
            "workspace_id": "repo",
            "relative_path": "lines.txt",
            "start_line": 2,
            "end_line": 3,
        },
    )["result"]

    assert result["content"] == "two\nthree\n"
    assert result["last_line"] == 3
    assert result["truncated"] is False
    with pytest.raises(WorkspacePathRejected):
        executor.execute(
            "read_file_range",
            {
                "workspace_id": "repo",
                "relative_path": "lines.txt",
                "start_line": 3,
                "end_line": 2,
            },
        )


def test_list_files_is_depth_and_count_bounded_and_never_follows_links(
    executor: ReadOnlyToolExecutor,
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    directory = root / "directory"
    directory.mkdir()
    (directory / "nested.txt").write_text("nested", encoding="utf-8")
    (root / "plain.txt").write_text("plain", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    create_directory_link(root / "linked", outside)

    result = executor.execute(
        "list_files",
        {
            "workspace_id": "repo",
            "relative_path": "root",
            "max_depth": 1,
            "limit": 10,
        },
    )["result"]
    indexed = {entry["relative_path"]: entry for entry in result["entries"]}

    assert indexed["root/linked"]["kind"] == "blocked_link"
    assert "root/linked/secret.txt" not in indexed
    assert "root/directory/nested.txt" not in indexed

    limited = executor.execute(
        "list_files",
        {"workspace_id": "repo", "relative_path": "root", "limit": 1},
    )["result"]
    assert len(limited["entries"]) == 1
    assert limited["truncated"] is True


def test_search_files_supports_bounded_name_and_utf8_content_search(
    executor: ReadOnlyToolExecutor,
    tmp_path: Path,
) -> None:
    (tmp_path / "alpha-notes.txt").write_text(
        "first line\n오류 원인 발견\n",
        encoding="utf-8",
    )
    (tmp_path / "other.txt").write_text("nothing", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"\xff\xfe")

    by_name = executor.execute(
        "search_files",
        {"workspace_id": "repo", "query": "ALPHA", "mode": "name"},
    )["result"]
    assert by_name["matches"] == [{"relative_path": "alpha-notes.txt"}]

    by_content = executor.execute(
        "search_files",
        {"workspace_id": "repo", "query": "원인", "mode": "content"},
    )["result"]
    assert by_content["matches"][0]["relative_path"] == "alpha-notes.txt"
    assert by_content["matches"][0]["line"] == 2
    assert by_content["skipped_non_utf8"] == 1


def test_calculate_hash_streams_sha256(
    executor: ReadOnlyToolExecutor,
    tmp_path: Path,
) -> None:
    content = b"local voice agent"
    (tmp_path / "hash.bin").write_bytes(content)

    result = executor.execute(
        "calculate_hash",
        {"workspace_id": "repo", "relative_path": "hash.bin"},
    )["result"]

    assert result["sha256"] == hashlib.sha256(content).hexdigest()
    assert result["size_bytes"] == len(content)


def test_list_recent_files_filters_and_sorts(
    executor: ReadOnlyToolExecutor,
    tmp_path: Path,
) -> None:
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")
    old_time = new.stat().st_mtime - 7_200
    os.utime(old, (old_time, old_time))

    result = executor.execute(
        "list_recent_files",
        {
            "workspace_id": "repo",
            "within_minutes": 60,
            "limit": 10,
        },
    )["result"]

    assert [item["relative_path"] for item in result["files"]] == ["new.txt"]
