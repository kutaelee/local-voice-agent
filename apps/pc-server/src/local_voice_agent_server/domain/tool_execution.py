"""Tool execution aggregate with explicit transitions and CAS versioning."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from .errors import (
    InvalidTransition,
    OperationNotCancellable,
    OptimisticLockError,
)


class ToolExecutionState(str, Enum):
    PLANNED = "PLANNED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"


_ALLOWED_TRANSITIONS: dict[ToolExecutionState, frozenset[ToolExecutionState]] = {
    ToolExecutionState.PLANNED: frozenset(
        {
            ToolExecutionState.WAITING_APPROVAL,
            ToolExecutionState.QUEUED,
            ToolExecutionState.CANCELLED,
        }
    ),
    ToolExecutionState.WAITING_APPROVAL: frozenset(
        {ToolExecutionState.QUEUED, ToolExecutionState.CANCELLED}
    ),
    ToolExecutionState.QUEUED: frozenset(
        {
            ToolExecutionState.RUNNING,
            ToolExecutionState.CANCELLED,
            ToolExecutionState.FAILED,
        }
    ),
    ToolExecutionState.RUNNING: frozenset(
        {
            ToolExecutionState.VERIFYING,
            ToolExecutionState.CANCELLED,
            ToolExecutionState.FAILED,
        }
    ),
    ToolExecutionState.VERIFYING: frozenset(
        {
            ToolExecutionState.SUCCEEDED,
            ToolExecutionState.FAILED,
            ToolExecutionState.ROLLING_BACK,
        }
    ),
    ToolExecutionState.FAILED: frozenset({ToolExecutionState.ROLLING_BACK}),
    ToolExecutionState.ROLLING_BACK: frozenset(
        {ToolExecutionState.ROLLED_BACK, ToolExecutionState.FAILED}
    ),
    ToolExecutionState.SUCCEEDED: frozenset(),
    ToolExecutionState.CANCELLED: frozenset(),
    ToolExecutionState.ROLLED_BACK: frozenset(),
}


@dataclass(frozen=True, slots=True)
class ToolExecutionEvent:
    from_state: ToolExecutionState
    to_state: ToolExecutionState
    version: int
    occurred_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class ToolExecution:
    execution_id: str
    session_id: str
    request_id: str
    tool_call_id: str
    tool_name: str
    idempotency_key: str
    normalized_arguments_sha256: str
    state: ToolExecutionState = ToolExecutionState.PLANNED
    version: int = 0
    cancellable: bool = True
    events: tuple[ToolExecutionEvent, ...] = ()

    def transition(
        self,
        to_state: ToolExecutionState,
        *,
        expected_version: int,
        reason: str,
        now: datetime | None = None,
    ) -> "ToolExecution":
        if expected_version != self.version:
            raise OptimisticLockError(
                f"expected version {expected_version}, current {self.version}"
            )
        if to_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransition(
                f"{self.state.value} cannot transition to {to_state.value}"
            )
        occurred_at = now or datetime.now(timezone.utc)
        new_version = self.version + 1
        event = ToolExecutionEvent(
            from_state=self.state,
            to_state=to_state,
            version=new_version,
            occurred_at=occurred_at,
            reason=reason,
        )
        return replace(
            self,
            state=to_state,
            version=new_version,
            events=(*self.events, event),
        )

    def cancel(
        self,
        *,
        expected_version: int,
        reason: str,
        now: datetime | None = None,
    ) -> "ToolExecution":
        if not self.cancellable:
            raise OperationNotCancellable(
                f"{self.tool_name} is not safely cancellable in {self.state.value}"
            )
        return self.transition(
            ToolExecutionState.CANCELLED,
            expected_version=expected_version,
            reason=reason,
            now=now,
        )
