"""Execute one queued tool plan through a port and verify its receipt."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .ports import (
    ToolExecutionPort,
    ToolExecutionPortError,
    ToolExecutionReceipt,
)
from .tool_planner import ToolPlan
from ..domain.digests import sha256_json
from ..domain.errors import InvalidTransition
from ..domain.tool_execution import ToolExecution, ToolExecutionState


@dataclass(frozen=True, slots=True)
class ToolExecutionOutcome:
    execution: ToolExecution
    receipt: ToolExecutionReceipt | None
    error_code: str | None

    @property
    def succeeded(self) -> bool:
        return self.execution.state is ToolExecutionState.SUCCEEDED


class ExecuteQueuedTool:
    def __init__(self, port: ToolExecutionPort) -> None:
        self._port = port

    def execute(
        self,
        plan: ToolPlan,
        *,
        expected_execution_version: int,
        now: datetime | None = None,
    ) -> ToolExecutionOutcome:
        if plan.execution is None:
            raise InvalidTransition("plan has no execution")
        observed_at = now or datetime.now(timezone.utc)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        running = plan.execution.transition(
            ToolExecutionState.RUNNING,
            expected_version=expected_execution_version,
            reason="executor_dispatch_started",
            now=observed_at,
        )
        dispatch_plan = replace(plan, execution=running)
        try:
            receipt = self._port.execute(
                dispatch_plan,
                requested_at=observed_at,
            )
        except ToolExecutionPortError:
            return ToolExecutionOutcome(
                execution=running.transition(
                    ToolExecutionState.FAILED,
                    expected_version=running.version,
                    reason="executor_dispatch_failed",
                    now=observed_at,
                ),
                receipt=None,
                error_code="TOOL_EXECUTOR_REQUEST_FAILED",
            )

        verifying = running.transition(
            ToolExecutionState.VERIFYING,
            expected_version=running.version,
            reason="executor_receipt_received",
            now=observed_at,
        )
        if (
            receipt.execution_id != verifying.execution_id
            or sha256_json(dict(receipt.result)) != receipt.result_sha256
        ):
            return ToolExecutionOutcome(
                execution=verifying.transition(
                    ToolExecutionState.FAILED,
                    expected_version=verifying.version,
                    reason="executor_receipt_verification_failed",
                    now=observed_at,
                ),
                receipt=None,
                error_code="TOOL_EXECUTOR_RECEIPT_INVALID",
            )

        succeeded = verifying.transition(
            ToolExecutionState.SUCCEEDED,
            expected_version=verifying.version,
            reason=(
                "executor_duplicate_receipt_verified"
                if receipt.duplicate
                else "executor_receipt_verified"
            ),
            now=observed_at,
        )
        return ToolExecutionOutcome(
            execution=succeeded,
            receipt=receipt,
            error_code=None,
        )
