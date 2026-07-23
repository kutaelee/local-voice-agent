"""Closed client payload models at the WebSocket trust boundary."""

from __future__ import annotations

import base64
import binascii
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClosedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AudioInputStartPayload(ClosedPayload):
    audio_stream_id: UUID
    encoding: Literal["pcm_s16le", "opus"]
    sample_rate_hz: Literal[16000, 24000, 48000]
    channels: Literal[1, 2]


class AudioInputChunkPayload(ClosedPayload):
    audio_stream_id: UUID
    chunk_index: Annotated[int, Field(ge=0)]
    encoding: Literal["pcm_s16le", "opus"]
    duration_ms: Annotated[int, Field(ge=1, le=1000)]
    data_base64: Annotated[str, Field(max_length=524288)]

    @field_validator("data_base64")
    @classmethod
    def valid_bounded_base64(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("audio data is not valid base64") from error
        if not decoded or len(decoded) > 384 * 1024:
            raise ValueError("decoded audio chunk size is invalid")
        return value

    def decoded_data(self) -> bytes:
        return base64.b64decode(self.data_base64, validate=True)


class AudioInputEndPayload(ClosedPayload):
    audio_stream_id: UUID
    reason: Literal["vad_end", "barge_in", "client_stop", "disconnect"]


class ApprovalResponsePayload(ClosedPayload):
    approval_id: UUID
    decision: Literal["approve", "reject"]
    arguments_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    reason: Annotated[str | None, Field(max_length=2048)] = None


class OperationCancelPayload(ClosedPayload):
    target_kind: Literal[
        "assistant_response",
        "tool_execution",
        "agent_task",
        "model_switch",
    ]
    target_id: UUID
    reason: Literal[
        "user_request",
        "barge_in",
        "app_background",
        "session_closing",
    ]
    idempotency_key: UUID


class ClientErrorPayload(ClosedPayload):
    error_code: Annotated[str, Field(min_length=1, max_length=128)]
    message: Annotated[str, Field(max_length=4096)]
    component: Annotated[str, Field(max_length=128)]
    retryable: bool
    evidence_id: Annotated[str | None, Field(max_length=256)] = None


ClientPayload = (
    AudioInputStartPayload
    | AudioInputChunkPayload
    | AudioInputEndPayload
    | ApprovalResponsePayload
    | OperationCancelPayload
    | ClientErrorPayload
)

_PAYLOAD_TYPES: dict[str, type[ClosedPayload]] = {
    "audio.input.start": AudioInputStartPayload,
    "audio.input.chunk": AudioInputChunkPayload,
    "audio.input.end": AudioInputEndPayload,
    "tool.approval.response": ApprovalResponsePayload,
    "operation.cancel.requested": OperationCancelPayload,
    "error": ClientErrorPayload,
}


def validate_client_payload(event_type: str, value: dict[str, Any]) -> ClientPayload:
    payload_type = _PAYLOAD_TYPES.get(event_type)
    if payload_type is None:
        raise ValueError("unsupported client event type")
    return payload_type.model_validate(value)
