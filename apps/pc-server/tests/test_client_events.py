from __future__ import annotations

import base64
from uuid import uuid4

import pytest
from pydantic import ValidationError

from local_voice_agent_server.protocol.client_events import (
    AudioInputChunkPayload,
    SalonCallMessagePayload,
    validate_client_payload,
)


def test_audio_chunk_decodes_strict_base64() -> None:
    raw = b"\x00\x01" * 160
    payload = validate_client_payload(
        "audio.input.chunk",
        {
            "audio_stream_id": str(uuid4()),
            "chunk_index": 0,
            "encoding": "pcm_s16le",
            "duration_ms": 20,
            "data_base64": base64.b64encode(raw).decode("ascii"),
        },
    )
    assert isinstance(payload, AudioInputChunkPayload)
    assert payload.decoded_data() == raw


@pytest.mark.parametrize(
    "data_base64",
    ["not base64!", "", base64.b64encode(b"x" * (384 * 1024 + 1)).decode()],
)
def test_audio_chunk_rejects_invalid_or_oversized_data(data_base64: str) -> None:
    with pytest.raises(ValidationError):
        validate_client_payload(
            "audio.input.chunk",
            {
                "audio_stream_id": str(uuid4()),
                "chunk_index": 0,
                "encoding": "pcm_s16le",
                "duration_ms": 20,
                "data_base64": data_base64,
            },
        )


def test_payload_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        validate_client_payload(
            "audio.input.start",
            {
                "audio_stream_id": str(uuid4()),
                "encoding": "pcm_s16le",
                "sample_rate_hz": 16000,
                "channels": 1,
                "extra": True,
            },
        )


def test_salon_call_message_is_closed_and_bounded() -> None:
    payload = validate_client_payload(
        "salon.call.message",
        {"text": "내일 오후 2시에 커트 예약하고 싶어요"},
    )
    assert isinstance(payload, SalonCallMessagePayload)

    with pytest.raises(ValidationError):
        validate_client_payload(
            "salon.call.message",
            {"text": "예약", "unexpected": True},
        )
    with pytest.raises(ValidationError):
        validate_client_payload(
            "salon.call.message",
            {"text": "x" * 2001},
        )
