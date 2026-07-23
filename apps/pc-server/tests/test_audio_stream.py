from uuid import uuid4

import pytest

from local_voice_agent_server.domain.audio_stream import (
    AudioStream,
    AudioStreamError,
    AudioStreamState,
)


def test_ordered_pcm_stream_finishes_with_exact_bytes() -> None:
    stream_id = uuid4()
    stream = AudioStream(max_bytes=16)
    stream.start(
        stream_id=stream_id,
        encoding="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
    )
    stream.append(
        stream_id=stream_id,
        chunk_index=0,
        data=b"\x01\x02",
        duration_ms=20,
    )
    stream.append(
        stream_id=stream_id,
        chunk_index=1,
        data=b"\x03\x04",
        duration_ms=20,
    )

    assert stream.finish(stream_id=stream_id) == b"\x01\x02\x03\x04"
    assert stream.state is AudioStreamState.COMPLETED
    assert stream.duration_ms == 40


@pytest.mark.parametrize(
    ("action", "message"),
    [
        ("out_of_order", "out of order"),
        ("wrong_id", "does not match"),
        ("too_large", "byte limit"),
    ],
)
def test_stream_rejects_contract_violations(action: str, message: str) -> None:
    stream_id = uuid4()
    stream = AudioStream(max_bytes=2)
    stream.start(
        stream_id=stream_id,
        encoding="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
    )

    with pytest.raises(AudioStreamError, match=message):
        if action == "out_of_order":
            stream.append(
                stream_id=stream_id,
                chunk_index=1,
                data=b"\x00\x00",
                duration_ms=20,
            )
        elif action == "wrong_id":
            stream.append(
                stream_id=uuid4(),
                chunk_index=0,
                data=b"\x00\x00",
                duration_ms=20,
            )
        else:
            stream.append(
                stream_id=stream_id,
                chunk_index=0,
                data=b"\x00\x00\x00",
                duration_ms=20,
            )


def test_cancel_discards_buffer_and_is_terminal() -> None:
    stream_id = uuid4()
    stream = AudioStream()
    stream.start(
        stream_id=stream_id,
        encoding="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
    )
    stream.append(
        stream_id=stream_id,
        chunk_index=0,
        data=b"\x00\x00",
        duration_ms=20,
    )
    stream.cancel(stream_id=stream_id)

    assert stream.state is AudioStreamState.CANCELLED
    assert stream.size_bytes == 0
    with pytest.raises(AudioStreamError, match="no audio stream"):
        stream.append(
            stream_id=stream_id,
            chunk_index=1,
            data=b"\x00\x00",
            duration_ms=20,
        )
