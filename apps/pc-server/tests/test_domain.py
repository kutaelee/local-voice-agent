from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from local_voice_agent_server.domain.approval import (
    ApprovalRequest,
    ApprovalState,
)
from local_voice_agent_server.domain.digests import sha256_json
from local_voice_agent_server.domain.errors import (
    ApprovalBindingError,
    ApprovalExpired,
    InvalidTransition,
    OperationNotCancellable,
    OptimisticLockError,
)
from local_voice_agent_server.domain.policy import (
    PolicyAction,
    RiskLevel,
    evaluate_policy,
)
from local_voice_agent_server.domain.tool_execution import (
    ToolExecution,
    ToolExecutionState,
)
from local_voice_agent_server.protocol.envelope import EventEnvelope


def execution(*, cancellable: bool = True) -> ToolExecution:
    return ToolExecution(
        execution_id=str(uuid4()),
        session_id=str(uuid4()),
        request_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        tool_name="inspect_gpu",
        idempotency_key=str(uuid4()),
        normalized_arguments_sha256=sha256_json({}),
        cancellable=cancellable,
    )


def test_canonical_digest_is_order_independent() -> None:
    assert sha256_json({"b": 2, "a": "한글"}) == sha256_json(
        {"a": "한글", "b": 2}
    )


def test_tool_execution_happy_path_records_versioned_events() -> None:
    item = execution()
    for target in (
        ToolExecutionState.QUEUED,
        ToolExecutionState.RUNNING,
        ToolExecutionState.VERIFYING,
        ToolExecutionState.SUCCEEDED,
    ):
        item = item.transition(
            target,
            expected_version=item.version,
            reason="test",
        )
    assert item.state is ToolExecutionState.SUCCEEDED
    assert item.version == 4
    assert tuple(event.version for event in item.events) == (1, 2, 3, 4)


def test_invalid_tool_transition_is_rejected() -> None:
    with pytest.raises(InvalidTransition):
        execution().transition(
            ToolExecutionState.SUCCEEDED,
            expected_version=0,
            reason="skip verification",
        )


def test_stale_tool_version_is_rejected() -> None:
    item = execution().transition(
        ToolExecutionState.QUEUED,
        expected_version=0,
        reason="ready",
    )
    with pytest.raises(OptimisticLockError):
        item.transition(
            ToolExecutionState.RUNNING,
            expected_version=0,
            reason="stale writer",
        )


def test_non_cancellable_operation_is_rejected() -> None:
    with pytest.raises(OperationNotCancellable):
        execution(cancellable=False).cancel(
            expected_version=0,
            reason="barge-in",
        )


def approval(now: datetime) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        normalized_arguments_sha256=sha256_json({"path": "src/app.py"}),
        precondition_version=3,
        created_at=now,
        expires_at=now + timedelta(minutes=2),
    )


def test_approval_is_bound_to_exact_arguments_and_precondition() -> None:
    now = datetime.now(timezone.utc)
    request = approval(now)
    with pytest.raises(ApprovalBindingError):
        request.decide(
            approved=True,
            normalized_arguments_sha256=sha256_json({"path": "other.py"}),
            precondition_version=3,
            expected_version=0,
            now=now + timedelta(seconds=1),
        )


def test_approval_cannot_be_used_after_expiry() -> None:
    now = datetime.now(timezone.utc)
    request = approval(now)
    with pytest.raises(ApprovalExpired):
        request.decide(
            approved=True,
            normalized_arguments_sha256=request.normalized_arguments_sha256,
            precondition_version=3,
            expected_version=0,
            now=request.expires_at,
        )


def test_approval_decision_is_single_use() -> None:
    now = datetime.now(timezone.utc)
    request = approval(now)
    decided = request.decide(
        approved=False,
        normalized_arguments_sha256=request.normalized_arguments_sha256,
        precondition_version=3,
        expected_version=0,
        now=now + timedelta(seconds=1),
    )
    assert decided.state is ApprovalState.DENIED
    with pytest.raises(InvalidTransition):
        decided.decide(
            approved=True,
            normalized_arguments_sha256=request.normalized_arguments_sha256,
            precondition_version=3,
            expected_version=1,
            now=now + timedelta(seconds=2),
        )


def test_stale_approval_version_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    request = approval(now)
    with pytest.raises(OptimisticLockError):
        request.decide(
            approved=True,
            normalized_arguments_sha256=request.normalized_arguments_sha256,
            precondition_version=3,
            expected_version=1,
            now=now + timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    ("risk", "grant", "expected"),
    [
        (RiskLevel.OBSERVE, False, PolicyAction.ALLOW),
        (RiskLevel.REVERSIBLE_LOCAL, False, PolicyAction.REQUIRE_APPROVAL),
        (RiskLevel.REVERSIBLE_LOCAL, True, PolicyAction.ALLOW),
        (RiskLevel.IMPACTING, True, PolicyAction.REQUIRE_APPROVAL),
        (RiskLevel.HIGH_RISK, True, PolicyAction.DENY),
    ],
)
def test_policy_risk_levels(
    risk: RiskLevel,
    grant: bool,
    expected: PolicyAction,
) -> None:
    decision = evaluate_policy(
        tool_name="test_tool",
        risk_level=risk,
        tool_definition_sha256="a" * 64,
        normalized_arguments_sha256="b" * 64,
        session_grant_valid=grant,
    )
    assert decision.action is expected


def test_disabled_tool_fails_closed() -> None:
    decision = evaluate_policy(
        tool_name="restricted_shell",
        risk_level=RiskLevel.OBSERVE,
        tool_definition_sha256="a" * 64,
        normalized_arguments_sha256="b" * 64,
        tool_enabled=False,
    )
    assert decision.action is PolicyAction.DENY
    assert decision.reason_codes == ("TOOL_DISABLED",)


def test_protocol_envelope_rejects_negative_sequence() -> None:
    with pytest.raises(ValueError):
        EventEnvelope.create(
            type="assistant.state",
            session_id=uuid4(),
            request_id=uuid4(),
            sequence=-1,
            payload={},
        )


def test_protocol_envelope_serializes_uuid_and_utc_timestamp() -> None:
    envelope = EventEnvelope.create(
        type="assistant.state",
        session_id=uuid4(),
        request_id=uuid4(),
        sequence=0,
        payload={"state": "thinking"},
    )
    value = envelope.to_dict()
    assert value["schema_version"] == "1.0"
    assert value["timestamp"].endswith("+00:00")
