from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from local_voice_agent_server.application.execute_tool import ExecuteQueuedTool
from local_voice_agent_server.application.ports import ToolExecutionReceipt
from local_voice_agent_server.application.tool_planner import ToolPlanner
from local_voice_agent_server.domain.digests import sha256_json
from local_voice_agent_server.infrastructure.tool_agent_conversation import (
    ToolAgentConversation,
    ToolAgentError,
)
from local_voice_agent_server.infrastructure.tool_registry import ToolRegistry


ROOT = Path(__file__).resolve().parents[3]
API_KEY = "test-only-model-api-key-with-32-characters"


class FakePort:
    def __init__(self) -> None:
        self.plans = []

    def execute(self, plan, **_: object) -> ToolExecutionReceipt:
        self.plans.append(plan)
        result = {
            "tool_name": plan.tool_name,
            "status": "succeeded",
            "result": {"observed": True},
        }
        return ToolExecutionReceipt(
            execution_id=plan.execution.execution_id,
            duplicate=False,
            result=result,
            result_sha256=sha256_json(result),
            evidence_id=str(uuid4()),
        )


def registry() -> ToolRegistry:
    return ToolRegistry.load(
        definitions_dir=ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            ROOT / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
        disabled_tools={"restricted_shell"},
    )


def agent(
    messages: list[dict[str, object]],
) -> tuple[ToolAgentConversation, FakePort]:
    tool_registry = registry()
    port = FakePort()

    def transport(_: dict[str, object]) -> dict[str, object]:
        return messages.pop(0)

    return (
        ToolAgentConversation(
            base_url="http://127.0.0.1:8766/v1",
            model="gemma4-12b",
            api_key=API_KEY,
            session_id=uuid4(),
            request_id=uuid4(),
            registry=tool_registry,
            planner=ToolPlanner(tool_registry),
            executor=ExecuteQueuedTool(port),
            transport=transport,
        ),
        port,
    )


def tool_message(
    name: str,
    arguments: str,
) -> dict[str, object]:
    return {
        "content": None,
        "tool_calls": [
            {
                "id": "model-call-1",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        ],
    }


def test_level_zero_tool_executes_and_returns_verified_result() -> None:
    conversation, port = agent(
        [
            tool_message(
                "read_file",
                '{"workspace_id":"local_voice_agent","relative_path":"README.md"}',
            ),
            {"content": "확인 결과 파일을 읽었습니다."},
        ]
    )
    reply = asyncio.run(conversation.respond("README 읽어줘", language="ko"))
    assert reply.text == "확인 결과 파일을 읽었습니다."
    assert [event.type for event in reply.events] == [
        "assistant.state",
        "tool.plan",
        "assistant.state",
        "tool.started",
        "assistant.state",
        "tool.completed",
    ]
    assert len(port.plans) == 1
    assert port.plans[0].tool_name == "read_file"


def test_level_one_tool_waits_for_exact_approval_then_executes() -> None:
    conversation, port = agent(
        [
            tool_message(
                "write_file",
                (
                    '{"workspace_id":"local_voice_agent",'
                    '"relative_path":"tests/example.txt",'
                    '"expected_sha256":null,"content":"safe"}'
                ),
            ),
            {"content": "승인된 파일 생성을 완료했습니다."},
        ]
    )
    pending = asyncio.run(
        conversation.respond("파일 만들어줘", language="ko")
    )
    assert pending.text is None
    assert pending.pending_approval_id is not None
    approval_event = pending.events[-1]
    assert approval_event.type == "tool.approval.required"
    assert port.plans == []

    completed = asyncio.run(
        conversation.decide_approval(
            approval_id=pending.pending_approval_id,
            approved=True,
            arguments_digest=str(
                approval_event.payload["arguments_digest"]
            ),
            reason=None,
        )
    )
    assert completed.text == "승인된 파일 생성을 완료했습니다."
    assert [event.type for event in completed.events] == [
        "assistant.state",
        "tool.started",
        "assistant.state",
        "tool.completed",
    ]
    assert len(port.plans) == 1
    assert port.plans[0].approval.state.value == "APPROVED"


def test_rejected_level_one_tool_never_executes() -> None:
    conversation, port = agent(
        [
            tool_message(
                "write_file",
                (
                    '{"workspace_id":"local_voice_agent",'
                    '"relative_path":"tests/example.txt",'
                    '"expected_sha256":null,"content":"safe"}'
                ),
            ),
        ]
    )
    pending = asyncio.run(
        conversation.respond("파일 만들어줘", language="ko")
    )
    rejected = asyncio.run(
        conversation.decide_approval(
            approval_id=pending.pending_approval_id,
            approved=False,
            arguments_digest=str(
                pending.events[-1].payload["arguments_digest"]
            ),
            reason="사용자 취소",
        )
    )
    assert rejected.text == "요청한 변경을 실행하지 않았습니다."
    assert rejected.events[0].payload["error_code"] == "USER_REJECTED"
    assert port.plans == []


def test_parallel_tool_calls_fail_closed() -> None:
    message = tool_message("git_status", '{"workspace_id":"local_voice_agent"}')
    message["tool_calls"] = [
        *message["tool_calls"],
        {
            "id": "model-call-2",
            "type": "function",
            "function": {
                "name": "git_branch",
                "arguments": '{"workspace_id":"local_voice_agent"}',
            },
        },
    ]
    conversation, _ = agent([message])
    with pytest.raises(ToolAgentError, match="parallel"):
        asyncio.run(conversation.respond("상태 확인", language="ko"))
