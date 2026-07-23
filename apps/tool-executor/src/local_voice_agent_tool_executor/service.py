"""Bound execution service with in-process idempotency and metadata evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
from threading import RLock
from time import perf_counter
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from .audit import AuditEvidenceStore, utc_now
from .digests import sha256_json
from .errors import (
    ExecutionBindingError,
    ExecutionExpired,
    IdempotencyConflict,
    InternalExecutionError,
    ToolExecutorError,
)
from .executor import ReadOnlyToolExecutor


MAX_EXECUTION_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class ExecutionCommand:
    execution_id: str
    session_id: str
    request_id: str
    tool_call_id: str
    idempotency_key: str
    tool_name: str
    arguments: Mapping[str, Any]
    normalized_arguments_sha256: str
    tool_definition_sha256: str
    risk_level: int
    requested_at: datetime
    expires_at: datetime
    approval_id: str | None = None
    approval_arguments_sha256: str | None = None
    approval_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class _CachedExecution:
    fingerprint: str
    response: Mapping[str, Any] | None = None
    error_type: type[ToolExecutorError] | None = None


class BoundExecutionService:
    def __init__(
        self,
        *,
        executor: ReadOnlyToolExecutor,
        audit_store: AuditEvidenceStore,
    ) -> None:
        self._executor = executor
        self._audit = audit_store
        self._lock = RLock()
        self._completed: dict[str, _CachedExecution] = {}

    def execute(
        self,
        command: ExecutionCommand,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = now or utc_now()
        self._validate_identifiers(command)
        arguments = dict(command.arguments)
        actual_arguments_sha256 = self._executor.validate_arguments(
            command.tool_name,
            arguments,
        )
        actual_definition_sha256 = self._executor.definition_sha256(
            command.tool_name
        )
        if self._executor.risk_level(command.tool_name) != command.risk_level:
            raise ExecutionBindingError("tool risk level mismatch")
        if not hmac.compare_digest(
            actual_arguments_sha256,
            command.normalized_arguments_sha256,
        ):
            raise ExecutionBindingError("normalized argument digest mismatch")
        if not hmac.compare_digest(
            actual_definition_sha256,
            command.tool_definition_sha256,
        ):
            raise ExecutionBindingError("tool definition digest mismatch")
        self._validate_approval(
            command,
            arguments_sha256=actual_arguments_sha256,
            observed_at=observed_at,
        )
        if self._executor.idempotency(command.tool_name) == "required":
            argument_key = arguments.get("idempotency_key")
            if argument_key != command.idempotency_key:
                raise ExecutionBindingError(
                    "tool argument idempotency key mismatch"
                )

        fingerprint = sha256_json(
            {
                "execution_id": command.execution_id,
                "session_id": command.session_id,
                "request_id": command.request_id,
                "tool_call_id": command.tool_call_id,
                "tool_name": command.tool_name,
                "normalized_arguments_sha256": actual_arguments_sha256,
                "tool_definition_sha256": actual_definition_sha256,
                "risk_level": command.risk_level,
                "requested_at": command.requested_at.isoformat(),
                "expires_at": command.expires_at.isoformat(),
                "approval_id": command.approval_id,
                "approval_arguments_sha256": (
                    command.approval_arguments_sha256
                ),
                "approval_expires_at": (
                    command.approval_expires_at.isoformat()
                    if command.approval_expires_at is not None
                    else None
                ),
            }
        )
        with self._lock:
            cached = self._completed.get(command.idempotency_key)
            if cached is not None:
                if not hmac.compare_digest(cached.fingerprint, fingerprint):
                    raise IdempotencyConflict(
                        "idempotency key is bound to a different execution"
                    )
                if cached.error_type is not None:
                    raise cached.error_type("cached failed execution")
                if cached.response is None:
                    raise InternalExecutionError("cached execution is incomplete")
                duplicate = dict(cached.response)
                duplicate["duplicate"] = True
                return duplicate
            self._validate_time(command, observed_at)
            return self._execute_once(
                command,
                arguments=arguments,
                arguments_sha256=actual_arguments_sha256,
                definition_sha256=actual_definition_sha256,
                fingerprint=fingerprint,
                observed_at=observed_at,
            )

    def _execute_once(
        self,
        command: ExecutionCommand,
        *,
        arguments: dict[str, Any],
        arguments_sha256: str,
        definition_sha256: str,
        fingerprint: str,
        observed_at: datetime,
    ) -> dict[str, Any]:
        idempotency_sha256 = sha256_json(command.idempotency_key)
        started = _audit_event(
            command,
            timestamp=observed_at,
            result="started",
            metadata={
                "execution_id": command.execution_id,
                "idempotency_key_sha256": idempotency_sha256,
                "normalized_arguments_sha256": arguments_sha256,
                "tool_definition_sha256": definition_sha256,
            },
        )
        self._audit.append_event(started)
        started_counter = perf_counter()
        try:
            execution_result = self._executor.execute(
                command.tool_name,
                arguments,
                execution_id=command.execution_id,
            )
            result_sha256 = sha256_json(execution_result)
            latency_ms = (perf_counter() - started_counter) * 1000
            completed_at = utc_now()
            evidence = {
                "schema_version": "1.0",
                "execution_id": command.execution_id,
                "session_id": command.session_id,
                "request_id": command.request_id,
                "tool_call_id": command.tool_call_id,
                "tool_name": command.tool_name,
                "risk_level": command.risk_level,
                "approval_id": command.approval_id,
                "normalized_arguments_sha256": arguments_sha256,
                "tool_definition_sha256": definition_sha256,
                "idempotency_key_sha256": idempotency_sha256,
                "status": "succeeded",
                "result_sha256": result_sha256,
                "error_code": None,
                "started_at": observed_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "latency_ms": round(latency_ms, 3),
            }
            reference = self._audit.write_evidence(
                execution_id=command.execution_id,
                evidence=evidence,
            )
            self._audit.append_event(
                _audit_event(
                    command,
                    timestamp=completed_at,
                    result="succeeded",
                    latency_ms=latency_ms,
                    evidence_path=str(reference.path),
                    metadata={
                        "execution_id": command.execution_id,
                        "result_sha256": result_sha256,
                    },
                )
            )
            response: dict[str, Any] = {
                "schema_version": "1.0",
                "execution_id": command.execution_id,
                "status": "succeeded",
                "duplicate": False,
                "result": execution_result,
                "result_sha256": result_sha256,
                "evidence_id": reference.evidence_id,
            }
            self._completed[command.idempotency_key] = _CachedExecution(
                fingerprint=fingerprint,
                response=MappingProxyType(dict(response)),
            )
            return response
        except ToolExecutorError as error:
            self._record_failure(
                command,
                arguments_sha256=arguments_sha256,
                definition_sha256=definition_sha256,
                idempotency_sha256=idempotency_sha256,
                observed_at=observed_at,
                started_counter=started_counter,
                error_code=error.code,
            )
            self._completed[command.idempotency_key] = _CachedExecution(
                fingerprint=fingerprint,
                error_type=type(error),
            )
            raise
        except Exception as error:
            self._record_failure(
                command,
                arguments_sha256=arguments_sha256,
                definition_sha256=definition_sha256,
                idempotency_sha256=idempotency_sha256,
                observed_at=observed_at,
                started_counter=started_counter,
                error_code=InternalExecutionError.code,
            )
            self._completed[command.idempotency_key] = _CachedExecution(
                fingerprint=fingerprint,
                error_type=InternalExecutionError,
            )
            raise InternalExecutionError("unexpected executor failure") from error

    def _record_failure(
        self,
        command: ExecutionCommand,
        *,
        arguments_sha256: str,
        definition_sha256: str,
        idempotency_sha256: str,
        observed_at: datetime,
        started_counter: float,
        error_code: str,
    ) -> None:
        latency_ms = (perf_counter() - started_counter) * 1000
        completed_at = utc_now()
        evidence = {
            "schema_version": "1.0",
            "execution_id": command.execution_id,
            "session_id": command.session_id,
            "request_id": command.request_id,
            "tool_call_id": command.tool_call_id,
            "tool_name": command.tool_name,
            "risk_level": command.risk_level,
            "normalized_arguments_sha256": arguments_sha256,
            "tool_definition_sha256": definition_sha256,
            "idempotency_key_sha256": idempotency_sha256,
            "status": "failed",
            "result_sha256": None,
            "error_code": error_code,
            "started_at": observed_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "latency_ms": round(latency_ms, 3),
        }
        reference = self._audit.write_evidence(
            execution_id=command.execution_id,
            evidence=evidence,
        )
        self._audit.append_event(
            _audit_event(
                command,
                timestamp=completed_at,
                result="failed",
                latency_ms=latency_ms,
                evidence_path=str(reference.path),
                error_code=error_code,
                metadata={"execution_id": command.execution_id},
            )
        )

    @staticmethod
    def _validate_identifiers(command: ExecutionCommand) -> None:
        for name, value in (
            ("execution_id", command.execution_id),
            ("session_id", command.session_id),
            ("request_id", command.request_id),
            ("tool_call_id", command.tool_call_id),
            ("idempotency_key", command.idempotency_key),
        ):
            try:
                parsed = UUID(value)
            except (ValueError, TypeError, AttributeError) as error:
                raise ExecutionBindingError(f"{name} must be a UUID") from error
            if str(parsed) != value.lower():
                raise ExecutionBindingError(f"{name} must be canonical UUID text")
        if command.approval_id is not None:
            try:
                parsed_approval = UUID(command.approval_id)
            except (ValueError, TypeError, AttributeError) as error:
                raise ExecutionBindingError(
                    "approval_id must be a UUID"
                ) from error
            if str(parsed_approval) != command.approval_id.lower():
                raise ExecutionBindingError(
                    "approval_id must be canonical UUID text"
                )

    @staticmethod
    def _validate_approval(
        command: ExecutionCommand,
        *,
        arguments_sha256: str,
        observed_at: datetime,
    ) -> None:
        approval_values = (
            command.approval_id,
            command.approval_arguments_sha256,
            command.approval_expires_at,
        )
        if command.risk_level == 0:
            if any(value is not None for value in approval_values):
                raise ExecutionBindingError(
                    "Level 0 execution must not contain approval binding"
                )
            return
        if command.risk_level != 1 or any(
            value is None for value in approval_values
        ):
            raise ExecutionBindingError(
                "Level 1 execution requires exact approval binding"
            )
        assert command.approval_arguments_sha256 is not None
        assert command.approval_expires_at is not None
        if not hmac.compare_digest(
            command.approval_arguments_sha256,
            arguments_sha256,
        ):
            raise ExecutionBindingError("approval argument digest mismatch")
        if (
            command.approval_expires_at.tzinfo is None
            or command.approval_expires_at.utcoffset() is None
        ):
            raise ExecutionBindingError(
                "approval_expires_at must be timezone-aware"
            )
        if observed_at >= command.approval_expires_at:
            raise ExecutionExpired("approval expired")

    @staticmethod
    def _validate_time(
        command: ExecutionCommand,
        observed_at: datetime,
    ) -> None:
        for name, value in (
            ("requested_at", command.requested_at),
            ("expires_at", command.expires_at),
            ("now", observed_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ExecutionBindingError(f"{name} must be timezone-aware")
        if command.expires_at <= command.requested_at:
            raise ExecutionBindingError("expires_at must follow requested_at")
        if command.expires_at - command.requested_at > MAX_EXECUTION_TTL:
            raise ExecutionBindingError("execution TTL exceeds five minutes")
        if observed_at >= command.expires_at:
            raise ExecutionExpired("execution request expired")
        if command.requested_at > observed_at + timedelta(seconds=30):
            raise ExecutionBindingError("requested_at is too far in the future")


def _audit_event(
    command: ExecutionCommand,
    *,
    timestamp: datetime,
    result: str,
    metadata: Mapping[str, Any],
    latency_ms: float | None = None,
    evidence_path: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
        "level": "error" if result == "failed" else "info",
        "session_id": command.session_id,
        "request_id": command.request_id,
        "tool_call_id": command.tool_call_id,
        "component": "tool_executor",
        "event": "tool.execution",
        "model": None,
        "runtime": "tool-executor-0.1.0",
        "latency_ms": None if latency_ms is None else round(latency_ms, 3),
        "risk_level": command.risk_level,
        "approval_id": command.approval_id,
        "result": result,
        "error_code": error_code,
        "evidence_path": evidence_path,
        "metadata": dict(metadata),
    }
