"""Exercise the approval-bound registered test profile over the executor API."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps/pc-server/src"))

from local_voice_agent_server.application.execute_tool import ExecuteQueuedTool
from local_voice_agent_server.application.tool_planner import ToolPlanner
from local_voice_agent_server.infrastructure.tool_executor_client import (
    HttpToolExecutionAdapter,
    ToolExecutorClientSettings,
)
from local_voice_agent_server.infrastructure.tool_registry import ToolRegistry


def execute(
    planner: ToolPlanner,
    adapter: HttpToolExecutionAdapter,
    *,
    tool_name: str,
    arguments: dict[str, object],
    approval: bool,
) -> dict[str, object]:
    plan = planner.plan(
        session_id=str(uuid4()),
        request_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        tool_name=tool_name,
        arguments=arguments,
        idempotency_key=str(uuid4()),
        precondition_version=0,
    )
    if plan.execution is None:
        raise RuntimeError(f"{tool_name} unexpectedly denied")
    if approval:
        if plan.approval is None:
            raise RuntimeError(f"{tool_name} did not require approval")
        decided = plan.approval.decide(
            approved=True,
            normalized_arguments_sha256=plan.execution.normalized_arguments_sha256,
            precondition_version=plan.approval.precondition_version,
            expected_version=plan.approval.version,
        )
        plan = planner.queue_approved(
            plan,
            decided_approval=decided,
            expected_execution_version=plan.execution.version,
        )
    outcome = ExecuteQueuedTool(adapter).execute(
        plan,
        expected_execution_version=plan.execution.version,
    )
    if not outcome.succeeded or outcome.receipt is None:
        raise RuntimeError(f"{tool_name} execution failed: {outcome.error_code}")
    return dict(outcome.receipt.result)


def main() -> int:
    token = os.environ.get("LVA_TOOL_EXECUTOR_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("LVA_TOOL_EXECUTOR_TOKEN is required")
    registry = ToolRegistry.load(
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT
            / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
    )
    planner = ToolPlanner(registry)
    adapter = HttpToolExecutionAdapter(
        ToolExecutorClientSettings(
            base_url="http://127.0.0.1:8790",
            ipc_token=token,
        )
    )
    test_result = execute(
        planner,
        adapter,
        tool_name="run_tests",
        arguments={
            "workspace_id": "local_voice_agent",
            "profile_id": "repository-validation",
            "timeout_seconds": 15,
        },
        approval=True,
    )
    inner = test_result["result"]
    if not isinstance(inner, dict) or not inner.get("succeeded"):
        raise RuntimeError("registered validation profile did not succeed")
    evidence_id = inner.get("evidence_id")
    if not isinstance(evidence_id, str):
        raise RuntimeError("registered validation profile did not return evidence")
    log_result = execute(
        planner,
        adapter,
        tool_name="inspect_test_log",
        arguments={
            "workspace_id": "local_voice_agent",
            "evidence_id": evidence_id,
        },
        approval=False,
    )
    log = log_result["result"]
    if not isinstance(log, dict) or "repository_validation_passed" not in str(
        log.get("text", "")
    ):
        raise RuntimeError("registered test evidence did not contain validation result")
    print(
        json.dumps(
            {
                "status": "approved_registered_test_api_smoke_passed",
                "test_evidence_id": evidence_id,
                "test_result_sha256": test_result.get("result_sha256"),
                "log_result_sha256": log_result.get("result_sha256"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
