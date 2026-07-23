"""Execution of code-owned, workspace-registered development profiles."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
from time import monotonic, sleep
from typing import Any, Mapping
from uuid import UUID, uuid4

from .errors import (
    DevelopmentToolError,
    ToolNotSupported,
    WorkspaceConfigurationError,
)
from .system import _redact_command_line
from .workspaces import WorkspaceRegistry


DEVELOPMENT_TOOLS = frozenset({"inspect_test_log", "run_tests"})
_TAIL_BYTES = 16 * 1024


class DevelopmentToolExecutor:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRegistry,
        executables: Mapping[str, Path],
        artifact_root: Path,
    ) -> None:
        self._workspaces = workspaces
        self._executables = {
            key: value.resolve(strict=True) for key, value in executables.items()
        }
        self._artifact_root = artifact_root.resolve()
        self._artifact_root.mkdir(parents=True, exist_ok=True)

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        if tool_name not in DEVELOPMENT_TOOLS:
            raise ToolNotSupported(tool_name)
        return getattr(self, f"_{tool_name}")(**dict(arguments))

    def _run_tests(
        self,
        *,
        workspace_id: str,
        profile_id: str,
        idempotency_key: str,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del idempotency_key
        workspace = self._workspaces.get(workspace_id)
        try:
            profile = workspace.command_profile(profile_id)
        except WorkspaceConfigurationError as error:
            raise DevelopmentToolError(
                "test profile is not registered"
            ) from error
        if profile.kind != "test":
            raise DevelopmentToolError("profile is not registered for tests")
        executable = self._executables.get(profile.executable_id)
        if executable is None:
            raise DevelopmentToolError("registered executable is unavailable")
        working_directory = self._workspaces.resolve_existing(
            workspace_id,
            profile.working_directory_relative or ".",
            expected_kind="directory",
        ).path
        effective_timeout = profile.timeout_seconds
        if timeout_seconds is not None:
            effective_timeout = min(effective_timeout, timeout_seconds)
        return self._run_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
            executable=executable,
            arguments=profile.arguments,
            working_directory=working_directory,
            timeout_seconds=effective_timeout,
            max_output_bytes=profile.max_output_bytes,
            environment_keys=profile.environment_keys,
            kind="test",
        )

    def _inspect_test_log(
        self,
        *,
        workspace_id: str,
        evidence_id: str,
        offset_bytes: int = 0,
        max_bytes: int = 65_536,
    ) -> dict[str, Any]:
        try:
            canonical_id = str(UUID(evidence_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise DevelopmentToolError("evidence ID is invalid") from error
        metadata_path = self._artifact_root / f"{canonical_id}.json"
        log_path = self._artifact_root / f"{canonical_id}.log"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DevelopmentToolError("test evidence is unavailable") from error
        if (
            metadata.get("workspace_id") != workspace_id
            or metadata.get("kind") != "test"
        ):
            raise DevelopmentToolError("test evidence binding mismatch")
        try:
            size = log_path.stat().st_size
            with log_path.open("rb") as handle:
                handle.seek(offset_bytes)
                raw = handle.read(max_bytes)
        except OSError as error:
            raise DevelopmentToolError("test log is unavailable") from error
        return {
            "evidence_id": canonical_id,
            "offset_bytes": offset_bytes,
            "returned_bytes": len(raw),
            "total_bytes": size,
            "eof": offset_bytes + len(raw) >= size,
            "text": raw.decode("utf-8", errors="replace"),
        }

    def _run_profile(
        self,
        *,
        workspace_id: str,
        profile_id: str,
        executable: Path,
        arguments: tuple[str, ...],
        working_directory: Path,
        timeout_seconds: int,
        max_output_bytes: int,
        environment_keys: tuple[str, ...],
        kind: str,
    ) -> dict[str, Any]:
        evidence_id = str(uuid4())
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{evidence_id}.",
            suffix=".tmp",
            dir=self._artifact_root,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        command = [str(executable), *arguments]
        environment = _minimal_environment(environment_keys)
        started_at = datetime.now(timezone.utc)
        started = monotonic()
        timed_out = False
        output_limited = False
        try:
            with temporary_path.open("wb") as output:
                process = subprocess.Popen(
                    command,
                    cwd=working_directory,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    ),
                )
                while process.poll() is None:
                    elapsed = monotonic() - started
                    output.flush()
                    if elapsed >= timeout_seconds:
                        timed_out = True
                        process.kill()
                        break
                    if temporary_path.stat().st_size > max_output_bytes:
                        output_limited = True
                        process.kill()
                        break
                    sleep(0.05)
                process.wait(timeout=5)
            if temporary_path.stat().st_size > max_output_bytes:
                output_limited = True
            raw = temporary_path.read_bytes()[:max_output_bytes]
            decoded = raw.decode("utf-8", errors="replace")
            redacted = _redact_command_line(decoded) or ""
            encoded = redacted.encode("utf-8")[:max_output_bytes]
            log_path = self._artifact_root / f"{evidence_id}.log"
            metadata_path = self._artifact_root / f"{evidence_id}.json"
            with log_path.open("xb") as handle:
                handle.write(encoded)
            completed_at = datetime.now(timezone.utc)
            metadata = {
                "schema_version": "1.0",
                "evidence_id": evidence_id,
                "workspace_id": workspace_id,
                "profile_id": profile_id,
                "kind": kind,
                "exit_code": process.returncode,
                "timed_out": timed_out,
                "output_limited": output_limited,
                "output_bytes": len(encoded),
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": round((monotonic() - started) * 1000, 3),
            }
            with metadata_path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(metadata, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
            return {
                **metadata,
                "succeeded": (
                    process.returncode == 0
                    and not timed_out
                    and not output_limited
                ),
                "output_tail": encoded[-_TAIL_BYTES:].decode(
                    "utf-8",
                    errors="replace",
                ),
            }
        except (OSError, subprocess.SubprocessError) as error:
            raise DevelopmentToolError(
                "registered development command failed"
            ) from error
        finally:
            temporary_path.unlink(missing_ok=True)


def _minimal_environment(allowed_keys: tuple[str, ...]) -> dict[str, str]:
    baseline = (
        "ComSpec",
        "SystemDrive",
        "SystemRoot",
        "TEMP",
        "TMP",
        "WINDIR",
    )
    environment: dict[str, str] = {}
    for key in (*baseline, *allowed_keys):
        value = os.environ.get(key)
        if value is not None:
            environment[key] = value
    return environment
