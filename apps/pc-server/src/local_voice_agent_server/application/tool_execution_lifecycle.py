"""Durable lifecycle around the isolated, side-effecting Tool Executor."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, Mapping, Protocol
from uuid import UUID

from .execute_tool import ExecuteQueuedTool, ToolExecutionOutcome
from .tool_planner import ToolPlan
from ..domain.tool_execution import ToolExecutionState


class ToolLifecycleStore(Protocol):
    async def persist_planned_plan(self, plan: ToolPlan) -> Any: ...

    async def decide_approval(
        self,
        *,
        approval_id: str,
        approved: bool,
        arguments_digest: str,
        precondition_version: int,
        expected_approval_version: int,
        reason: str | None,
    ) -> Any: ...

    async def transition_tool_execution(
        self,
        execution_id: Any,
        *,
        expected_version: int,
        to_state: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        result_metadata: Mapping[str, Any] | None = None,
    ) -> Any: ...


class DurableToolExecutionLifecycle:
    """Fail-closed persistence boundary for every executable ToolPlan."""

    def __init__(self, *, store: ToolLifecycleStore, executor: ExecuteQueuedTool) -> None:
        self._store = store
        self._executor = executor

    async def persist_plan(self, plan: ToolPlan) -> None:
        if plan.execution is not None:
            await self._store.persist_planned_plan(plan)

    async def decide_approval(
        self,
        plan: ToolPlan,
        *,
        approved: bool,
        arguments_digest: str,
        reason: str | None,
    ) -> None:
        approval = plan.approval
        if approval is None:
            raise ValueError("plan has no approval")
        await self._store.decide_approval(
            approval_id=approval.approval_id,
            approved=approved,
            arguments_digest=arguments_digest,
            precondition_version=approval.precondition_version,
            expected_approval_version=approval.version,
            reason=reason,
        )

    async def execute(self, plan: ToolPlan) -> ToolExecutionOutcome:
        execution = plan.execution
        if execution is None or execution.state is not ToolExecutionState.QUEUED:
            raise ValueError("only queued plans can enter the durable lifecycle")

        running = await self._store.transition_tool_execution(
            UUID(execution.execution_id),
            expected_version=execution.version,
            to_state=ToolExecutionState.RUNNING.value,
            event_type="tool.started",
        )
        running_execution = replace(
            execution,
            state=ToolExecutionState.RUNNING,
            version=running.version,
        )
        running_plan = replace(plan, execution=running_execution)
        outcome = await asyncio.to_thread(
            self._executor.execute_running,
            running_plan,
        )

        if outcome.receipt is None and outcome.error_code != "TOOL_EXECUTOR_RECEIPT_INVALID":
            await self._store.transition_tool_execution(
                execution.execution_id,
                expected_version=running.version,
                to_state=ToolExecutionState.FAILED.value,
                event_type="tool.failed",
                payload={"error_code": outcome.error_code or "TOOL_EXECUTOR_FAILED"},
            )
            return outcome

        verifying = await self._store.transition_tool_execution(
            execution.execution_id,
            expected_version=running.version,
            to_state=ToolExecutionState.VERIFYING.value,
            event_type="tool.verifying",
        )
        if outcome.succeeded and outcome.receipt is not None:
            await self._store.transition_tool_execution(
                execution.execution_id,
                expected_version=verifying.version,
                to_state=ToolExecutionState.SUCCEEDED.value,
                event_type="tool.completed",
                result_metadata={
                    "evidence_id": outcome.receipt.evidence_id,
                    "result_sha256": outcome.receipt.result_sha256,
                    "duplicate": outcome.receipt.duplicate,
                },
            )
            return outcome

        await self._store.transition_tool_execution(
            execution.execution_id,
            expected_version=verifying.version,
            to_state=ToolExecutionState.FAILED.value,
            event_type="tool.failed",
            payload={"error_code": outcome.error_code or "TOOL_EXECUTOR_RECEIPT_INVALID"},
        )
        return outcome
