"""Registered, evidence-producing process adapter for the local vLLM runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from ..application.model_router import ModelId
from ..application.model_switch import (
    RuntimeActionReceipt,
    RuntimeProcessError,
)


_MODEL_SIZE = {
    ModelId.GEMMA4_12B: "12b",
    ModelId.GEMMA4_31B: "31b",
}
_SERVED_MODEL = {
    ModelId.GEMMA4_12B: "gemma4-12b",
    ModelId.GEMMA4_31B: "gemma4-31b",
}
_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "CUDA_VISIBLE_DEVICES",
        "HOME",
        "LANG",
        "LC_ALL",
        "LD_LIBRARY_PATH",
        "LOGNAME",
        "PATH",
        "SHELL",
        "USER",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeCommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


CommandRunner = Callable[
    [tuple[str, ...], Mapping[str, str], float],
    Awaitable[RuntimeCommandResult],
]
HttpGet = Callable[[str, str | None, float], bytes]
PortProbe = Callable[[str, int], bool]


@dataclass(frozen=True, slots=True)
class RegisteredVllmSettings:
    api_key: str
    base_url: str
    start_script: Path
    stop_script: Path
    status_path: Path
    evidence_directory: Path
    command_timeout_seconds: float = 960
    health_timeout_seconds: float = 5

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("vLLM runtime URL must be loopback HTTP")
        if parsed.path not in {"", "/"}:
            raise ValueError("vLLM runtime URL must not include an API path")
        if len(self.api_key) < 32:
            raise ValueError("vLLM runtime API key is invalid")
        for path in (self.start_script, self.stop_script):
            if not path.is_absolute() or not path.is_file():
                raise ValueError(f"registered runtime script is unavailable: {path}")
        if not self.status_path.is_absolute():
            raise ValueError("runtime status path must be absolute")
        if not self.evidence_directory.is_absolute():
            raise ValueError("runtime evidence directory must be absolute")
        if not 90 <= self.command_timeout_seconds <= 1_200:
            raise ValueError("runtime command timeout is invalid")
        if not 1 <= self.health_timeout_seconds <= 30:
            raise ValueError("runtime health timeout is invalid")


class RegisteredVllmRuntimeAdapter:
    def __init__(
        self,
        settings: RegisteredVllmSettings,
        *,
        command_runner: CommandRunner | None = None,
        http_get: HttpGet | None = None,
        port_probe: PortProbe | None = None,
    ) -> None:
        self._settings = settings
        self._command_runner = command_runner or _run_command
        self._http_get = http_get or _http_get
        self._port_probe = port_probe or _port_open

    async def start(self, model_id: ModelId) -> RuntimeActionReceipt:
        result = await self._execute(
            "start",
            model_id,
            (
                "bash",
                str(self._settings.start_script),
            ),
            {
                "LVA_VLLM_API_KEY": self._settings.api_key,
                "LVA_VLLM_MODEL_SIZE": _MODEL_SIZE[model_id],
                "LVA_VLLM_MTP_MODE": "off",
                "LVA_VLLM_PORT": str(self._port),
                "LVA_VLLM_STARTUP_TIMEOUT_SECONDS": str(
                    min(
                        900,
                        max(
                            60,
                            int(self._settings.command_timeout_seconds) - 30,
                        ),
                    )
                ),
            },
        )
        return RuntimeActionReceipt(
            model_id=model_id,
            action="start",
            evidence_path=result,
        )

    async def health_check(self, model_id: ModelId) -> RuntimeActionReceipt:
        try:
            details = await asyncio.to_thread(
                self._verify_health,
                model_id,
            )
        except Exception as error:
            evidence_path = self._write_evidence(
                action="health",
                model_id=model_id,
                success=False,
                details={"error": type(error).__name__},
            )
            raise RuntimeProcessError(
                "vLLM health verification failed",
                code="VLLM_HEALTH_FAILED",
                evidence_path=evidence_path,
            ) from error

        evidence_path = self._write_evidence(
            action="health",
            model_id=model_id,
            success=True,
            details=details,
        )
        return RuntimeActionReceipt(
            model_id=model_id,
            action="health",
            evidence_path=evidence_path,
        )

    def observe_ready_model(self) -> ModelId | None:
        """Return an independently verified ready model, never status alone."""

        try:
            status = self._load_status()
            configured = status.get("model_id")
            model_id = next(
                (
                    candidate
                    for candidate, served_name in _SERVED_MODEL.items()
                    if served_name == configured
                ),
                None,
            )
            if model_id is None:
                return None
            self._verify_health(model_id)
            return model_id
        except Exception:
            return None

    async def stop(self, model_id: ModelId) -> RuntimeActionReceipt:
        evidence_path = await self._execute(
            "stop",
            model_id,
            (
                "bash",
                str(self._settings.stop_script),
            ),
            {
                "LVA_VLLM_EXPECTED_MODEL_SIZE": _MODEL_SIZE[model_id],
            },
        )
        if await asyncio.to_thread(
            self._port_probe,
            self._hostname,
            self._port,
        ):
            failed_evidence = self._write_evidence(
                action="stop",
                model_id=model_id,
                success=False,
                details={"error": "listener_still_open", "port": self._port},
            )
            raise RuntimeProcessError(
                "vLLM listener remained open after stop",
                code="VLLM_STOP_FAILED",
                evidence_path=failed_evidence,
            )
        return RuntimeActionReceipt(
            model_id=model_id,
            action="stop",
            evidence_path=evidence_path,
        )

    @property
    def _port(self) -> int:
        parsed = urlparse(self._settings.base_url)
        return parsed.port or 80

    @property
    def _hostname(self) -> str:
        hostname = urlparse(self._settings.base_url).hostname
        if hostname is None:
            raise RuntimeError("validated runtime URL has no hostname")
        return hostname

    async def _execute(
        self,
        action: str,
        model_id: ModelId,
        argv: tuple[str, ...],
        additions: Mapping[str, str],
    ) -> str:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in _ENVIRONMENT_ALLOWLIST
        }
        environment.update(additions)
        result = await self._command_runner(
            argv,
            environment,
            self._settings.command_timeout_seconds,
        )
        details = {
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "stdout_tail": self._redact(result.stdout)[-4_096:],
            "stderr_tail": self._redact(result.stderr)[-4_096:],
        }
        success = result.exit_code == 0 and not result.timed_out
        evidence_path = self._write_evidence(
            action=action,
            model_id=model_id,
            success=success,
            details=details,
        )
        if not success:
            code = (
                f"VLLM_{action.upper()}_TIMEOUT"
                if result.timed_out
                else f"VLLM_{action.upper()}_FAILED"
            )
            raise RuntimeProcessError(
                f"registered vLLM {action} failed",
                code=code,
                evidence_path=evidence_path,
            )
        return evidence_path

    def _load_status(self) -> dict[str, object]:
        if not self._settings.status_path.is_file():
            raise ValueError("runtime status file is unavailable")
        if self._settings.status_path.stat().st_size > 64 * 1024:
            raise ValueError("runtime status file is too large")
        value = json.loads(self._settings.status_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("runtime status must be an object")
        return value

    def _verify_health(self, model_id: ModelId) -> dict[str, object]:
        status = self._load_status()
        expected_model = _SERVED_MODEL[model_id]
        if (
            status.get("state") != "ready"
            or status.get("model_id") != expected_model
            or status.get("model_size") != _MODEL_SIZE[model_id]
            or status.get("port") != self._port
        ):
            raise ValueError("runtime status identity mismatch")
        pid = status.get("pid")
        if not isinstance(pid, int) or pid < 1:
            raise ValueError("runtime status PID is invalid")
        try:
            os.kill(pid, 0)
        except OSError as error:
            raise ValueError("runtime status PID is not alive") from error

        self._http_get(
            self._settings.base_url.rstrip("/") + "/health",
            None,
            self._settings.health_timeout_seconds,
        )
        raw_models = self._http_get(
            self._settings.base_url.rstrip("/") + "/v1/models",
            self._settings.api_key,
            self._settings.health_timeout_seconds,
        )
        if len(raw_models) > 256 * 1024:
            raise ValueError("runtime model response is too large")
        models = json.loads(raw_models)
        if not isinstance(models, dict):
            raise ValueError("runtime model response must be an object")
        identifiers = {
            item.get("id")
            for item in models.get("data", [])
            if isinstance(item, dict)
        }
        if identifiers != {expected_model}:
            raise ValueError("runtime API model identity mismatch")
        return {
            "pid": pid,
            "model_id": expected_model,
            "port": self._port,
        }

    def _write_evidence(
        self,
        *,
        action: str,
        model_id: ModelId,
        success: bool,
        details: Mapping[str, object],
    ) -> str:
        self._settings.evidence_directory.mkdir(parents=True, exist_ok=True)
        evidence_id = uuid4()
        destination = (
            self._settings.evidence_directory
            / f"vllm-{model_id.value}-{action}-{evidence_id}.json"
        )
        temporary = destination.with_suffix(".json.tmp")
        payload = {
            "schema_version": "1.0",
            "evidence_id": str(evidence_id),
            "component": "registered_vllm_runtime",
            "action": action,
            "model_id": model_id.value,
            "success": success,
            "details": dict(details),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, destination)
        return str(destination)

    def _redact(self, value: str) -> str:
        return value.replace(self._settings.api_key, "<redacted>")


async def _run_command(
    argv: tuple[str, ...],
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> RuntimeCommandResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        env=dict(environment),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
        return RuntimeCommandResult(
            exit_code=-1,
            stdout="",
            stderr="registered runtime wrapper timed out",
            timed_out=True,
        )
    return RuntimeCommandResult(
        exit_code=process.returncode,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


def _http_get(url: str, api_key: str | None, timeout_seconds: float) -> bytes:
    headers = {"Accept": "application/json"}
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(256 * 1024 + 1)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError("runtime HTTP check failed") from error
    if len(body) > 256 * 1024:
        raise RuntimeError("runtime HTTP response is too large")
    return body


def _port_open(hostname: str, port: int) -> bool:
    try:
        with socket.create_connection((hostname, port), timeout=0.5):
            return True
    except OSError:
        return False
