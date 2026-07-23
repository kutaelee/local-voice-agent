import asyncio
from uuid import uuid4

from local_voice_agent_server.application.voice_turn import (
    SynthesizedAudio,
    Transcript,
    VoiceTurnService,
)


class FakeStt:
    async def transcribe(
        self,
        audio: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
    ) -> Transcript:
        assert audio == b"\x00\x00" * 160
        assert sample_rate_hz == 16_000
        assert channels == 1
        return Transcript("컴퓨터 상태 알려줘.", "ko", 0.9)


class FakeConversation:
    async def respond(self, text: str, *, language: str) -> str:
        assert text == "컴퓨터 상태 알려줘."
        assert language == "ko"
        return "현재 상태를 확인하겠습니다."


class FakeTts:
    async def synthesize(self, text: str, *, language: str) -> SynthesizedAudio:
        assert text == "현재 상태를 확인하겠습니다."
        assert language == "ko"
        return SynthesizedAudio(b"\x01\x02" * 100, sample_rate_hz=24_000)


def test_voice_turn_emits_ordered_transcript_text_and_audio() -> None:
    service = VoiceTurnService(
        stt=FakeStt(),
        conversation=FakeConversation(),
        tts=FakeTts(),
        output_chunk_bytes=64,
    )
    stream_id = uuid4()

    start = service.start(
        stream_id=stream_id,
        encoding="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
    )
    service.append(
        stream_id=stream_id,
        chunk_index=0,
        data=b"\x00\x00" * 160,
        duration_ms=10,
    )
    completed = asyncio.run(service.finish(stream_id=stream_id))

    types = [event.type for event in start + completed]
    assert types[:6] == [
        "assistant.state",
        "assistant.state",
        "transcript.user.final",
        "assistant.state",
        "assistant.text.final",
        "assistant.state",
    ]
    assert types.count("audio.output.chunk") == 4
    first_audio = next(
        event for event in completed if event.type == "audio.output.chunk"
    )
    assert first_audio.payload["sample_rate_hz"] == 24_000
    assert first_audio.payload["channels"] == 1
    assert types[-1] == "audio.output.end"
    assert completed[1].payload["text"] == "컴퓨터 상태 알려줘."
