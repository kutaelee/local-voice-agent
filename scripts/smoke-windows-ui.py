#!/usr/bin/env python3
"""Exercise observed Notepad UI through the real approved executor boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "pc-server" / "src"))

from local_voice_agent_server.application.execute_tool import ExecuteQueuedTool
from local_voice_agent_server.application.tool_planner import ToolPlan, ToolPlanner
from local_voice_agent_server.infrastructure.tool_executor_client import (
    HttpToolExecutionAdapter,
    ToolExecutorClientSettings,
)
from local_voice_agent_server.infrastructure.tool_registry import ToolRegistry


def approve(planner: ToolPlanner, plan: ToolPlan) -> ToolPlan:
    if plan.approval is None or plan.execution is None:
        raise RuntimeError("expected an approval-bound UI execution")
    approved = plan.approval.decide(
        approved=True,
        normalized_arguments_sha256=plan.approval.normalized_arguments_sha256,
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


def main() -> int:
    token = os.environ.get("LVA_TOOL_EXECUTOR_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("LVA_TOOL_EXECUTOR_TOKEN is required")
    expected_filename = os.environ.get("LVA_UI_SMOKE_FILENAME", "")
    if not expected_filename.startswith(".lva-ui-smoke-"):
        raise RuntimeError("LVA_UI_SMOKE_FILENAME must name an isolated smoke file")
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
            base_url="http://127.0.0.1:46323",
            ipc_token=token,
        )
    )
    use_case = ExecuteQueuedTool(adapter)
    session_id = str(uuid4())
    request_id = str(uuid4())
    evidence_ids: list[str] = []

    def run(tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        plan = planner.plan(
            session_id=session_id,
            request_id=request_id,
            tool_call_id=str(uuid4()),
            tool_name=tool_name,
            arguments=arguments,
            idempotency_key=str(uuid4()),
            precondition_version=0,
        )
        if plan.approval is not None:
            plan = approve(planner, plan)
        if plan.execution is None:
            raise RuntimeError(f"{tool_name} did not produce an execution")
        outcome = use_case.execute(
            plan,
            expected_execution_version=plan.execution.version,
        )
        if not outcome.succeeded or outcome.receipt is None:
            raise RuntimeError(f"{tool_name} failed: {outcome.error_code}")
        evidence_ids.append(outcome.receipt.evidence_id)
        return dict(outcome.receipt.result["result"])

    listed = run("ui_list_windows", {"limit": 100})
    candidates = [
        item
        for item in listed["windows"]
        if str(item.get("process_name", "")).casefold() == "notepad.exe"
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected exactly one visible Notepad window, found {len(candidates)}"
        )
    window = candidates[0]
    if expected_filename.casefold() not in str(window["title"]).casefold():
        raise RuntimeError("Notepad did not open the isolated smoke target")
    window_ref = str(window["window_ref"])
    run(
        "ui_focus_window",
        {
            "window_ref": window_ref,
            "window_state_fingerprint": window["window_state_fingerprint"],
        },
    )
    tree = run(
        "ui_get_accessibility_tree",
        {
            "window_ref": window_ref,
            "max_depth": 10,
            "max_nodes": 2_000,
        },
    )
    editable = next(
        item
        for item in tree["nodes"]
        if item["control_type"] in {"Edit", "Document"}
    )
    typed = run(
        "ui_type_text",
        {
            "window_ref": window_ref,
            "element_ref": editable["element_ref"],
            "ui_state_fingerprint": tree["ui_state_fingerprint"],
            "text": "Local Voice Agent approved UI Automation smoke.",
            "submit": False,
        },
    )
    captured = run(
        "ui_capture_screen",
        {"window_ref": window_ref, "include_cursor": False},
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "window_title": window["title"],
                "process_id": window["process_id"],
                "typed_characters": typed["typed_characters"],
                "screenshot_artifact_id": captured["artifact_id"],
                "screenshot_sha256": captured["sha256"],
                "evidence_ids": evidence_ids,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
