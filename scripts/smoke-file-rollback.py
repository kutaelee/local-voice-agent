#!/usr/bin/env python3
"""Live approved create-and-rollback smoke through the isolated executor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "pc-server" / "src"))

from local_voice_agent_server.application.execute_tool import (  # noqa: E402
    ExecuteQueuedTool,
)
from local_voice_agent_server.application.tool_planner import (  # noqa: E402
    ToolPlan,
    ToolPlanner,
)
from local_voice_agent_server.infrastructure.tool_executor_client import (  # noqa: E402
    HttpToolExecutionAdapter,
    ToolExecutorClientSettings,
)
from local_voice_agent_server.infrastructure.tool_registry import (  # noqa: E402
    ToolRegistry,
)


def approve(planner: ToolPlanner, plan: ToolPlan) -> ToolPlan:
    if plan.approval is None or plan.execution is None:
        raise RuntimeError("expected an approval-bound execution")
    approved = plan.approval.decide(
        approved=True,
        normalized_arguments_sha256=(
            plan.approval.normalized_arguments_sha256
        ),
        precondition_version=plan.approval.precondition_version,
        expected_version=plan.approval.version,
        now=plan.approval.created_at,
    )
    return planner.queue_approved(
        plan,
        decided_approval=approved,
        expected_execution_version=plan.execution.version,
        now=plan.approval.created_at,
    )


def execute(adapter: HttpToolExecutionAdapter, plan: ToolPlan) -> dict:
    if plan.execution is None:
        raise RuntimeError("plan has no execution")
    outcome = ExecuteQueuedTool(adapter).execute(
        plan,
        expected_execution_version=plan.execution.version,
    )
    if not outcome.succeeded or outcome.receipt is None:
        raise RuntimeError(f"execution failed: {outcome.error_code}")
    return {
        "evidence_id": outcome.receipt.evidence_id,
        "result": outcome.receipt.result["result"],
    }


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
    session_id = str(uuid4())
    request_id = str(uuid4())
    relative_path = f"tests/.lva-rollback-smoke-{uuid4()}.txt"
    create = planner.plan(
        session_id=session_id,
        request_id=request_id,
        tool_call_id=str(uuid4()),
        tool_name="write_file",
        arguments={
            "workspace_id": "local_voice_agent",
            "relative_path": relative_path,
            "expected_sha256": None,
            "content": "temporary approved rollback smoke\n",
        },
        idempotency_key=str(uuid4()),
        precondition_version=0,
    )
    created = execute(adapter, approve(planner, create))
    target = REPO_ROOT / relative_path
    if not target.is_file():
        raise RuntimeError("executor did not create the smoke file")

    rollback = planner.plan(
        session_id=session_id,
        request_id=request_id,
        tool_call_id=str(uuid4()),
        tool_name="rollback_file_change",
        arguments={
            "workspace_id": "local_voice_agent",
            "relative_path": relative_path,
            "backup_id": created["result"]["backup_id"],
            "expected_current_sha256": created["result"]["after_sha256"],
        },
        idempotency_key=str(uuid4()),
        precondition_version=1,
    )
    rolled_back = execute(adapter, approve(planner, rollback))
    if target.exists():
        raise RuntimeError("rollback did not remove the created smoke file")

    print(
        json.dumps(
            {
                "status": "passed",
                "relative_path": relative_path,
                "create_evidence_id": created["evidence_id"],
                "rollback_evidence_id": rolled_back["evidence_id"],
                "backup_id": created["result"]["backup_id"],
                "after_sha256": created["result"]["after_sha256"],
                "final_exists": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
