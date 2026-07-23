from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from local_voice_agent_server.infrastructure.status_adapters import (
    AgentStatusManager,
    GitObservation,
    GitStatusAdapter,
    ProcessRecord,
    PublishedAgentStatus,
    StatusAdapterError,
    StatusFileAdapter,
    WindowsProcessAdapter,
)


REPO = Path(__file__).resolve().parents[3]
SCHEMA_ROOT = REPO / "packages" / "status-adapters" / "schemas"


def published(agent: str = "codex") -> dict[str, object]:
    return {
        "agent": agent,
        "project": "demo",
        "task": "Implement the adapter.",
        "phase": "testing",
        "progress_summary": "Unit tests are running.",
        "current_action": "Running tests.",
        "changed_files": ["src/adapter.py"],
        "tests": {"status": "running", "summary": "1 suite"},
        "blockers": [],
        "updated_at": "2026-07-23T15:00:00+00:00",
    }


def validate_normalized(value: dict[str, object]) -> None:
    input_schema = json.loads(
        (SCHEMA_ROOT / "agent-status-input.schema.json").read_text("utf-8")
    )
    output_schema = json.loads(
        (SCHEMA_ROOT / "normalized-agent-status.schema.json").read_text(
            "utf-8"
        )
    )
    registry = Registry().with_resources(
        [
            (
                input_schema["$id"],
                Resource.from_contents(input_schema),
            ),
            (
                output_schema["$id"],
                Resource.from_contents(output_schema),
            ),
        ]
    )
    Draft202012Validator(output_schema, registry=registry).validate(value)


def test_status_file_is_preferred_and_matches_normalized_contract(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / ".local-voice-agent" / "agent-status.json"
    status_path.parent.mkdir()
    status_path.write_text(json.dumps(published()), encoding="utf-8")

    manager = AgentStatusManager(
        processes=FailingProcessAdapter(),
        git=FailingGitAdapter(),
    )
    results = manager.observe(tmp_path)

    assert len(results) == 1
    value = results[0].to_dict()
    assert value["adapter_id"] == "status-json:codex"
    assert value["provenance"]["task"]["classification"] == "observed"
    validate_normalized(value)


def test_status_file_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text(json.dumps(published()), encoding="utf-8")
    status_path = tmp_path / ".local-voice-agent" / "agent-status.json"
    status_path.parent.mkdir()
    status_path.symlink_to(outside)

    with pytest.raises(StatusAdapterError, match="symlinks"):
        StatusFileAdapter().read(tmp_path)


def test_process_adapter_classifies_supported_agents_without_exposing_command(
    tmp_path: Path,
) -> None:
    records = [
        ProcessRecord(
            101,
            "node.exe",
            r"C:\tools\node.exe C:\bin\codex --token very-secret-value",
        ),
        ProcessRecord(102, "claude.exe", "claude"),
        ProcessRecord(103, "opencode.exe", "opencode serve"),
        ProcessRecord(104, "python.exe", "python -m aider"),
        ProcessRecord(105, "pwsh.exe", f"pwsh -WorkingDirectory {tmp_path}"),
        ProcessRecord(106, "other.exe", "other"),
    ]

    observed = WindowsProcessAdapter().observe(records, workspace=tmp_path)

    assert [item.agent for item in observed] == [
        "codex",
        "claude-code",
        "opencode",
        "aider",
        "terminal",
    ]
    serialized = json.dumps(
        [
            {
                "adapter_id": item.adapter_id,
                "agent": item.agent,
                "pid": item.pid,
                "process_name": item.process_name,
            }
            for item in observed
        ]
    )
    assert "very-secret-value" not in serialized


def test_process_fallback_marks_inference_and_unknown_fields(
    tmp_path: Path,
) -> None:
    manager = AgentStatusManager(
        status_files=EmptyStatusFileAdapter(),
        processes=WindowsProcessAdapter(),
        git=StaticGitAdapter(),
    )
    result = manager.observe(
        tmp_path,
        process_records=[
            ProcessRecord(
                501,
                "codex.exe",
                f"codex {tmp_path}",
                datetime(2026, 7, 23, tzinfo=timezone.utc),
            )
        ],
    )[0]
    value = result.to_dict()

    assert value["status"]["changed_files"] == ["README.md"]
    assert value["provenance"]["changed_files"]["classification"] == "observed"
    assert value["provenance"]["phase"]["classification"] == "inferred"
    assert value["provenance"]["task"]["classification"] == "unknown"
    assert "progress_percent" not in value["status"]
    validate_normalized(value)


def test_git_adapter_observes_modified_and_untracked_files(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True,
    )
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("initial\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "tracked.txt"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "initial"],
        check=True,
    )
    tracked.write_text("changed\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")

    result = GitStatusAdapter().observe(tmp_path)

    assert result.changed_files == ("new.txt", "tracked.txt")
    assert result.branch in {"main", "master"}


class FailingProcessAdapter:
    def observe(self, records: object = None) -> object:
        raise AssertionError("process fallback must not run")


class FailingGitAdapter:
    def observe(self, workspace: Path) -> object:
        raise AssertionError("Git fallback must not run")


class EmptyStatusFileAdapter:
    def read(self, workspace: Path) -> PublishedAgentStatus | None:
        return None


class StaticGitAdapter:
    def observe(self, workspace: Path) -> GitObservation:
        return GitObservation(("README.md",), "main")
