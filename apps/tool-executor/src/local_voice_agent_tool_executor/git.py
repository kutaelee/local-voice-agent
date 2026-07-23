"""Read-only Git adapter using fixed argv and bounded process output."""

from __future__ import annotations

from dataclasses import dataclass
import codecs
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
from typing import Any, Sequence

from .contracts import ReadToolContracts
from .errors import (
    GitCommandFailed,
    GitCommandTimedOut,
    GitOutputDecodingError,
    GitWorkspaceRejected,
    ToolExecutorError,
)
from .workspaces import Workspace, WorkspaceRegistry, _is_link_or_reparse


MAX_FIXED_OUTPUT_BYTES = 1_048_576
MAX_BLAME_OUTPUT_BYTES = 2_097_152
MAX_GIT_METADATA_ENTRIES = 100_000
MAX_GIT_CONFIG_BYTES = 1_048_576
_OBJECT_ID = re.compile(r"^[0-9a-f]{40,64}$")
_CONFIG_INCLUDE_SECTION = re.compile(
    br"(?mi)^\s*\[\s*include(?:if)?\b"
)


@dataclass(frozen=True, slots=True)
class GitProcessResult:
    stdout: str
    stderr: str
    stdout_bytes: int
    truncated: bool


class ReadOnlyGit:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRegistry,
        contracts: ReadToolContracts,
        git_executable: Path,
    ) -> None:
        executable = Path(git_executable)
        if not executable.is_absolute() or not executable.is_file():
            raise GitWorkspaceRejected("git executable must be an absolute file")
        self._workspaces = workspaces
        self._contracts = contracts
        self._git_executable = executable.resolve(strict=True)

    def git_status(
        self,
        *,
        workspace_id: str,
        include_untracked: bool = True,
    ) -> dict[str, Any]:
        workspace = self._require_repository(workspace_id)
        untracked = "all" if include_untracked else "no"
        result = self._run(
            workspace,
            "git_status",
            [
                "status",
                "--porcelain=v2",
                "--branch",
                "-z",
                f"--untracked-files={untracked}",
            ],
            max_bytes=MAX_FIXED_OUTPUT_BYTES,
        )
        return _result(workspace_id, result, nul_delimited=True)

    def git_diff(
        self,
        *,
        workspace_id: str,
        staged: bool = False,
        relative_path: str | None = None,
        max_bytes: int = MAX_FIXED_OUTPUT_BYTES,
    ) -> dict[str, Any]:
        workspace = self._require_repository(workspace_id)
        argv = ["diff", "--no-ext-diff", "--no-textconv"]
        if staged:
            argv.append("--cached")
        argv.append("--")
        if relative_path is not None:
            argv.append(
                self._workspaces.normalize_relative(
                    workspace_id,
                    relative_path,
                    allow_root=False,
                )
            )
        result = self._run(
            workspace,
            "git_diff",
            argv,
            max_bytes=max_bytes,
        )
        return _result(workspace_id, result)

    def git_diff_stat(
        self,
        *,
        workspace_id: str,
        staged: bool = False,
    ) -> dict[str, Any]:
        workspace = self._require_repository(workspace_id)
        argv = [
            "diff",
            "--stat",
            "--summary",
            "--no-ext-diff",
            "--no-textconv",
        ]
        if staged:
            argv.append("--cached")
        argv.append("--")
        result = self._run(
            workspace,
            "git_diff_stat",
            argv,
            max_bytes=MAX_FIXED_OUTPUT_BYTES,
        )
        return _result(workspace_id, result)

    def git_log(
        self,
        *,
        workspace_id: str,
        revision: str = "HEAD",
        max_count: int = 20,
    ) -> dict[str, Any]:
        workspace = self._require_repository(workspace_id)
        object_id = self._resolve_commit(workspace, revision, "git_log")
        result = self._run(
            workspace,
            "git_log",
            [
                "log",
                "--no-decorate",
                "--date=iso-strict",
                "--format=%H%x00%aI%x00%an%x00%s",
                "-z",
                f"--max-count={max_count}",
                object_id,
                "--",
            ],
            max_bytes=MAX_FIXED_OUTPUT_BYTES,
        )
        return _result(workspace_id, result, nul_delimited=True)

    def git_branch(self, *, workspace_id: str) -> dict[str, Any]:
        workspace = self._require_repository(workspace_id)
        result = self._run(
            workspace,
            "git_branch",
            [
                "branch",
                "--format=%(refname:short)%00%(HEAD)%00"
                "%(upstream:short)%00%(upstream:trackshort)",
            ],
            max_bytes=MAX_FIXED_OUTPUT_BYTES,
        )
        return _result(workspace_id, result, nul_delimited=True)

    def git_show(
        self,
        *,
        workspace_id: str,
        revision: str,
        relative_path: str | None = None,
        max_bytes: int = 524_288,
    ) -> dict[str, Any]:
        workspace = self._require_repository(workspace_id)
        object_id = self._resolve_commit(workspace, revision, "git_show")
        argv = [
            "show",
            "--no-ext-diff",
            "--no-textconv",
            "--format=fuller",
            "--date=iso-strict",
            object_id,
        ]
        if relative_path is not None:
            argv.extend(
                (
                    "--",
                    self._workspaces.normalize_relative(
                        workspace_id,
                        relative_path,
                        allow_root=False,
                    ),
                )
            )
        result = self._run(
            workspace,
            "git_show",
            argv,
            max_bytes=max_bytes,
        )
        return _result(workspace_id, result)

    def git_blame(
        self,
        *,
        workspace_id: str,
        relative_path: str,
        start_line: int = 1,
        end_line: int | None = None,
        revision: str | None = None,
    ) -> dict[str, Any]:
        workspace = self._require_repository(workspace_id)
        if end_line is not None and end_line < start_line:
            raise GitWorkspaceRejected("end_line must be greater than start_line")
        object_id = self._resolve_commit(
            workspace,
            revision or "HEAD",
            "git_blame",
        )
        path = self._workspaces.normalize_relative(
            workspace_id,
            relative_path,
            allow_root=False,
        )
        argv = ["blame", "--porcelain"]
        if start_line != 1 or end_line is not None:
            line_range = f"{start_line},{end_line or ''}"
            argv.extend(("-L", line_range))
        argv.extend((object_id, "--", path))
        result = self._run(
            workspace,
            "git_blame",
            argv,
            max_bytes=MAX_BLAME_OUTPUT_BYTES,
        )
        return _result(workspace_id, result)

    def _require_repository(self, workspace_id: str) -> Workspace:
        workspace = self._workspaces.get(workspace_id)
        if not workspace.git_enabled:
            raise GitWorkspaceRejected("workspace is not registered for Git")
        try:
            git_directory = self._workspaces.resolve_existing(
                workspace_id,
                ".git",
                expected_kind="directory",
            )
        except ToolExecutorError as error:
            raise GitWorkspaceRejected(
                "workspace must contain an internal .git directory"
            ) from error
        _assert_git_metadata_safe(git_directory.path)
        return workspace

    def _resolve_commit(
        self,
        workspace: Workspace,
        revision: str,
        contract_name: str,
    ) -> str:
        if "\x00" in revision:
            raise GitWorkspaceRejected("revision contains NUL")
        result = self._run(
            workspace,
            contract_name,
            [
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{revision}^{{commit}}",
            ],
            max_bytes=256,
        )
        object_id = result.stdout.strip()
        if not _OBJECT_ID.fullmatch(object_id):
            raise GitCommandFailed("revision did not resolve to one commit")
        return object_id

    def _run(
        self,
        workspace: Workspace,
        contract_name: str,
        argv: Sequence[str],
        *,
        max_bytes: int,
    ) -> GitProcessResult:
        if not 1 <= max_bytes <= 4_194_304:
            raise GitWorkspaceRejected("Git output bound is invalid")
        command = [
            str(self._git_executable),
            "-c",
            "color.ui=false",
            "-c",
            "core.pager=cat",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            f"core.worktree={workspace.root}",
            "-c",
            "core.bare=false",
            "-c",
            "i18n.logOutputEncoding=utf-8",
            "-c",
            "log.mailmap=false",
            *argv,
        ]
        popen_options: dict[str, Any] = {
            "cwd": workspace.root,
            "env": _minimal_environment(),
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True

        with (
            tempfile.TemporaryFile() as stdout_file,
            tempfile.TemporaryFile() as stderr_file,
        ):
            try:
                process = subprocess.Popen(
                    command,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    **popen_options,
                )
            except OSError as error:
                raise GitCommandFailed(
                    f"{contract_name}: failed to start Git"
                ) from error
            try:
                return_code = process.wait(
                    timeout=self._contracts.timeout_seconds(contract_name)
                )
            except subprocess.TimeoutExpired as error:
                _terminate_owned_process(process)
                raise GitCommandTimedOut(contract_name) from error

            stdout_file.seek(0, os.SEEK_END)
            stdout_size = stdout_file.tell()
            stdout_file.seek(0)
            stdout_bytes = stdout_file.read(max_bytes + 1)
            stderr_file.seek(0)
            stderr_bytes = stderr_file.read(65_537)
        stdout = _decode_git_output(
            stdout_bytes[:max_bytes],
            truncated=stdout_size > max_bytes,
        )
        stderr = _decode_git_output(
            stderr_bytes[:65_536],
            truncated=len(stderr_bytes) > 65_536,
        )
        if return_code != 0:
            raise GitCommandFailed(
                f"{contract_name} exited {return_code}: {stderr[:512]}"
            )
        return GitProcessResult(
            stdout=stdout,
            stderr=stderr,
            stdout_bytes=stdout_size,
            truncated=stdout_size > max_bytes,
        )


def _minimal_environment() -> dict[str, str]:
    environment = {
        key: value
        for key in ("SystemRoot", "WINDIR", "TMP", "TEMP", "TMPDIR")
        if (value := os.environ.get(key))
    }
    environment.update(
        {
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_LITERAL_PATHSPECS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PAGER": "cat",
        }
    )
    return environment


def _assert_git_metadata_safe(git_directory: Path) -> None:
    pending = [git_directory]
    scanned = 0
    while pending:
        directory = pending.pop()
        try:
            children = os.scandir(directory)
        except OSError as error:
            raise GitWorkspaceRejected("Git metadata cannot be scanned") from error
        with children:
            for child in children:
                scanned += 1
                if scanned > MAX_GIT_METADATA_ENTRIES:
                    raise GitWorkspaceRejected(
                        "Git metadata exceeds the safety scan bound"
                    )
                try:
                    child_stat = child.stat(follow_symlinks=False)
                except OSError as error:
                    raise GitWorkspaceRejected(
                        "Git metadata changed during safety scan"
                    ) from error
                child_path = Path(child.path)
                if _is_link_or_reparse(child_path, child_stat):
                    raise GitWorkspaceRejected(
                        "Git metadata links and reparse points are forbidden"
                    )
                if stat.S_ISDIR(child_stat.st_mode):
                    pending.append(child_path)
                elif not stat.S_ISREG(child_stat.st_mode):
                    raise GitWorkspaceRejected(
                        "special files in Git metadata are forbidden"
                    )

    alternates = git_directory / "objects" / "info" / "alternates"
    commondir = git_directory / "commondir"
    if alternates.exists() or commondir.exists():
        raise GitWorkspaceRejected(
            "external object stores and linked worktrees are forbidden"
        )

    config = git_directory / "config"
    try:
        config_bytes = config.read_bytes()
    except OSError as error:
        raise GitWorkspaceRejected("Git config is unavailable") from error
    if len(config_bytes) > MAX_GIT_CONFIG_BYTES:
        raise GitWorkspaceRejected("Git config exceeds the safety bound")
    if _CONFIG_INCLUDE_SECTION.search(config_bytes):
        raise GitWorkspaceRejected("Git config include sections are forbidden")


def _terminate_owned_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.terminate()
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def _decode_git_output(value: bytes, *, truncated: bool = False) -> str:
    try:
        if not truncated:
            return value.decode("utf-8")
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        return decoder.decode(value, final=False)
    except UnicodeDecodeError as error:
        raise GitOutputDecodingError("Git output is not UTF-8") from error


def _result(
    workspace_id: str,
    process: GitProcessResult,
    *,
    nul_delimited: bool = False,
) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "output": process.stdout,
        "stderr": process.stderr,
        "output_bytes": process.stdout_bytes,
        "truncated": process.truncated,
        "nul_delimited": nul_delimited,
    }
