from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete

from local_voice_agent_server.domain.errors import OptimisticLockError
from local_voice_agent_server.infrastructure.persistence import (
    PostgresStateStore,
    outbox_events,
    sessions,
)


DATABASE_URL = os.environ.get("LVA_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="LVA_DATABASE_URL is required for PostgreSQL integration tests",
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
