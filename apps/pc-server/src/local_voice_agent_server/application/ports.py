"""Application ports for isolated side-effecting infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from .tool_planner import ToolPlan


@dataclass(frozen=True, slots=True)
class ToolExecutionReceipt:
    execution_id: str
    duplicate: bool
    result: Mapping[str, Any]
    result_sha256: str
    evidence_id: str


class ToolExecutionPort(Protocol):
    def execute(
        self,
        plan: ToolPlan,
        *,
        requested_at: datetime | None = None,
    ) -> ToolExecutionReceipt:
        """Execute one policy-bound, already queued Level 0 plan."""
