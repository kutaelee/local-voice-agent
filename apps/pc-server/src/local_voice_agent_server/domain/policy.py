"""Pure risk policy decisions; no tool execution occurs here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, IntEnum


class RiskLevel(IntEnum):
    OBSERVE = 0
    REVERSIBLE_LOCAL = 1
    IMPACTING = 2
    HIGH_RISK = 3


class PolicyAction(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    action: PolicyAction
    risk_level: RiskLevel
    tool_name: str
    tool_definition_sha256: str
    normalized_arguments_sha256: str
    reason_codes: tuple[str, ...]
    evaluated_at: datetime


def evaluate_policy(
    *,
    tool_name: str,
    risk_level: RiskLevel,
    tool_definition_sha256: str,
    normalized_arguments_sha256: str,
    session_grant_valid: bool = False,
    tool_enabled: bool = True,
) -> PolicyDecision:
    """Apply the fail-closed baseline permission policy."""

    if not tool_enabled:
        action = PolicyAction.DENY
        reasons = ("TOOL_DISABLED",)
    elif risk_level is RiskLevel.HIGH_RISK:
        action = PolicyAction.DENY
        reasons = ("LEVEL_3_DEFAULT_DENY",)
    elif risk_level is RiskLevel.IMPACTING:
        action = PolicyAction.REQUIRE_APPROVAL
        reasons = ("EXACT_APPROVAL_REQUIRED",)
    elif risk_level is RiskLevel.REVERSIBLE_LOCAL and not session_grant_valid:
        action = PolicyAction.REQUIRE_APPROVAL
        reasons = ("EXACT_APPROVAL_REQUIRED",)
    elif risk_level is RiskLevel.REVERSIBLE_LOCAL:
        action = PolicyAction.ALLOW
        reasons = ("SESSION_GRANT_VALID", "WITHIN_SCOPE")
    else:
        action = PolicyAction.ALLOW
        reasons = ("WITHIN_SCOPE",)

    return PolicyDecision(
        action=action,
        risk_level=risk_level,
        tool_name=tool_name,
        tool_definition_sha256=tool_definition_sha256,
        normalized_arguments_sha256=normalized_arguments_sha256,
        reason_codes=reasons,
        evaluated_at=datetime.now(timezone.utc),
    )
