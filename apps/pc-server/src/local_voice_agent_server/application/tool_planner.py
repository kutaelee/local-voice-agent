"""Plan a validated tool request without executing it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from ..domain.approval import ApprovalRequest
from ..domain.digests import sha256_json
from ..domain.policy import PolicyAction, PolicyDecision, evaluate_policy
from ..domain.tool_execution import ToolExecution, ToolExecutionState
from ..infrastructure.tool_registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class ToolPlan:
    tool_name: str
    normalized_arguments: Mapping[str, Any]
    policy: PolicyDecision
    execution: ToolExecution | None
    approval: ApprovalRequest | None


class ToolPlanner:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        approval_ttl: timedelta = timedelta(minutes=2),
    ) -> None:
        if approval_ttl <= timedelta(0):
            raise ValueError("approval_ttl must be positive")
        self._registry = registry
        self._approval_ttl = approval_ttl

    def plan(
        self,
        *,
        session_id: str,
        request_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        idempotency_key: str,
        precondition_version: int,
        session_grant_valid: bool = False,
        now: datetime | None = None,
    ) -> ToolPlan:
        observed_at = now or datetime.now(timezone.utc)
        definition = self._registry.get(tool_name)
        arguments_copy = dict(arguments)

        if definition.enabled:
            arguments_sha256 = self._registry.validate_model_arguments(
                tool_name,
                arguments_copy,
            )
        else:
            arguments_sha256 = sha256_json(arguments_copy)

        decision = evaluate_policy(
            tool_name=tool_name,
            risk_level=definition.risk_level,
            tool_definition_sha256=definition.sha256,
            normalized_arguments_sha256=arguments_sha256,
            session_grant_valid=session_grant_valid,
            tool_enabled=definition.enabled,
        )

        if decision.action is PolicyAction.DENY:
            return ToolPlan(
                tool_name=tool_name,
                normalized_arguments=MappingProxyType(arguments_copy),
                policy=decision,
                execution=None,
                approval=None,
            )

        execution = ToolExecution(
            execution_id=str(uuid4()),
            session_id=session_id,
            request_id=request_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key,
            normalized_arguments_sha256=arguments_sha256,
        )

        if decision.action is PolicyAction.ALLOW:
            execution = execution.transition(
                ToolExecutionState.QUEUED,
                expected_version=0,
                reason="policy_allowed",
                now=observed_at,
            )
            approval = None
        else:
            execution = execution.transition(
                ToolExecutionState.WAITING_APPROVAL,
                expected_version=0,
                reason="policy_requires_approval",
                now=observed_at,
            )
            approval = ApprovalRequest(
                approval_id=str(uuid4()),
                tool_call_id=tool_call_id,
                normalized_arguments_sha256=arguments_sha256,
                precondition_version=precondition_version,
                created_at=observed_at,
                expires_at=observed_at + self._approval_ttl,
            )

        return ToolPlan(
            tool_name=tool_name,
            normalized_arguments=MappingProxyType(arguments_copy),
            policy=decision,
            execution=execution,
            approval=approval,
        )
