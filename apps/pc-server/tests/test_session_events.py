from __future__ import annotations

import asyncio
import base64
from uuid import uuid4

from local_voice_agent_server.application.session_events import (
    VoiceSessionEventHandler,
)
from local_voice_agent_server.application.voice_turn import (
    SynthesizedAudio,
    Transcript,
    VoiceTurnService,
)
from local_voice_agent_server.protocol.client_events import (
    validate_client_payload,
)


class FakeStt:
    async def transcribe(self, audio: bytes, **_: object) -> Transcript:
        assert audio == b"\x00\x01" * 160
        return Transcript("테스트입니다.", "ko", 0.9)


class FakeConversation:
    async def respond(self, text: str, **_: object) -> str:
        assert text == "테스트입니다."
        return "확인했습니다."


class FakeTts:
    async def synthesize(self, text: str, **_: object) -> SynthesizedAudio:
        assert text == "확인했습니다."
        return SynthesizedAudio(b"\x00\x00" * 120, 24_000)


def factory() -> VoiceTurnService:
    return VoiceTurnService(
        stt=FakeStt(),
        conversation=FakeConversation(),
        tts=FakeTts(),
    )


def test_voice_session_routes_complete_turn_and_releases_session() -> None:
    async def scenario() -> None:
        handler = VoiceSessionEventHandler(factory)
        session_id = uuid4()
        request_id = uuid4()
        stream_id = uuid4()
        started = await handler.handle(
            session_id=session_id,
            request_id=request_id,
            event_type="audio.input.start",
            payload=validate_client_payload(
                "audio.input.start",
                {
                    "audio_stream_id": str(stream_id),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16000,
                    "channels": 1,
                },
            ),
        )
        assert [event.type for event in started] == ["assistant.state"]
        chunked = await handler.handle(
            session_id=session_id,
            request_id=request_id,
            event_type="audio.input.chunk",
            payload=validate_client_payload(
                "audio.input.chunk",
                {
                    "audio_stream_id": str(stream_id),
                    "chunk_index": 0,
                    "encoding": "pcm_s16le",
                    "duration_ms": 20,
                    "data_base64": base64.b64encode(b"\x00\x01" * 160).decode(),
                },
            ),
        )
        assert chunked == []
        completed = await handler.handle(
            session_id=session_id,
            request_id=request_id,
            event_type="audio.input.end",
            payload=validate_client_payload(
                "audio.input.end",
                {
                    "audio_stream_id": str(stream_id),
                    "reason": "vad_end",
                },
            ),
        )
        assert completed[-1].type == "audio.output.end"

        restarted = await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.start",
            payload=validate_client_payload(
                "audio.input.start",
                {
                    "audio_stream_id": str(uuid4()),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16000,
                    "channels": 1,
                },
            ),
        )
        assert restarted[0].payload["state"] == "listening"

    asyncio.run(scenario())


def test_barge_in_cancels_active_capture() -> None:
    async def scenario() -> None:
        handler = VoiceSessionEventHandler(factory)
        session_id = uuid4()
        stream_id = uuid4()
        await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.start",
            payload=validate_client_payload(
                "audio.input.start",
                {
                    "audio_stream_id": str(stream_id),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16000,
                    "channels": 1,
                },
            ),
        )
        result = await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.end",
            payload=validate_client_payload(
                "audio.input.end",
                {
                    "audio_stream_id": str(stream_id),
                    "reason": "barge_in",
                },
            ),
        )
        assert result[0].payload["state"] == "interrupted"

    asyncio.run(scenario())
