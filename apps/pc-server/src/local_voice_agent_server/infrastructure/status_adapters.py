"""Read-only adapters for observable coding-agent state.

No adapter assumes a private agent API. Command lines are inspected only for
local classification and are never returned because they may contain secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


Classification = Literal["observed", "inferred", "unknown"]
Phase = Literal["planning", "coding", "testing", "blocked", "completed"]
TestState = Literal["not_run", "running", "passed", "failed"]


class PublishedTests(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TestState
    summary: str = Field(max_length=16_384)


class PublishedAgentStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str = Field(min_length=1, max_length=128)
    project: str = Field(min_length=1, max_length=256)
    task: str = Field(max_length=4_096)
    phase: Phase
    progress_summary: str = Field(max_length=16_384)
    current_action: str = Field(max_length=4_096)
    changed_files: list[str] = Field(max_length=1_000)
    tests: PublishedTests
    blockers: list[str] = Field(max_length=100)
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Basis:
    classification: Classification
    source: str
    explanation: str | None = None

    def to_dict(self) -> dict[str, str]:
        value = {
            "classification": self.classification,
            "source": self.source,
        }
        if self.explanation is not None:
            value["explanation"] = self.explanation
        return value


@dataclass(frozen=True, slots=True)
class ProcessRecord:
    pid: int
    name: str
    command_line: str
    started_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AgentProcessObservation:
    adapter_id: str
    agent: str
    pid: int
    process_name: str
    started_at: datetime | None
    workspace_match: bool


@dataclass(frozen=True, slots=True)
class GitObservation:
    changed_files: tuple[str, ...]
    branch: str | None


@dataclass(frozen=True, slots=True)
class NormalizedAgentStatus:
    adapter_id: str
    status: PublishedAgentStatus
    provenance: dict[str, object]
    observed_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "adapter_id": self.adapter_id,
            "status": self.status.model_dump(mode="json"),
            "provenance": self.provenance,
            "observed_at": self.observed_at.isoformat(),
        }


class StatusAdapterError(RuntimeError):
    pass


class StatusFileAdapter:
    def __init__(self, *, max_bytes: int = 1024 * 1024) -> None:
        self._max_bytes = max_bytes

    def read(
        self,
        workspace: Path,
        *,
        relative_path: str = ".local-voice-agent/agent-status.json",
    ) -> PublishedAgentStatus | None:
        root = workspace.resolve(strict=True)
        candidate = workspace / relative_path
        if not candidate.exists():
            return None
        if candidate.is_symlink():
            raise StatusAdapterError("status file symlinks are forbidden")
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise StatusAdapterError("status file escapes workspace") from error
        if not resolved.is_file():
            raise StatusAdapterError("status path is not a regular file")
        size = resolved.stat().st_size
        if size > self._max_bytes:
            raise StatusAdapterError("status file exceeds size limit")
        try:
            raw = json.loads(resolved.read_text(encoding="utf-8"))
            status = PublishedAgentStatus.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            raise StatusAdapterError("status file is invalid") from error
        if status.updated_at.tzinfo is None:
            raise StatusAdapterError("status timestamp must be timezone-aware")
        return status


class WindowsProcessAdapter:
    """Classify supported agents from Windows process observations."""

    _MARKERS = (
        ("codex", re.compile(r"(^|[\\/\s])codex(?:\.exe|\.cmd)?(?:$|\s)", re.I)),
        (
            "claude-code",
            re.compile(r"(^|[\\/\s])claude(?:\.exe|\.cmd)?(?:$|\s)", re.I),
        ),
        (
            "opencode",
            re.compile(r"(^|[\\/\s])opencode(?:\.exe|\.cmd)?(?:$|\s)", re.I),
        ),
        ("aider", re.compile(r"(^|[\\/\s])aider(?:\.exe|\.cmd)?(?:$|\s)", re.I)),
    )
    _TERMINALS = {
        "bash",
        "cmd",
        "conhost",
        "powershell",
        "pwsh",
        "terminal",
        "windowsterminal",
    }

    def observe(
        self,
        records: list[ProcessRecord] | None = None,
        *,
        workspace: Path | None = None,
    ) -> list[AgentProcessObservation]:
        process_records = records if records is not None else self._query_windows()
        observations: list[AgentProcessObservation] = []
        for record in process_records:
            haystack = f"{record.name} {record.command_line}"
            agent = next(
                (
                    candidate
                    for candidate, pattern in self._MARKERS
                    if pattern.search(haystack)
                ),
                None,
            )
            normalized_name = Path(record.name).stem.casefold()
            if agent is None and normalized_name == "chatgpt":
                agent = "codex-desktop"
                if "--type=" in record.command_line.casefold():
                    continue
            if agent is None and normalized_name in self._TERMINALS:
                agent = "terminal"
            if agent is None:
                continue
            workspace_match = (
                workspace is not None
                and self._mentions_workspace(record.command_line, workspace)
            )
            if agent == "terminal" and not workspace_match:
                continue
            observations.append(
                AgentProcessObservation(
                    adapter_id=f"process:{agent}:{record.pid}",
                    agent=agent,
                    pid=record.pid,
                    process_name=Path(record.name).name[:256],
                    started_at=record.started_at,
                    workspace_match=workspace_match,
                )
            )
        return observations

    @staticmethod
    def _mentions_workspace(command_line: str, workspace: Path) -> bool:
        normalized_command = command_line.replace("\\", "/").casefold()
        normalized_workspace = str(workspace).replace("\\", "/").casefold()
        candidates = {normalized_workspace}
        match = re.match(r"^/mnt/([a-z])/(.*)$", normalized_workspace)
        if match:
            candidates.add(f"{match.group(1)}:/{match.group(2)}")
        return any(candidate in normalized_command for candidate in candidates)

    def _query_windows(self) -> list[ProcessRecord]:
        if os.name == "nt":
            powershell = (
                Path(os.environ.get("WINDIR", r"C:\Windows"))
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            )
        else:
            powershell = Path(
                "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
            )
        script = (
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,Name,CommandLine,CreationDate | "
            "ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise StatusAdapterError("Windows process query failed") from error
        if completed.returncode != 0 or len(completed.stdout) > 8 * 1024 * 1024:
            raise StatusAdapterError("Windows process query failed")
        try:
            decoded = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as error:
            raise StatusAdapterError("Windows process response is invalid") from error
        rows = decoded if isinstance(decoded, list) else [decoded]
        result: list[ProcessRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                pid = int(row["ProcessId"])
                name = str(row.get("Name") or "")
                command_line = str(row.get("CommandLine") or "")
            except (KeyError, TypeError, ValueError):
                continue
            if not name:
                continue
            result.append(ProcessRecord(pid, name, command_line))
        return result


class GitStatusAdapter:
    def observe(self, workspace: Path) -> GitObservation:
        root = workspace.resolve(strict=True)
        if not root.is_dir():
            raise StatusAdapterError("workspace is not a directory")
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        status = self._git(
            root,
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            environment,
        )
        changed: list[str] = []
        fields = status.split("\0")
        index = 0
        while index < len(fields):
            entry = fields[index]
            index += 1
            if not entry:
                continue
            if len(entry) < 4:
                raise StatusAdapterError("Git status output is invalid")
            path = entry[3:]
            if entry[:2] in {"R ", " R", "C ", " C"}:
                if index >= len(fields) or not fields[index]:
                    raise StatusAdapterError("Git rename output is invalid")
                path = fields[index]
                index += 1
            changed.append(path)
        branch = self._git(
            root,
            ["branch", "--show-current"],
            environment,
        ).strip() or None
        return GitObservation(tuple(sorted(set(changed))), branch)

    @staticmethod
    def _git(root: Path, arguments: list[str], environment: dict[str, str]) -> str:
        try:
            completed = subprocess.run(
                [
                    "git",
                    "-c",
                    f"safe.directory={root}",
                    "-C",
                    str(root),
                    *arguments,
                ],
                check=False,
                capture_output=True,
                timeout=10,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise StatusAdapterError("Git observation failed") from error
        if completed.returncode != 0 or len(completed.stdout) > 8 * 1024 * 1024:
            raise StatusAdapterError("Git observation failed")
        return completed.stdout.decode("utf-8", errors="replace")


class AgentStatusManager:
    def __init__(
        self,
        *,
        status_files: StatusFileAdapter | None = None,
        processes: WindowsProcessAdapter | None = None,
        git: GitStatusAdapter | None = None,
    ) -> None:
        self._status_files = status_files or StatusFileAdapter()
        self._processes = processes or WindowsProcessAdapter()
        self._git = git or GitStatusAdapter()

    def observe(
        self,
        workspace: Path,
        *,
        process_records: list[ProcessRecord] | None = None,
    ) -> list[NormalizedAgentStatus]:
        observed_at = datetime.now(timezone.utc)
        published = self._status_files.read(workspace)
        if published is not None:
            source = ".local-voice-agent/agent-status.json"
            basis = Basis("observed", source)
            provenance = {
                key: basis.to_dict()
                for key in (
                    "agent",
                    "project",
                    "task",
                    "phase",
                    "progress_summary",
                    "current_action",
                    "changed_files",
                    "blockers",
                    "updated_at",
                )
            }
            provenance["tests"] = {
                "status": basis.to_dict(),
                "summary": basis.to_dict(),
            }
            return [
                NormalizedAgentStatus(
                    adapter_id=f"status-json:{published.agent}",
                    status=published,
                    provenance=provenance,
                    observed_at=observed_at,
                )
            ]

        git = self._git.observe(workspace)
        observations = self._processes.observe(
            process_records,
            workspace=workspace,
        )
        return [
            self._from_process(
                observation,
                workspace=workspace,
                git=git,
                observed_at=observed_at,
            )
            for observation in observations
        ]

    @staticmethod
    def _from_process(
        observation: AgentProcessObservation,
        *,
        workspace: Path,
        git: GitObservation,
        observed_at: datetime,
    ) -> NormalizedAgentStatus:
        process_source = f"windows-process:{observation.pid}"
        git_source = f"git:{workspace}"
        unknown = Basis(
            "unknown",
            process_source,
            "No authoritative status source published this field.",
        )
        inferred = Basis(
            "inferred",
            process_source,
            "A matching local process is running; its private task state is unavailable.",
        )
        workspace_known = observation.workspace_match
        status = PublishedAgentStatus(
            agent=observation.agent,
            project=workspace.name if workspace_known else "unknown",
            task="",
            phase="coding",
            progress_summary=(
                f"{observation.agent} process {observation.pid} is running; "
                "progress details are unavailable."
            ),
            current_action="Process is running.",
            changed_files=list(git.changed_files) if workspace_known else [],
            tests=PublishedTests(
                status="not_run",
                summary="No authoritative test-status source was observed.",
            ),
            blockers=[],
            updated_at=observation.started_at or observed_at,
        )
        provenance: dict[str, object] = {
            "agent": Basis("observed", process_source).to_dict(),
            "project": (
                Basis("observed", f"workspace:{workspace}").to_dict()
                if workspace_known
                else unknown.to_dict()
            ),
            "task": unknown.to_dict(),
            "phase": inferred.to_dict(),
            "progress_summary": inferred.to_dict(),
            "current_action": inferred.to_dict(),
            "changed_files": (
                Basis("observed", git_source).to_dict()
                if workspace_known
                else unknown.to_dict()
            ),
            "tests": {
                "status": unknown.to_dict(),
                "summary": unknown.to_dict(),
            },
            "blockers": unknown.to_dict(),
            "updated_at": (
                Basis("observed", process_source).to_dict()
                if observation.started_at
                else inferred.to_dict()
            ),
        }
        return NormalizedAgentStatus(
            adapter_id=observation.adapter_id,
            status=status,
            provenance=provenance,
            observed_at=observed_at,
        )
