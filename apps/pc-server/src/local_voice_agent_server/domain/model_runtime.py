"""Model runtime aggregate with explicit, versioned lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from .errors import InvalidTransition, OptimisticLockError


class ModelRuntimeState(str, Enum):
    UNLOADED = "UNLOADED"
    LOADING = "LOADING"
    HEALTH_CHECKING = "HEALTH_CHECKING"
    READY = "READY"
    DRAINING = "DRAINING"
    UNLOADING = "UNLOADING"
    FAILED = "FAILED"


_ALLOWED_TRANSITIONS: dict[ModelRuntimeState, frozenset[ModelRuntimeState]] = {
    ModelRuntimeState.UNLOADED: frozenset({ModelRuntimeState.LOADING}),
    ModelRuntimeState.LOADING: frozenset(
        {ModelRuntimeState.HEALTH_CHECKING, ModelRuntimeState.FAILED}
    ),
    ModelRuntimeState.HEALTH_CHECKING: frozenset(
        {ModelRuntimeState.READY, ModelRuntimeState.FAILED}
    ),
    ModelRuntimeState.READY: frozenset(
        {ModelRuntimeState.DRAINING, ModelRuntimeState.FAILED}
    ),
    ModelRuntimeState.DRAINING: frozenset(
        {ModelRuntimeState.UNLOADING, ModelRuntimeState.FAILED}
    ),
    ModelRuntimeState.UNLOADING: frozenset(
        {ModelRuntimeState.UNLOADED, ModelRuntimeState.FAILED}
    ),
    ModelRuntimeState.FAILED: frozenset({ModelRuntimeState.UNLOADING}),
}


@dataclass(frozen=True, slots=True)
class ModelRuntimeEvent:
    from_state: ModelRuntimeState
    to_state: ModelRuntimeState
    version: int
    occurred_at: datetime
    reason: str
    failure_code: str | None = None
    evidence_path: str | None = None


@dataclass(frozen=True, slots=True)
class ModelRuntime:
    model_id: str
    state: ModelRuntimeState = ModelRuntimeState.UNLOADED
    version: int = 0
    events: tuple[ModelRuntimeEvent, ...] = ()

    @property
    def accepts_new_requests(self) -> bool:
        return self.state is ModelRuntimeState.READY

    def transition(
        self,
        to_state: ModelRuntimeState,
        *,
        expected_version: int,
        reason: str,
        now: datetime | None = None,
        failure_code: str | None = None,
        evidence_path: str | None = None,
    ) -> "ModelRuntime":
        if expected_version != self.version:
            raise OptimisticLockError(
                f"expected version {expected_version}, current {self.version}"
            )
        if to_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransition(
                f"{self.state.value} cannot transition to {to_state.value}"
            )
        if not reason.strip():
            raise ValueError("transition reason is required")
        if to_state is ModelRuntimeState.FAILED:
            if not failure_code or not evidence_path:
                raise ValueError(
                    "FAILED transition requires failure_code and evidence_path"
                )
        elif failure_code is not None or evidence_path is not None:
            raise ValueError("failure metadata is valid only for FAILED")

        occurred_at = now or datetime.now(timezone.utc)
        new_version = self.version + 1
        event = ModelRuntimeEvent(
            from_state=self.state,
            to_state=to_state,
            version=new_version,
            occurred_at=occurred_at,
            reason=reason,
            failure_code=failure_code,
            evidence_path=evidence_path,
        )
        return replace(
            self,
            state=to_state,
            version=new_version,
            events=(*self.events, event),
        )
