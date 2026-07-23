"""Closed WebSocket envelope matching the repository JSON Schema."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    type: str
    session_id: UUID
    request_id: UUID
    sequence: int
    payload: dict[str, Any]
    timestamp: datetime
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("unsupported schema_version")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")

    @classmethod
    def create(
        cls,
        *,
        type: str,
        session_id: UUID,
        request_id: UUID,
        sequence: int,
        payload: dict[str, Any],
    ) -> "EventEnvelope":
        return cls(
            type=type,
            session_id=session_id,
            request_id=request_id,
            sequence=sequence,
            payload=payload,
            timestamp=datetime.now(timezone.utc),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "type": self.type,
            "session_id": str(self.session_id),
            "request_id": str(self.request_id),
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
        }
