"""Bounded Gemma tool loop with exact policy, approval, and executor binding."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from ..application.execute_tool import ExecuteQueuedTool, ToolExecutionOutcome
from ..application.tool_execution_lifecycle import DurableToolExecutionLifecycle
from ..application.tool_planner import ToolPlan, ToolPlanner
from ..application.voice_turn import ConversationReply, VoiceEvent
from ..domain.policy import PolicyAction, RiskLevel
from .tool_registry import ToolRegistry


EXECUTOR_TOOL_NAMES = frozenset(
    {
        "apply_patch",
        "browser_click",
        "browser_close",
        "browser_console_logs",
        "browser_download_status",
        "browser_get_page_state",
        "browser_launch",
        "browser_navigate",
        "browser_network_errors",
        "browser_screenshot",
        "browser_scroll",
        "browser_select",
        "browser_type",
        "calculate_hash",
        "check_port",
        "git_blame",
        "git_branch",
        "git_diff",
        "git_diff_stat",
        "git_log",
        "git_show",
        "git_status",
        "inspect_cpu",
        "inspect_disk",
        "inspect_gpu",
        "inspect_memory",
        "inspect_network",
        "inspect_process",
        "inspect_service",
        "inspect_test_log",
        "list_files",
        "list_processes",
        "list_recent_files",
        "list_services",
        "read_file",
        "read_file_range",
        "rollback_file_change",
        "run_tests",
        "search_files",
        "ui_capture_screen",
        "ui_click_element",
        "ui_focus_window",
        "ui_get_accessibility_tree",
        "ui_list_windows",
        "ui_press_key",
        "ui_type_text",
        "write_file",
    }
)
MAX_TOOL_ROUNDS = 4
MAX_MODEL_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TOOL_RESULT_PROMPT_BYTES = 256 * 1024
ChatTransport = Callable[[dict[str, object]], dict[str, object]]


class ToolAgentError(RuntimeError):
    pass


@dataclass(slots=True)
class PendingToolCall:
    plan: ToolPlan
    messages: list[dict[str, object]]
    model_tool_call_id: str
    rounds: int
    language: str


class ToolAgentConversation:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        session_id: UUID,
        request_id: UUID,
        registry: ToolRegistry,
        planner: ToolPlanner,
        executor: ExecuteQueuedTool,
        lifecycle: DurableToolExecutionLifecycle | None = None,
        timeout_seconds: float = 120,
        transport: ChatTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("model URL must be uncredentialed loopback HTTP")
        if not model or len(model) > 512:
            raise ValueError("model name is invalid")
        if len(api_key) < 32:
            raise ValueError("model API key must contain at least 32 characters")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("model timeout is invalid")
        missing = EXECUTOR_TOOL_NAMES.difference(
            definition["function"]["name"]
            for definition in registry.as_function_tools()
        )
        if missing:
            raise ValueError(f"executor tool definitions are missing: {sorted(missing)}")
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key
        self._session_id = session_id
        self._request_id = request_id
        self._registry = registry
        self._planner = planner
        self._executor = executor
        self._lifecycle = lifecycle
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._post
        self._tools = tuple(
            registry.get(name).as_function_tool()
            for name in sorted(EXECUTOR_TOOL_NAMES)
        )
        self._pending: PendingToolCall | None = None

    async def respond(self, text: str, *, language: str) -> ConversationReply:
        if self._pending is not None:
            raise ToolAgentError("a tool approval is already pending")
        if not text.strip() or len(text) > 65_536:
            raise ValueError("conversation text is invalid")
        if not language or len(language) > 32:
            raise ValueError("conversation language is invalid")
        messages: list[dict[str, object]] = [
            {
                "role": "system",
                "content": (
                    "You are a local voice computer-use assistant. Reply "
                    f"concisely in the user's language ({language}). Use only "
                    "the supplied tools. Never claim a tool ran unless a tool "
                    "result is present. Prefer observation before mutation."
                ),
            },
            {"role": "user", "content": text},
        ]
        return await self._advance(messages, rounds=0, language=language)

    async def decide_approval(
        self,
        *,
        approval_id: UUID,
        approved: bool,
        arguments_digest: str,
        reason: str | None,
    ) -> ConversationReply:
        pending = self._pending
        if pending is None or pending.plan.approval is None:
            raise ToolAgentError("no tool approval is pending")
        approval = pending.plan.approval
        if str(approval_id) != approval.approval_id:
            raise ToolAgentError("approval identifier mismatch")
        decided = approval.decide(
            approved=approved,
            normalized_arguments_sha256=arguments_digest,
            precondition_version=approval.precondition_version,
            expected_version=approval.version,
        )
        if self._lifecycle is not None:
            await self._lifecycle.decide_approval(
                pending.plan,
                approved=approved,
                arguments_digest=arguments_digest,
                reason=reason,
            )
        self._pending = None
        if not approved:
            return ConversationReply(
                text=(
                    "요청한 변경을 실행하지 않았습니다."
                    if pending.language == "ko"
                    else "The requested change was not executed."
                ),
                events=(
                    VoiceEvent(
                        "tool.failed",
                        {
                            "tool_call_id": decided.tool_call_id,
                            "tool_name": pending.plan.tool_name,
                            "error_code": "USER_REJECTED",
                            "message": reason or "The user rejected the operation.",
                            "rollback_available": False,
                            "evidence_ids": [],
                        },
                    ),
                ),
            )
        queued = self._planner.queue_approved(
            pending.plan,
            decided_approval=decided,
            expected_execution_version=pending.plan.execution.version,
        )
        return await self._execute_and_continue(
            queued,
            messages=pending.messages,
            model_tool_call_id=pending.model_tool_call_id,
            rounds=pending.rounds,
            language=pending.language,
        )

    async def cancel_pending_approval(self) -> None:
        """Durably reject an unconsumed approval before discarding local state."""
        pending = self._pending
        if pending is None or pending.plan.approval is None:
            return
        approval = pending.plan.approval
        if self._lifecycle is not None:
            await self._lifecycle.decide_approval(
                pending.plan,
                approved=False,
                arguments_digest=approval.normalized_arguments_sha256,
                reason="cancelled_before_execution",
            )
        self._pending = None

    async def _advance(
        self,
        messages: list[dict[str, object]],
        *,
        rounds: int,
        language: str,
    ) -> ConversationReply:
        message = await asyncio.to_thread(
            self._transport,
            self._request_payload(messages),
        )
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ToolAgentError("model returned neither text nor a tool call")
            return ConversationReply(text=content.strip())
        if not isinstance(tool_calls, list) or len(tool_calls) != 1:
            raise ToolAgentError("parallel or malformed tool calls are rejected")
        if rounds >= MAX_TOOL_ROUNDS:
            raise ToolAgentError("tool-call round limit reached")
        call = tool_calls[0]
        if not isinstance(call, dict):
            raise ToolAgentError("tool call is malformed")
        function = call.get("function")
        model_call_id = call.get("id")
        if (
            not isinstance(function, dict)
            or not isinstance(model_call_id, str)
            or not 1 <= len(model_call_id) <= 512
        ):
            raise ToolAgentError("tool call identity is malformed")
        tool_name = function.get("name")
        encoded_arguments = function.get("arguments")
        if (
            not isinstance(tool_name, str)
            or tool_name not in EXECUTOR_TOOL_NAMES
            or not isinstance(encoded_arguments, str)
            or len(encoded_arguments) > 2 * 1024 * 1024
        ):
            raise ToolAgentError("model selected an unavailable tool")
        try:
            arguments = json.loads(encoded_arguments)
        except json.JSONDecodeError as error:
            raise ToolAgentError("tool arguments are not valid JSON") from error
        if not isinstance(arguments, dict):
            raise ToolAgentError("tool arguments must be an object")

        tool_call_id = uuid4()
        plan = self._planner.plan(
            session_id=str(self._session_id),
            request_id=str(self._request_id),
            tool_call_id=str(tool_call_id),
            tool_name=tool_name,
            arguments=arguments,
            idempotency_key=str(uuid4()),
            precondition_version=0,
        )
        plan_events = self._plan_events(plan)
        assistant_message = {
            "role": "assistant",
            "content": message.get("content"),
            "tool_calls": tool_calls,
        }
        continued_messages = [*messages, assistant_message]
        if plan.policy.action is PolicyAction.DENY or plan.execution is None:
            return ConversationReply(
                text=(
                    "이 도구는 현재 보안 정책상 사용할 수 없습니다."
                    if language == "ko"
                    else "That tool is unavailable under the current policy."
                ),
                events=tuple(plan_events),
            )
        if self._lifecycle is not None:
            await self._lifecycle.persist_plan(plan)
        if plan.policy.action is PolicyAction.REQUIRE_APPROVAL:
            if plan.approval is None:
                raise ToolAgentError("approval-bound plan has no approval")
            self._pending = PendingToolCall(
                plan=plan,
                messages=continued_messages,
                model_tool_call_id=model_call_id,
                rounds=rounds + 1,
                language=language,
            )
            return ConversationReply(
                text=None,
                events=tuple(
                    [
                        *plan_events,
                        VoiceEvent(
                            "assistant.state",
                            {"state": "waiting_approval"},
                        ),
                        self._approval_event(plan),
                    ]
                ),
                pending_approval_id=UUID(plan.approval.approval_id),
            )
        return await self._execute_and_continue(
            plan,
            messages=continued_messages,
            model_tool_call_id=model_call_id,
            rounds=rounds + 1,
            language=language,
            prefix_events=plan_events,
        )

    async def _execute_and_continue(
        self,
        plan: ToolPlan,
        *,
        messages: list[dict[str, object]],
        model_tool_call_id: str,
        rounds: int,
        language: str,
        prefix_events: list[VoiceEvent] | None = None,
    ) -> ConversationReply:
        if plan.execution is None:
            raise ToolAgentError("executable plan has no execution")
        started_at = datetime.now(timezone.utc)
        events = list(prefix_events or [])
        events.extend(
            [
                VoiceEvent("assistant.state", {"state": "executing"}),
                VoiceEvent(
                    "tool.started",
                    {
                        "tool_call_id": plan.execution.tool_call_id,
                        "tool_name": plan.tool_name,
                        "started_at": started_at.isoformat(),
                    },
                ),
            ]
        )
        if self._lifecycle is not None:
            outcome = await self._lifecycle.execute(plan)
        else:
            outcome = await asyncio.to_thread(
                self._executor.execute,
                plan,
                expected_execution_version=plan.execution.version,
            )
        if not outcome.succeeded or outcome.receipt is None:
            events.append(self._failure_event(plan, outcome))
            return ConversationReply(
                text=(
                    "도구 실행에 실패했습니다. 실행 증거를 확인해 주세요."
                    if language == "ko"
                    else "Tool execution failed; inspect the execution evidence."
                ),
                events=tuple(events),
            )
        events.extend(
            [
                VoiceEvent("assistant.state", {"state": "verifying"}),
                VoiceEvent(
                    "tool.completed",
                    {
                        "tool_call_id": plan.execution.tool_call_id,
                        "tool_name": plan.tool_name,
                        "result": dict(outcome.receipt.result),
                        "evidence_ids": [outcome.receipt.evidence_id],
                    },
                ),
            ]
        )
        result_json = json.dumps(
            dict(outcome.receipt.result),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(result_json.encode("utf-8")) > MAX_TOOL_RESULT_PROMPT_BYTES:
            raise ToolAgentError("tool result exceeds model prompt bound")
        continued = [
            *messages,
            {
                "role": "tool",
                "tool_call_id": model_tool_call_id,
                "content": result_json,
            },
        ]
        next_reply = await self._advance(
            continued,
            rounds=rounds,
            language=language,
        )
        return ConversationReply(
            text=next_reply.text,
            events=tuple([*events, *next_reply.events]),
            pending_approval_id=next_reply.pending_approval_id,
        )

    def _request_payload(
        self,
        messages: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "model": self._model,
            "messages": messages,
            "tools": self._tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "temperature": 0.1,
            "max_tokens": 512,
            "stream": False,
        }

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            self._endpoint,
            data=encoded,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read(MAX_MODEL_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, TimeoutError) as error:
            raise ToolAgentError("model request failed") from error
        if len(raw) > MAX_MODEL_RESPONSE_BYTES:
            raise ToolAgentError("model response is too large")
        try:
            value = json.loads(raw)
            message = value["choices"][0]["message"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise ToolAgentError("model response shape is invalid") from error
        if not isinstance(message, dict):
            raise ToolAgentError("model message is invalid")
        return message

    def _plan_events(self, plan: ToolPlan) -> list[VoiceEvent]:
        risk = int(plan.policy.risk_level)
        return [
            VoiceEvent("assistant.state", {"state": "selecting_tool"}),
            VoiceEvent(
                "tool.plan",
                {
                    "plan_id": str(uuid4()),
                    "goal": f"Execute {plan.tool_name} for the current request.",
                    "requires_approval": (
                        plan.policy.action is PolicyAction.REQUIRE_APPROVAL
                    ),
                    "steps": [
                        {
                            "sequence": 1,
                            "summary": f"Validate and execute {plan.tool_name}.",
                            "tool_name": plan.tool_name,
                            "risk_level": risk,
                        }
                    ],
                },
            ),
        ]

    @staticmethod
    def _approval_event(plan: ToolPlan) -> VoiceEvent:
        if plan.approval is None or plan.execution is None:
            raise ToolAgentError("approval event requires a bound plan")
        arguments = dict(plan.normalized_arguments)
        workspace = str(arguments.get("workspace_id", "registered workspace"))
        relative = str(arguments.get("relative_path", plan.tool_name))
        target = f"{workspace}:{relative}"[:2048]
        return VoiceEvent(
            "tool.approval.required",
            {
                "approval_id": plan.approval.approval_id,
                "tool_call_id": plan.execution.tool_call_id,
                "tool_name": plan.tool_name,
                "risk_level": int(plan.policy.risk_level),
                "target": target,
                "normalized_arguments": arguments,
                "arguments_digest": (
                    plan.approval.normalized_arguments_sha256
                ),
                "expected_changes": [
                    f"{plan.tool_name} will change only the displayed target."
                ],
                "impact_scope": "One registered local workspace target.",
                "rollback": (
                    "The executor stores an external pre-state backup and "
                    "requires a separate exact rollback approval."
                ),
                "steps": [
                    "Revalidate approval, schema, workspace, and precondition.",
                    "Execute one bounded operation.",
                    "Verify the post-state and persist evidence.",
                ],
                "expires_at": plan.approval.expires_at.isoformat(),
            },
        )

    @staticmethod
    def _failure_event(
        plan: ToolPlan,
        outcome: ToolExecutionOutcome,
    ) -> VoiceEvent:
        if plan.execution is None:
            raise ToolAgentError("failure event requires an execution")
        return VoiceEvent(
            "tool.failed",
            {
                "tool_call_id": plan.execution.tool_call_id,
                "tool_name": plan.tool_name,
                "error_code": outcome.error_code or "TOOL_EXECUTION_FAILED",
                "message": "The bounded tool execution failed.",
                "rollback_available": False,
                "evidence_ids": [],
            },
        )
