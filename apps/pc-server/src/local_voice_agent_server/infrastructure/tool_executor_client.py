"""Authenticated loopback adapter for the standalone Tool Executor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address, IPv4Network, ip_address
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from ..application.ports import ToolExecutionPortError, ToolExecutionReceipt
from ..application.tool_planner import ToolPlan
from ..domain.approval import ApprovalState
from ..domain.policy import PolicyAction, RiskLevel
from ..domain.tool_execution import ToolExecutionState


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
EXECUTION_TTL = timedelta(minutes=2)
RFC1918_NETWORKS = tuple(
    IPv4Network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
Transport = Callable[[str, bytes, dict[str, str], float, int], bytes]


class ToolExecutorClientError(ToolExecutionPortError):
    """Sanitized failure at the isolated executor boundary."""


@dataclass(frozen=True, slots=True)
class ToolExecutorClientSettings:
    base_url: str
    ipc_token: str
    allowed_wsl_gateway: str | None = None
    timeout_seconds: float = 30.0
    max_response_bytes: int = MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        allowed_hosts = {"127.0.0.1", "::1"}
        if self.allowed_wsl_gateway is not None:
            try:
                gateway = ip_address(self.allowed_wsl_gateway)
            except ValueError as error:
                raise ValueError("WSL gateway must be an explicit IP address") from error
            if (
                not isinstance(gateway, IPv4Address)
                or not any(gateway in network for network in RFC1918_NETWORKS)
                or gateway.is_loopback
                or gateway.is_unspecified
                or gateway.is_multicast
            ):
                raise ValueError(
                    "WSL gateway must be a private non-loopback IPv4 address"
                )
            if str(gateway) != self.allowed_wsl_gateway:
                raise ValueError("WSL gateway must use canonical IPv4 notation")
            allowed_hosts.add(str(gateway))
        if (
            parsed.scheme != "http"
            or parsed.hostname not in allowed_hosts
            or parsed.port is None
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Tool Executor URL must use loopback or the exact approved WSL gateway"
            )
        if len(self.ipc_token) < 32 or self.ipc_token == "CHANGE_ME":
            raise ValueError("Tool Executor IPC token is invalid")
        if not 0.1 <= self.timeout_seconds <= 300:
            raise ValueError("Tool Executor timeout is outside the safety range")
        if not 1_024 <= self.max_response_bytes <= 64 * 1024 * 1024:
            raise ValueError("Tool Executor response bound is invalid")


class HttpToolExecutionAdapter:
    def __init__(
        self,
        settings: ToolExecutorClientSettings,
        *,
        transport: Transport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or _post_json

    def execute(
        self,
        plan: ToolPlan,
        *,
        requested_at: datetime | None = None,
    ) -> ToolExecutionReceipt:
        execution = plan.execution
        if execution is None or execution.state is not ToolExecutionState.RUNNING:
            raise ToolExecutorClientError(
                "only running plans may execute"
            )
        approval = plan.approval
        if plan.policy.risk_level is RiskLevel.OBSERVE:
            if plan.policy.action is not PolicyAction.ALLOW or approval is not None:
                raise ToolExecutorClientError(
                    "Level 0 execution has invalid policy binding"
                )
        elif plan.policy.risk_level is RiskLevel.REVERSIBLE_LOCAL:
            if (
                plan.policy.action is not PolicyAction.REQUIRE_APPROVAL
                or approval is None
                or approval.state is not ApprovalState.APPROVED
                or approval.normalized_arguments_sha256
                != execution.normalized_arguments_sha256
                or approval.tool_call_id != execution.tool_call_id
            ):
                raise ToolExecutorClientError(
                    "Level 1 execution lacks exact approved binding"
                )
        else:
            raise ToolExecutorClientError(
                "Tool Executor client rejects Level 2 and Level 3"
            )
        observed_at = requested_at or datetime.now(timezone.utc)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ToolExecutorClientError("requested_at must be timezone-aware")

        payload = {
            "schema_version": "1.0",
            "execution_id": execution.execution_id,
            "session_id": execution.session_id,
            "request_id": execution.request_id,
            "tool_call_id": execution.tool_call_id,
            "idempotency_key": execution.idempotency_key,
            "tool_name": execution.tool_name,
            "arguments": dict(plan.normalized_arguments),
            "normalized_arguments_sha256": (
                execution.normalized_arguments_sha256
            ),
            "tool_definition_sha256": (
                plan.policy.tool_definition_sha256
            ),
            "risk_level": int(plan.policy.risk_level),
            "requested_at": observed_at.isoformat(),
            "expires_at": (observed_at + EXECUTION_TTL).isoformat(),
            "approval_id": (
                approval.approval_id if approval is not None else None
            ),
            "approval_arguments_sha256": (
                approval.normalized_arguments_sha256
                if approval is not None
                else None
            ),
            "approval_expires_at": (
                approval.expires_at.isoformat()
                if approval is not None
                else None
            ),
        }
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            response_body = self._transport(
                f"{self._settings.base_url.rstrip('/')}/v1/executions",
                body,
                {
                    "Authorization": f"Bearer {self._settings.ipc_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                self._settings.timeout_seconds,
                self._settings.max_response_bytes,
            )
            response = json.loads(response_body)
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise ToolExecutorClientError(
                "Tool Executor request failed"
            ) from error
        return _parse_receipt(response, expected_execution_id=execution.execution_id)


def _post_json(
    url: str,
    body: bytes,
    headers: dict[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
) -> bytes:
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise ToolExecutorClientError("Tool Executor returned an error")
        data = response.read(max_response_bytes + 1)
    if len(data) > max_response_bytes:
        raise ToolExecutorClientError("Tool Executor response exceeds limit")
    return data


def _parse_receipt(
    value: Any,
    *,
    expected_execution_id: str,
) -> ToolExecutionReceipt:
    if not isinstance(value, dict):
        raise ToolExecutorClientError("Tool Executor response is invalid")
    expected_keys = {
        "schema_version",
        "execution_id",
        "status",
        "duplicate",
        "result",
        "result_sha256",
        "evidence_id",
    }
    if set(value) != expected_keys:
        raise ToolExecutorClientError("Tool Executor response is invalid")
    if (
        value["schema_version"] != "1.0"
        or value["execution_id"] != expected_execution_id
        or value["status"] != "succeeded"
        or not isinstance(value["duplicate"], bool)
        or not isinstance(value["result"], dict)
        or not _is_sha256(value["result_sha256"])
        or not _is_canonical_uuid(value["evidence_id"])
    ):
        raise ToolExecutorClientError("Tool Executor response is invalid")
    return ToolExecutionReceipt(
        execution_id=value["execution_id"],
        duplicate=value["duplicate"],
        result=value["result"],
        result_sha256=value["result_sha256"],
        evidence_id=value["evidence_id"],
    )


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_canonical_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False
