from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from local_voice_agent_server.application.execute_tool import ExecuteQueuedTool
from local_voice_agent_server.application.ports import ToolExecutionReceipt
from local_voice_agent_server.application.tool_execution_lifecycle import (
    DurableToolExecutionLifecycle,
)
from local_voice_agent_server.application.tool_planner import ToolPlanner
from local_voice_agent_server.domain.digests import sha256_json
from local_voice_agent_server.domain.errors import OptimisticLockError
from local_voice_agent_server.infrastructure.persistence import (
    PostgresStateStore,
    approval_requests,
    audit_logs,
    outbox_events,
    sessions,
)
from local_voice_agent_server.infrastructure.tool_registry import ToolRegistry


DATABASE_URL = os.environ.get("LVA_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="LVA_DATABASE_URL is required for PostgreSQL integration tests",
)
ROOT = Path(__file__).resolve().parents[3]


class SuccessPort:
    def execute(self, plan, *, requested_at=None):
        result = {"tool_name": plan.tool_name, "observed": True}
        return ToolExecutionReceipt(
            execution_id=plan.execution.execution_id,
            duplicate=False,
            result=result,
            result_sha256=sha256_json(result),
            evidence_id=str(uuid4()),
        )


def _registry() -> ToolRegistry:
    return ToolRegistry.load(
        definitions_dir=ROOT / "packages/tool-registry/definitions",
        definition_schema_path=(
            ROOT / "packages/tool-registry/schemas/tool-definition.schema.json"
        ),
        disabled_tools={"restricted_shell"},
    )


def test_idempotency_cas_and_outbox_are_durable() -> None:
    asyncio.run(_exercise_persistence())


async def _exercise_persistence() -> None:
    assert DATABASE_URL is not None
    store = PostgresStateStore.from_url(DATABASE_URL)
    session_id = uuid4()
    execution_id = uuid4()
    arguments_sha256 = "a" * 64
    try:
        await store.ensure_session(session_id)
        first, created = await store.create_tool_execution(
            execution_id=execution_id,
            session_id=session_id,
            request_id=uuid4(),
            tool_call_id=uuid4(),
            tool_name="inspect_gpu",
            risk_level=0,
            state="PLANNED",
            idempotency_key="integration-idempotency",
            normalized_arguments_sha256=arguments_sha256,
            normalized_arguments={},
            cancellable=True,
        )
        assert created is True
        assert first.version == 0
        assert await store.unpublished_outbox_count() >= 1

        duplicate, created = await store.create_tool_execution(
            execution_id=uuid4(),
            session_id=session_id,
            request_id=uuid4(),
            tool_call_id=uuid4(),
            tool_name="inspect_gpu",
            risk_level=0,
            state="PLANNED",
            idempotency_key="integration-idempotency",
            normalized_arguments_sha256=arguments_sha256,
            normalized_arguments={},
            cancellable=True,
        )
        assert created is False
        assert duplicate.execution_id == execution_id

        with pytest.raises(ValueError, match="idempotency key conflicts"):
            await store.create_tool_execution(
                execution_id=uuid4(),
                session_id=session_id,
                request_id=uuid4(),
                tool_call_id=uuid4(),
                tool_name="read_file",
                risk_level=0,
                state="PLANNED",
                idempotency_key="integration-idempotency",
                normalized_arguments_sha256="b" * 64,
                normalized_arguments={"relative_path": "README.md"},
                cancellable=True,
            )

        queued = await store.transition_tool_execution(
            execution_id,
            expected_version=0,
            to_state="QUEUED",
            event_type="tool.queued",
        )
        assert queued.version == 1
        assert queued.state == "QUEUED"

        with pytest.raises(OptimisticLockError):
            await store.transition_tool_execution(
                execution_id,
                expected_version=0,
                to_state="RUNNING",
                event_type="tool.started",
            )

        restarted = PostgresStateStore.from_url(DATABASE_URL)
        try:
            restored = await restarted.get_tool_execution(execution_id)
            assert restored is not None
            assert restored.state == "QUEUED"
            assert restored.version == 1
        finally:
            await restarted.close()
    finally:
        async with store._engine.begin() as connection:
            await connection.execute(
                delete(outbox_events).where(
                    outbox_events.c.aggregate_id == execution_id
                )
            )
            await connection.execute(delete(sessions).where(sessions.c.id == session_id))
        await store.close()


def test_durable_approval_and_execution_lifecycle() -> None:
    asyncio.run(_exercise_durable_lifecycle())


async def _exercise_durable_lifecycle() -> None:
    assert DATABASE_URL is not None
    store = PostgresStateStore.from_url(DATABASE_URL)
    session_id = uuid4()
    execution_ids: set[UUID] = set()
    registry = _registry()
    planner = ToolPlanner(registry)
    try:
        await store.ensure_session(session_id)
        approval_plan = planner.plan(
            session_id=str(session_id),
            request_id=str(uuid4()),
            tool_call_id=str(uuid4()),
            tool_name="write_file",
            arguments={
                "workspace_id": "local_voice_agent",
                "relative_path": "tests/durable.txt",
                "expected_sha256": None,
                "content": "safe",
            },
            idempotency_key=str(uuid4()),
            precondition_version=0,
        )
        await store.persist_planned_plan(approval_plan)
        assert approval_plan.execution is not None
        approval_execution_id = UUID(approval_plan.execution.execution_id)
        execution_ids.add(approval_execution_id)
        persisted_waiting = await store.get_tool_execution(
            approval_execution_id
        )
        assert persisted_waiting is not None
        assert persisted_waiting.state == "WAITING_APPROVAL"
        assert persisted_waiting.version == 1
        assert approval_plan.approval is not None
        approved = await store.decide_approval(
            approval_id=approval_plan.approval.approval_id,
            approved=True,
            arguments_digest=approval_plan.approval.normalized_arguments_sha256,
            precondition_version=approval_plan.approval.precondition_version,
            expected_approval_version=approval_plan.approval.version,
            reason="",
        )
        assert approved.state == "QUEUED"
        assert approved.version == 2

        observe_plan = planner.plan(
            session_id=str(session_id),
            request_id=str(uuid4()),
            tool_call_id=str(uuid4()),
            tool_name="inspect_gpu",
            arguments={},
            idempotency_key=str(uuid4()),
            precondition_version=0,
        )
        lifecycle = DurableToolExecutionLifecycle(
            store=store,
            executor=ExecuteQueuedTool(SuccessPort()),
        )
        await lifecycle.persist_plan(observe_plan)
        outcome = await lifecycle.execute(observe_plan)
        assert outcome.succeeded is True
        assert observe_plan.execution is not None
        observe_execution_id = UUID(observe_plan.execution.execution_id)
        execution_ids.add(observe_execution_id)
        stored_success = await store.get_tool_execution(
            observe_execution_id
        )
        assert stored_success is not None
        assert stored_success.state == "SUCCEEDED"
        assert stored_success.version == 4
        async with store._engine.connect() as connection:
            approval_count = await connection.execute(
                select(approval_requests.c.id).where(
                    approval_requests.c.execution_id
                    == approval_execution_id
                )
            )
            assert approval_count.scalar_one() is not None
    finally:
        async with store._engine.begin() as connection:
            await connection.execute(delete(audit_logs).where(audit_logs.c.session_id == session_id))
            if execution_ids:
                await connection.execute(
                    delete(outbox_events).where(
                        outbox_events.c.aggregate_id.in_(execution_ids)
                    )
                )
            await connection.execute(delete(sessions).where(sessions.c.id == session_id))
        await store.close()
