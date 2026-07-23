"""Approval aggregate bound to exact normalized arguments and preconditions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from .errors import (
    ApprovalBindingError,
    ApprovalExpired,
    InvalidTransition,
    OptimisticLockError,
)


class ApprovalState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    approval_id: str
    tool_call_id: str
    normalized_arguments_sha256: str
    precondition_version: int
    created_at: datetime
    expires_at: datetime
    state: ApprovalState = ApprovalState.PENDING
    version: int = 0
    decided_at: datetime | None = None

    def decide(
        self,
        *,
        approved: bool,
        normalized_arguments_sha256: str,
        precondition_version: int,
        expected_version: int,
        now: datetime | None = None,
    ) -> "ApprovalRequest":
        observed_at = now or datetime.now(timezone.utc)
        if expected_version != self.version:
            raise OptimisticLockError(
                f"expected version {expected_version}, current {self.version}"
            )
        if self.state is not ApprovalState.PENDING:
            raise InvalidTransition(f"approval is already {self.state.value}")
        if observed_at >= self.expires_at:
            raise ApprovalExpired("approval has expired")
        if (
            normalized_arguments_sha256 != self.normalized_arguments_sha256
            or precondition_version != self.precondition_version
        ):
            raise ApprovalBindingError(
                "approval does not match arguments or precondition version"
            )
        return replace(
            self,
            state=ApprovalState.APPROVED if approved else ApprovalState.DENIED,
            version=self.version + 1,
            decided_at=observed_at,
        )

    def expire(self, *, now: datetime | None = None) -> "ApprovalRequest":
        observed_at = now or datetime.now(timezone.utc)
        if self.state is not ApprovalState.PENDING:
            return self
        if observed_at < self.expires_at:
            return self
        return replace(
            self,
            state=ApprovalState.EXPIRED,
            version=self.version + 1,
            decided_at=observed_at,
        )
