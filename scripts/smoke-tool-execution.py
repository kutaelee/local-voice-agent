"""Live Level 0 planner-to-executor smoke without persisting result content."""

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
    plan = ToolPlanner(registry).plan(
        session_id=str(uuid4()),
        request_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        tool_name="read_file",
        arguments={
            "workspace_id": "local_voice_agent",
            "relative_path": "README.md",
        },
        idempotency_key=str(uuid4()),
        precondition_version=0,
    )
    adapter = HttpToolExecutionAdapter(
        ToolExecutorClientSettings(
            base_url="http://127.0.0.1:8790",
            ipc_token=token,
        )
    )
    outcome = ExecuteQueuedTool(adapter).execute(
        plan,
        expected_execution_version=plan.execution.version,
    )
    if not outcome.succeeded or outcome.receipt is None:
        raise RuntimeError(f"execution failed: {outcome.error_code}")
    content = outcome.receipt.result["result"]["content"]
    if not content.startswith("# Local Voice Agent"):
        raise RuntimeError("unexpected README content")

    print(
        json.dumps(
            {
                "status": outcome.execution.state.value,
                "tool": plan.tool_name,
                "workspace_id": "local_voice_agent",
                "duplicate": outcome.receipt.duplicate,
                "result_sha256": outcome.receipt.result_sha256,
                "evidence_id": outcome.receipt.evidence_id,
                "persisted_result_content": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
