from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from local_voice_agent_server.application.execute_tool import ExecuteQueuedTool
from local_voice_agent_server.application.ports import (
    ToolExecutionPortError,
    ToolExecutionReceipt,
)
from local_voice_agent_server.application.tool_planner import ToolPlanner
from local_voice_agent_server.domain.digests import sha256_json
from local_voice_agent_server.domain.tool_execution import ToolExecutionState
from local_voice_agent_server.infrastructure.tool_registry import ToolRegistry


REPO_ROOT = Path(__file__).resolve().parents[3]


def queued_plan():
    registry = ToolRegistry.load(
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT
            / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
    )
    return ToolPlanner(registry).plan(
        session_id=str(uuid4()),
        request_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        tool_name="read_file",
        arguments={"workspace_id": "repo", "relative_path": "README.md"},
        idempotency_key=str(uuid4()),
        precondition_version=0,
    )


class SuccessPort:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.received_state = None

    def execute(self, plan, *, requested_at=None):
        self.received_state = plan.execution.state
        result = {"tool_name": "read_file", "content": "safe"}
        return ToolExecutionReceipt(
            execution_id=plan.execution.execution_id,
            duplicate=self.duplicate,
            result=result,
            result_sha256=sha256_json(result),
            evidence_id=str(uuid4()),
        )


class FailingPort:
    def execute(self, _plan, *, requested_at=None):
        raise ToolExecutionPortError("sanitized failure")


def test_success_transitions_through_running_and_verifying() -> None:
    port = SuccessPort()
    plan = queued_plan()
    outcome = ExecuteQueuedTool(port).execute(
        plan,
        expected_execution_version=plan.execution.version,
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )

    assert outcome.succeeded is True
    assert outcome.error_code is None
    assert outcome.receipt is not None
    assert port.received_state is ToolExecutionState.RUNNING
    assert [event.to_state for event in outcome.execution.events[-3:]] == [
        ToolExecutionState.RUNNING,
        ToolExecutionState.VERIFYING,
        ToolExecutionState.SUCCEEDED,
    ]


def test_verified_duplicate_receipt_succeeds_without_special_failure() -> None:
    port = SuccessPort(duplicate=True)
    plan = queued_plan()
    outcome = ExecuteQueuedTool(port).execute(
        plan,
        expected_execution_version=plan.execution.version,
    )

    assert outcome.succeeded is True
    assert outcome.receipt.duplicate is True
    assert outcome.execution.events[-1].reason == (
        "executor_duplicate_receipt_verified"
    )


def test_port_failure_produces_failed_terminal_outcome() -> None:
    plan = queued_plan()
    outcome = ExecuteQueuedTool(FailingPort()).execute(
        plan,
        expected_execution_version=plan.execution.version,
    )

    assert outcome.execution.state is ToolExecutionState.FAILED
    assert outcome.receipt is None
    assert outcome.error_code == "TOOL_EXECUTOR_REQUEST_FAILED"


def test_receipt_hash_mismatch_fails_after_verifying() -> None:
    class InvalidReceiptPort(SuccessPort):
        def execute(self, plan, *, requested_at=None):
            receipt = super().execute(plan, requested_at=requested_at)
            return replace(receipt, result_sha256="0" * 64)

    plan = queued_plan()
    outcome = ExecuteQueuedTool(InvalidReceiptPort()).execute(
        plan,
        expected_execution_version=plan.execution.version,
    )

    assert outcome.execution.state is ToolExecutionState.FAILED
    assert outcome.error_code == "TOOL_EXECUTOR_RECEIPT_INVALID"
    assert outcome.execution.events[-2].to_state is ToolExecutionState.VERIFYING
