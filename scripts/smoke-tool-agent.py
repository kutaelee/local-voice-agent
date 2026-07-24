#!/usr/bin/env python3
"""Run the tool-aware conversation loop against the real Tool Executor."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps/pc-server/src"))

from local_voice_agent_server.application.execute_tool import ExecuteQueuedTool
from local_voice_agent_server.application.tool_planner import ToolPlanner
from local_voice_agent_server.infrastructure.tool_agent_conversation import (
    ToolAgentConversation,
)
from local_voice_agent_server.infrastructure.tool_executor_client import (
    HttpToolExecutionAdapter,
    ToolExecutorClientSettings,
)
from local_voice_agent_server.infrastructure.tool_registry import ToolRegistry


def main() -> int:
    token = os.environ.get("LVA_TOOL_EXECUTOR_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("LVA_TOOL_EXECUTOR_TOKEN is required")
    executor_url = os.environ.get(
        "LVA_TOOL_EXECUTOR_URL",
        "http://127.0.0.1:46323",
    )
    windows_host_ip = os.environ.get("LVA_WINDOWS_HOST_IP") or None
    registry = ToolRegistry.load(
        definitions_dir=REPO_ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            REPO_ROOT
            / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
        disabled_tools={"restricted_shell"},
    )
    responses: list[dict[str, object]] = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "smoke-model-call",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps(
                            {
                                "workspace_id": "local_voice_agent",
                                "relative_path": "README.md",
                            },
                            separators=(",", ":"),
                        ),
                    },
                }
            ],
        },
        {
            "content": "README를 검증된 도구 결과로 확인했습니다.",
        },
    ]
    conversation = ToolAgentConversation(
        base_url="http://127.0.0.1:46322/v1",
        model="gemma4-12b",
        api_key="smoke-model-key-with-at-least-32-characters",
        session_id=uuid4(),
        request_id=uuid4(),
        registry=registry,
        planner=ToolPlanner(registry),
        executor=ExecuteQueuedTool(
            HttpToolExecutionAdapter(
                ToolExecutorClientSettings(
                    base_url=executor_url,
                    ipc_token=token,
                    allowed_wsl_gateway=windows_host_ip,
                )
            )
        ),
        transport=lambda _: responses.pop(0),
    )
    reply = asyncio.run(
        conversation.respond("README를 읽어줘.", language="ko")
    )
    completed = next(
        event for event in reply.events if event.type == "tool.completed"
    )
    result = completed.payload["result"]
    evidence_ids = completed.payload["evidence_ids"]
    if (
        reply.text != "README를 검증된 도구 결과로 확인했습니다."
        or not isinstance(result, dict)
        or result.get("status") != "succeeded"
        or len(evidence_ids) != 1
    ):
        raise RuntimeError("tool-aware conversation smoke failed")
    print(
        json.dumps(
            {
                "status": "passed",
                "tool_name": result["tool_name"],
                "event_types": [event.type for event in reply.events],
                "evidence_id": evidence_ids[0],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
