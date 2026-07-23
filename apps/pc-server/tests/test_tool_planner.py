from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from local_voice_agent_server.application.tool_planner import ToolPlanner
from local_voice_agent_server.domain.approval import ApprovalRequest
from local_voice_agent_server.domain.errors import (
    ApprovalBindingError,
    InvalidTransition,
)
from local_voice_agent_server.domain.policy import PolicyAction
from local_voice_agent_server.domain.tool_execution import ToolExecutionState
from local_voice_agent_server.infrastructure.tool_registry import ToolRegistry


REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def planner() -> ToolPlanner:
    registry = ToolRegistry.load(
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT
            / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
        disabled_tools={"restricted_shell"},
    )
    return ToolPlanner(registry)


def identifiers() -> dict[str, str]:
    return {
        "session_id": str(uuid4()),
        "request_id": str(uuid4()),
        "tool_call_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
    }


def test_level_zero_plan_is_queued_without_approval(
    planner: ToolPlanner,
) -> None:
    plan = planner.plan(
        **identifiers(),
        tool_name="read_file",
        arguments={"workspace_id": "repo", "relative_path": "README.md"},
        precondition_version=0,
    )
    assert plan.policy.action is PolicyAction.ALLOW
    assert plan.execution is not None
    assert plan.execution.state is ToolExecutionState.QUEUED
    assert plan.approval is None


def test_level_one_plan_waits_for_exact_approval(
    planner: ToolPlanner,
) -> None:
    plan = planner.plan(
        **identifiers(),
        tool_name="write_file",
        arguments={
            "workspace_id": "repo",
            "relative_path": "notes.txt",
            "expected_sha256": None,
            "content": "draft",
        },
        precondition_version=4,
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    assert plan.policy.action is PolicyAction.REQUIRE_APPROVAL
    assert plan.execution is not None
    assert plan.execution.state is ToolExecutionState.WAITING_APPROVAL
    assert plan.approval is not None
    assert (
        plan.approval.normalized_arguments_sha256
        == plan.execution.normalized_arguments_sha256
    )
    assert plan.approval.precondition_version == 4


def test_level_one_session_grant_can_queue(
    planner: ToolPlanner,
) -> None:
    plan = planner.plan(
        **identifiers(),
        tool_name="write_file",
        arguments={
            "workspace_id": "repo",
            "relative_path": "notes.txt",
            "expected_sha256": None,
            "content": "draft",
        },
        precondition_version=4,
        session_grant_valid=True,
    )
    assert plan.policy.action is PolicyAction.ALLOW
    assert plan.execution is not None
    assert plan.execution.state is ToolExecutionState.QUEUED


def test_level_two_always_requires_exact_approval(
    planner: ToolPlanner,
) -> None:
    plan = planner.plan(
        **identifiers(),
        tool_name="delete_file",
        arguments={
            "workspace_id": "repo",
            "relative_path": "old.txt",
            "expected_sha256": "a" * 64,
        },
        precondition_version=7,
        session_grant_valid=True,
    )
    assert plan.policy.action is PolicyAction.REQUIRE_APPROVAL
    assert plan.execution is not None
    assert plan.execution.state is ToolExecutionState.WAITING_APPROVAL


def test_level_three_creates_no_execution(
    planner: ToolPlanner,
) -> None:
    plan = planner.plan(
        **identifiers(),
        tool_name="git_reset",
        arguments={
            "workspace_id": "repo",
            "expected_head": "a" * 40,
            "target_commit": "b" * 40,
            "mode": "hard",
        },
        precondition_version=1,
    )
    assert plan.policy.action is PolicyAction.DENY
    assert plan.execution is None
    assert plan.approval is None


def test_disabled_tool_creates_no_execution(
    planner: ToolPlanner,
) -> None:
    plan = planner.plan(
        **identifiers(),
        tool_name="restricted_shell",
        arguments={"untrusted": "ignored because the tool is disabled"},
        precondition_version=0,
    )
    assert plan.policy.action is PolicyAction.DENY
    assert plan.policy.reason_codes == ("TOOL_DISABLED",)
    assert plan.execution is None


def waiting_plan(planner: ToolPlanner):
    return planner.plan(
        **identifiers(),
        tool_name="write_file",
        arguments={
            "workspace_id": "repo",
            "relative_path": "notes.txt",
            "expected_sha256": None,
            "content": "draft",
        },
        precondition_version=4,
    )


def test_exact_approved_plan_can_be_queued(planner: ToolPlanner) -> None:
    plan = waiting_plan(planner)
    assert plan.approval is not None
    decided = plan.approval.decide(
        approved=True,
        normalized_arguments_sha256=plan.approval.normalized_arguments_sha256,
        precondition_version=plan.approval.precondition_version,
        expected_version=0,
    )
    queued = planner.queue_approved(
        plan,
        decided_approval=decided,
        expected_execution_version=1,
    )
    assert queued.execution is not None
    assert queued.execution.state is ToolExecutionState.QUEUED
    assert queued.execution.version == 2


def test_denied_approval_cannot_queue(planner: ToolPlanner) -> None:
    plan = waiting_plan(planner)
    assert plan.approval is not None
    denied = plan.approval.decide(
        approved=False,
        normalized_arguments_sha256=plan.approval.normalized_arguments_sha256,
        precondition_version=plan.approval.precondition_version,
        expected_version=0,
    )
    with pytest.raises(InvalidTransition):
        planner.queue_approved(
            plan,
            decided_approval=denied,
            expected_execution_version=1,
        )


def test_mismatched_approved_record_cannot_queue(
    planner: ToolPlanner,
) -> None:
    plan = waiting_plan(planner)
    assert plan.approval is not None
    other = ApprovalRequest(
        approval_id=str(uuid4()),
        tool_call_id=plan.approval.tool_call_id,
        normalized_arguments_sha256=plan.approval.normalized_arguments_sha256,
        precondition_version=plan.approval.precondition_version,
        created_at=plan.approval.created_at,
        expires_at=plan.approval.expires_at,
    ).decide(
        approved=True,
        normalized_arguments_sha256=plan.approval.normalized_arguments_sha256,
        precondition_version=plan.approval.precondition_version,
        expected_version=0,
    )
    with pytest.raises(ApprovalBindingError):
        planner.queue_approved(
            plan,
            decided_approval=other,
            expected_execution_version=1,
        )
