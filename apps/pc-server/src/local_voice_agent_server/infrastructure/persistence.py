"""Async PostgreSQL persistence with CAS and transactional outbox invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
    UUID as PostgreSQLUUID,
    insert as postgresql_insert,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.sql import func

from ..domain.errors import OptimisticLockError


metadata = MetaData()

sessions = Table(
    "sessions",
    metadata,
    Column("id", PostgreSQLUUID(as_uuid=True), primary_key=True),
    Column("state", Text, nullable=False),
    Column("version", BigInteger, nullable=False, default=0),
    Column("client_capabilities", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
tool_executions = Table(
    "tool_executions",
    metadata,
    Column("id", PostgreSQLUUID(as_uuid=True), primary_key=True),
    Column(
        "session_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("request_id", PostgreSQLUUID(as_uuid=True), nullable=False),
    Column("tool_call_id", PostgreSQLUUID(as_uuid=True), nullable=False, unique=True),
    Column("tool_name", Text, nullable=False),
    Column("risk_level", SmallInteger, nullable=False),
    Column("state", Text, nullable=False),
    Column("version", BigInteger, nullable=False, default=0),
    Column("idempotency_key", Text, nullable=False),
    Column("normalized_arguments_sha256", String(64), nullable=False),
    Column("normalized_arguments", JSONB, nullable=False),
    Column("result_metadata", JSONB, nullable=False, default=dict),
    Column("cancellable", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "session_id",
        "idempotency_key",
        name="uq_tool_executions_session_idempotency",
    ),
)
tool_execution_events = Table(
    "tool_execution_events",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column(
        "execution_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tool_executions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("sequence", BigInteger, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False, default=dict),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "execution_id",
        "sequence",
        name="uq_tool_execution_events_sequence",
    ),
)
outbox_events = Table(
    "outbox_events",
    metadata,
    Column("id", PostgreSQLUUID(as_uuid=True), primary_key=True),
    Column("topic", Text, nullable=False),
    Column("aggregate_type", Text, nullable=False),
    Column("aggregate_id", PostgreSQLUUID(as_uuid=True), nullable=False),
    Column("sequence", BigInteger, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("publish_attempts", Integer, nullable=False, default=0),
    UniqueConstraint(
        "aggregate_type",
        "aggregate_id",
        "sequence",
        name="uq_outbox_events_aggregate_sequence",
    ),
)
Index(
    "ix_outbox_events_unpublished",
    outbox_events.c.created_at,
    postgresql_where=outbox_events.c.published_at.is_(None),
)


@dataclass(frozen=True, slots=True)
class StoredToolExecution:
    execution_id: UUID
    session_id: UUID
    request_id: UUID
    tool_call_id: UUID
    tool_name: str
    risk_level: int
    state: str
    version: int
    idempotency_key: str
    normalized_arguments_sha256: str
    normalized_arguments: Mapping[str, Any]
    result_metadata: Mapping[str, Any]
    cancellable: bool

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "StoredToolExecution":
        return cls(
            execution_id=row["id"],
            session_id=row["session_id"],
            request_id=row["request_id"],
            tool_call_id=row["tool_call_id"],
            tool_name=row["tool_name"],
            risk_level=row["risk_level"],
            state=row["state"],
            version=row["version"],
            idempotency_key=row["idempotency_key"],
            normalized_arguments_sha256=row["normalized_arguments_sha256"],
            normalized_arguments=row["normalized_arguments"],
            result_metadata=row["result_metadata"],
            cancellable=row["cancellable"],
        )


class PostgresStateStore:
    """Minimal durable adapter used by the application composition root."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> "PostgresStateStore":
        if not database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("an asyncpg PostgreSQL URL is required")
        return cls(create_async_engine(database_url, pool_pre_ping=True))

    async def close(self) -> None:
        await self._engine.dispose()

    async def ensure_session(
        self,
        session_id: UUID,
        *,
        state: str = "ACTIVE",
        client_capabilities: Mapping[str, Any] | None = None,
    ) -> None:
        statement = (
            postgresql_insert(sessions)
            .values(
                id=session_id,
                state=state,
                version=0,
                client_capabilities=dict(client_capabilities or {}),
            )
            .on_conflict_do_nothing(index_elements=[sessions.c.id])
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def create_tool_execution(
        self,
        *,
        execution_id: UUID,
        session_id: UUID,
        request_id: UUID,
        tool_call_id: UUID,
        tool_name: str,
        risk_level: int,
        state: str,
        idempotency_key: str,
        normalized_arguments_sha256: str,
        normalized_arguments: Mapping[str, Any],
        cancellable: bool,
    ) -> tuple[StoredToolExecution, bool]:
        """Create atomically, returning the prior exact idempotent record."""
        async with self._engine.begin() as connection:
            existing = await connection.execute(
                select(tool_executions).where(
                    and_(
                        tool_executions.c.session_id == session_id,
                        tool_executions.c.idempotency_key == idempotency_key,
                    )
                )
            )
            prior = existing.mappings().one_or_none()
            if prior is not None:
                exact = (
                    prior["tool_name"] == tool_name
                    and prior["normalized_arguments_sha256"]
                    == normalized_arguments_sha256
                )
                if not exact:
                    raise ValueError("idempotency key conflicts with another request")
                return StoredToolExecution.from_row(prior), False

            values = {
                "id": execution_id,
                "session_id": session_id,
                "request_id": request_id,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "risk_level": risk_level,
                "state": state,
                "version": 0,
                "idempotency_key": idempotency_key,
                "normalized_arguments_sha256": normalized_arguments_sha256,
                "normalized_arguments": dict(normalized_arguments),
                "result_metadata": {},
                "cancellable": cancellable,
            }
            row = (
                await connection.execute(
                    insert(tool_executions).values(**values).returning(tool_executions)
                )
            ).mappings().one()
            await connection.execute(
                insert(tool_execution_events).values(
                    execution_id=execution_id,
                    sequence=0,
                    event_type="tool.planned",
                    payload={"state": state},
                )
            )
            await connection.execute(
                insert(outbox_events).values(
                    id=uuid4(),
                    topic="tool.planned",
                    aggregate_type="tool_execution",
                    aggregate_id=execution_id,
                    sequence=0,
                    payload={"state": state, "tool_name": tool_name},
                )
            )
            return StoredToolExecution.from_row(row), True

    async def transition_tool_execution(
        self,
        execution_id: UUID,
        *,
        expected_version: int,
        to_state: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        result_metadata: Mapping[str, Any] | None = None,
    ) -> StoredToolExecution:
        next_version = expected_version + 1
        values: dict[str, Any] = {
            "state": to_state,
            "version": next_version,
            "updated_at": func.now(),
        }
        if result_metadata is not None:
            values["result_metadata"] = dict(result_metadata)
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(tool_executions)
                .where(
                    and_(
                        tool_executions.c.id == execution_id,
                        tool_executions.c.version == expected_version,
                    )
                )
                .values(**values)
                .returning(tool_executions)
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise OptimisticLockError(
                    f"execution {execution_id} is missing or version is stale"
                )
            event_payload = {"state": to_state, **dict(payload or {})}
            await connection.execute(
                insert(tool_execution_events).values(
                    execution_id=execution_id,
                    sequence=next_version,
                    event_type=event_type,
                    payload=event_payload,
                )
            )
            await connection.execute(
                insert(outbox_events).values(
                    id=uuid4(),
                    topic=event_type,
                    aggregate_type="tool_execution",
                    aggregate_id=execution_id,
                    sequence=next_version,
                    payload=event_payload,
                )
            )
            return StoredToolExecution.from_row(row)

    async def get_tool_execution(self, execution_id: UUID) -> StoredToolExecution | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(tool_executions).where(tool_executions.c.id == execution_id)
            )
            row = result.mappings().one_or_none()
            return None if row is None else StoredToolExecution.from_row(row)

    async def unpublished_outbox_count(self) -> int:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(func.count())
                .select_from(outbox_events)
                .where(outbox_events.c.published_at.is_(None))
            )
            return int(result.scalar_one())
