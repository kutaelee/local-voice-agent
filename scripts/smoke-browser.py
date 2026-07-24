#!/usr/bin/env python3
"""Exercise approved loopback browser computer-use through the real executor."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Thread
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
        raise RuntimeError("expected an approval-bound browser execution")
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

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            content = b"""<!doctype html><html><head>
            <title>Local Voice Agent browser smoke</title></head><body>
            <label>Name <input aria-label="Name"></label>
            <button type="button"
              onclick="document.querySelector('output').textContent='clicked'">
              Update
            </button><output>ready</output></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
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

    browser_session_id: str | None = None
    try:
        launched = run(
            "browser_launch",
            {
                "browser_profile_id": "local-loopback",
                "headless": True,
            },
        )
        browser_session_id = str(launched["browser_session_id"])
        run(
            "browser_navigate",
            {
                "browser_session_id": browser_session_id,
                "url": f"http://127.0.0.1:{server.server_port}/",
            },
        )
        state = run(
            "browser_get_page_state",
            {
                "browser_session_id": browser_session_id,
                "include_dom": True,
                "include_accessibility_tree": True,
                "max_bytes": 262_144,
            },
        )
        input_ref = next(
            item["element_ref"]
            for item in state["elements"]
            if item["tag"] == "input"
        )
        run(
            "browser_type",
            {
                "browser_session_id": browser_session_id,
                "element_ref": input_ref,
                "page_state_fingerprint": state["page_state_fingerprint"],
                "text": "approved local smoke",
                "submit": False,
            },
        )
        refreshed = run(
            "browser_get_page_state",
            {"browser_session_id": browser_session_id},
        )
        button_ref = next(
            item["element_ref"]
            for item in refreshed["elements"]
            if item["tag"] == "button"
        )
        run(
            "browser_click",
            {
                "browser_session_id": browser_session_id,
                "element_ref": button_ref,
                "page_state_fingerprint": (
                    refreshed["page_state_fingerprint"]
                ),
                "external_submission": False,
            },
        )
        screenshot = run(
            "browser_screenshot",
            {
                "browser_session_id": browser_session_id,
                "full_page": False,
            },
        )
        run(
            "browser_close",
            {"browser_session_id": browser_session_id},
        )
        browser_session_id = None
        print(
            json.dumps(
                {
                    "status": "passed",
                    "title": state["title"],
                    "network_policy": launched["network_policy"],
                    "screenshot_artifact_id": screenshot["artifact_id"],
                    "screenshot_sha256": screenshot["sha256"],
                    "screenshot_size_bytes": screenshot["size_bytes"],
                    "evidence_ids": evidence_ids,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        if browser_session_id is not None:
            try:
                run(
                    "browser_close",
                    {"browser_session_id": browser_session_id},
                )
            except Exception:
                pass
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
