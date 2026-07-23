"""Async PostgreSQL persistence with CAS and transactional outbox invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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

from ..application.tool_planner import ToolPlan
from ..domain.approval import ApprovalState
from ..domain.errors import OptimisticLockError
from ..domain.tool_execution import ToolExecutionState


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
approval_requests = Table(
    "approval_requests",
    metadata,
    Column("id", PostgreSQLUUID(as_uuid=True), primary_key=True),
    Column(
        "execution_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tool_executions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("state", Text, nullable=False),
    Column("version", BigInteger, nullable=False, default=0),
    Column("binding_sha256", String(64), nullable=False),
    Column("precondition_version", BigInteger, nullable=False),
    Column("display_summary", JSONB, nullable=False, default=dict),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("session_id", PostgreSQLUUID(as_uuid=True), nullable=True),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("risk_level", SmallInteger, nullable=False),
    Column("result", Text, nullable=False),
    Column("metadata", JSONB, nullable=False, default=dict),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
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


@dataclass(frozen=True, slots=True)
class StoredApprovalRequest:
    approval_id: UUID
    execution_id: UUID
    state: str
    version: int
    binding_sha256: str
    precondition_version: int
    expires_at: datetime

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "StoredApprovalRequest":
        return cls(
            approval_id=row["id"],
            execution_id=row["execution_id"],
            state=row["state"],
            version=row["version"],
            binding_sha256=row["binding_sha256"],
            precondition_version=row["precondition_version"],
            expires_at=row["expires_at"],
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

    async def _append_execution_event(
        self,
        connection: Any,
        *,
        execution_id: UUID,
        sequence: int,
        event_type: str,
        tool_name: str,
        payload: Mapping[str, Any],
    ) -> None:
        event_payload = dict(payload)
        await connection.execute(
            insert(tool_execution_events).values(
                execution_id=execution_id,
                sequence=sequence,
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
                sequence=sequence,
                payload={"tool_name": tool_name, **event_payload},
            )
        )

    async def _append_audit(
        self,
        connection: Any,
        *,
        session_id: UUID | None,
        action: str,
        risk_level: int,
        result: str,
        metadata: Mapping[str, Any],
    ) -> None:
        await connection.execute(
            insert(audit_logs).values(
                session_id=session_id,
                actor="pc-server",
                action=action,
                risk_level=risk_level,
                result=result,
                metadata=dict(metadata),
            )
        )

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

    async def persist_planned_plan(self, plan: ToolPlan) -> StoredToolExecution:
        """Durably create PLANNED plus its first policy transition in one tx."""
        execution = plan.execution
        if execution is None:
            raise ValueError("policy-denied plans have no durable execution")
        if execution.state not in {
            ToolExecutionState.QUEUED,
            ToolExecutionState.WAITING_APPROVAL,
        }:
            raise ValueError("planned execution has an invalid initial state")

        execution_id = UUID(execution.execution_id)
        session_id = UUID(execution.session_id)
        request_id = UUID(execution.request_id)
        tool_call_id = UUID(execution.tool_call_id)
        async with self._engine.begin() as connection:
            existing = await connection.execute(
                select(tool_executions).where(
                    and_(
                        tool_executions.c.session_id == session_id,
                        tool_executions.c.idempotency_key == execution.idempotency_key,
                    )
                )
            )
            prior = existing.mappings().one_or_none()
            if prior is not None:
                if (
                    prior["tool_name"] != execution.tool_name
                    or prior["normalized_arguments_sha256"]
                    != execution.normalized_arguments_sha256
                ):
                    raise ValueError("idempotency key conflicts with another request")
                return StoredToolExecution.from_row(prior)

            await connection.execute(
                insert(tool_executions).values(
                    id=execution_id,
                    session_id=session_id,
                    request_id=request_id,
                    tool_call_id=tool_call_id,
                    tool_name=execution.tool_name,
                    risk_level=int(plan.policy.risk_level),
                    state=ToolExecutionState.PLANNED.value,
                    version=0,
                    idempotency_key=execution.idempotency_key,
                    normalized_arguments_sha256=execution.normalized_arguments_sha256,
                    normalized_arguments=dict(plan.normalized_arguments),
                    result_metadata={},
                    cancellable=execution.cancellable,
                )
            )
            await self._append_execution_event(
                connection,
                execution_id=execution_id,
                sequence=0,
                event_type="tool.planned",
                tool_name=execution.tool_name,
                payload={"state": ToolExecutionState.PLANNED.value},
            )
            initial_event = (
                "tool.queued"
                if execution.state is ToolExecutionState.QUEUED
                else "tool.approval.required"
            )
            result = await connection.execute(
                update(tool_executions)
                .where(
                    and_(
                        tool_executions.c.id == execution_id,
                        tool_executions.c.version == 0,
                    )
                )
                .values(
                    state=execution.state.value,
                    version=execution.version,
                    updated_at=func.now(),
                )
                .returning(tool_executions)
            )
            row = result.mappings().one()
            await self._append_execution_event(
                connection,
                execution_id=execution_id,
                sequence=execution.version,
                event_type=initial_event,
                tool_name=execution.tool_name,
                payload={"state": execution.state.value},
            )
            if plan.approval is not None:
                approval = plan.approval
                await connection.execute(
                    insert(approval_requests).values(
                        id=UUID(approval.approval_id),
                        execution_id=execution_id,
                        state=approval.state.value,
                        version=approval.version,
                        binding_sha256=approval.normalized_arguments_sha256,
                        precondition_version=approval.precondition_version,
                        display_summary={
                            "tool_name": execution.tool_name,
                            "risk_level": int(plan.policy.risk_level),
                        },
                        expires_at=approval.expires_at,
                    )
                )
            await self._append_audit(
                connection,
                session_id=session_id,
                action="tool.plan.persisted",
                risk_level=int(plan.policy.risk_level),
                result=execution.state.value,
                metadata={"execution_id": str(execution_id), "tool_name": execution.tool_name},
            )
            return StoredToolExecution.from_row(row)

    async def decide_approval(
        self,
        *,
        approval_id: str,
        approved: bool,
        arguments_digest: str,
        precondition_version: int,
        expected_approval_version: int,
        reason: str | None,
    ) -> StoredToolExecution:
        """Bind one decision to its approval and execution with CAS in one tx."""
        approval_uuid = UUID(approval_id)
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            approval_result = await connection.execute(
                select(approval_requests)
                .where(approval_requests.c.id == approval_uuid)
                .with_for_update()
            )
            approval_row = approval_result.mappings().one_or_none()
            if approval_row is None:
                raise OptimisticLockError("approval is missing")
            approval = StoredApprovalRequest.from_row(approval_row)
            execution_result = await connection.execute(
                select(tool_executions)
                .where(tool_executions.c.id == approval.execution_id)
                .with_for_update()
            )
            execution_row = execution_result.mappings().one()
            execution = StoredToolExecution.from_row(execution_row)
            if approval.state != ApprovalState.PENDING.value:
                raise OptimisticLockError("approval is no longer pending")
            if approval.version != expected_approval_version:
                raise OptimisticLockError("approval version is stale")
            if (
                approval.binding_sha256 != arguments_digest
                or approval.precondition_version != precondition_version
            ):
                raise ValueError("approval binding does not match the planned operation")
            if execution.state != ToolExecutionState.WAITING_APPROVAL.value:
                raise OptimisticLockError("execution is not waiting for approval")

            decision_state = (
                ApprovalState.EXPIRED.value
                if now >= approval.expires_at
                else (ApprovalState.APPROVED.value if approved else ApprovalState.DENIED.value)
            )
            await connection.execute(
                update(approval_requests)
                .where(
                    and_(
                        approval_requests.c.id == approval_uuid,
                        approval_requests.c.version == approval.version,
                    )
                )
                .values(
                    state=decision_state,
                    version=approval.version + 1,
                    decided_at=now,
                )
            )
            target_state = (
                ToolExecutionState.QUEUED.value
                if decision_state == ApprovalState.APPROVED.value
                else ToolExecutionState.CANCELLED.value
            )
            event_type = (
                "tool.queued"
                if target_state == ToolExecutionState.QUEUED.value
                else "tool.cancelled"
            )
            result = await connection.execute(
                update(tool_executions)
                .where(
                    and_(
                        tool_executions.c.id == execution.execution_id,
                        tool_executions.c.version == execution.version,
                    )
                )
                .values(
                    state=target_state,
                    version=execution.version + 1,
                    updated_at=func.now(),
                )
                .returning(tool_executions)
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise OptimisticLockError("execution version is stale")
            await self._append_execution_event(
                connection,
                execution_id=execution.execution_id,
                sequence=execution.version + 1,
                event_type=event_type,
                tool_name=execution.tool_name,
                payload={"state": target_state, "approval_id": str(approval_uuid)},
            )
            await self._append_audit(
                connection,
                session_id=execution.session_id,
                action="tool.approval.decided",
                risk_level=execution.risk_level,
                result=decision_state,
                metadata={
                    "execution_id": str(execution.execution_id),
                    "approval_id": str(approval_uuid),
                    "reason_provided": bool(reason),
                },
            )
            if decision_state == ApprovalState.EXPIRED.value:
                raise ValueError("approval has expired")
            return StoredToolExecution.from_row(row)

    async def transition_tool_execution(
        self,
        execution_id: UUID | str,
        *,
        expected_version: int,
        to_state: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        result_metadata: Mapping[str, Any] | None = None,
    ) -> StoredToolExecution:
        execution_id = UUID(str(execution_id))
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
            await self._append_execution_event(
                connection,
                execution_id=execution_id,
                sequence=next_version,
                event_type=event_type,
                tool_name=row["tool_name"],
                payload=event_payload,
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
