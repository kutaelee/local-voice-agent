import asyncio
from uuid import uuid4

import pytest

from local_voice_agent_server.application.voice_turn import (
    SynthesizedAudio,
    Transcript,
    VoiceActivityDecision,
    VoiceTurnService,
    _crossfade_pcm16_boundary,
    _hold_pcm16_boundary,
    _take_complete_speech_units,
)


def test_streaming_speech_splits_a_long_clause_at_a_comma() -> None:
    clause = "이 답변은 첫 음성을 더 빠르게 들려주기 위해 충분히 긴 자연스러운 구간에서 나눕니다,"
    ready, pending = _take_complete_speech_units(
        clause + " 다음 구간은 아직 생성 중입니다"
    )

    assert ready == (clause,)
    assert pending == "다음 구간은 아직 생성 중입니다"


def test_short_comma_does_not_fragment_streaming_speech() -> None:
    ready, pending = _take_complete_speech_units("네, 바로 확인하겠습니다")

    assert ready == ()
    assert pending == "네, 바로 확인하겠습니다"


def test_short_first_sentence_is_coalesced_to_avoid_playback_gap() -> None:
    ready, pending = _take_complete_speech_units(
        "Okay. The next sentence has enough audio to cover synthesis. "
    )

    assert ready == (
        "Okay. The next sentence has enough audio to cover synthesis.",
    )
    assert pending == ""


def test_short_korean_apology_is_coalesced_with_following_sentence() -> None:
    ready, pending = _take_complete_speech_units(
        "죄송합니다. 바로 다시 확인하겠습니다. "
    )

    assert ready == ("죄송합니다. 바로 다시 확인하겠습니다.",)
    assert pending == ""


def test_pcm_boundary_hold_and_crossfade_preserve_order_without_a_gap() -> None:
    previous = b"".join(
        int(1_000).to_bytes(2, "little", signed=True) for _ in range(100)
    )
    current = b"".join(
        int(-1_000).to_bytes(2, "little", signed=True) for _ in range(100)
    )

    body, held = _hold_pcm16_boundary(
        previous,
        sample_rate_hz=1_000,
        channels=1,
    )
    transition, remainder = _crossfade_pcm16_boundary(
        held,
        current,
        sample_rate_hz=1_000,
        channels=1,
    )

    assert len(body) == 75 * 2
    assert len(held) == 25 * 2
    assert len(transition) == 25 * 2
    assert len(remainder) == 75 * 2
    transition_samples = [
        int.from_bytes(transition[index : index + 2], "little", signed=True)
        for index in range(0, len(transition), 2)
    ]
    assert transition_samples[0] > 0
    assert transition_samples[-1] < 0


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
        encoding="pcm_s16le",
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


def test_voice_turn_emits_first_sentence_audio_before_synthesizing_next() -> None:
    timeline: list[str] = []

    class SentenceConversation:
        async def respond(self, text: str, *, language: str) -> str:
            assert text
            assert language == "ko"
            return "첫 문장입니다. 두 번째 문장입니다."

    class SentenceTts:
        async def synthesize(
            self,
            text: str,
            *,
            language: str,
        ) -> SynthesizedAudio:
            assert language == "ko"
            timeline.append(f"tts:{text}")
            return SynthesizedAudio(
                text.encode("utf-8") * 8,
                sample_rate_hz=24_000,
            )

    async def scenario() -> None:
        service = VoiceTurnService(
            stt=FakeStt(),
            conversation=SentenceConversation(),
            tts=SentenceTts(),
            output_chunk_bytes=32,
        )
        stream_id = uuid4()
        service.start(
            stream_id=stream_id,
            encoding="pcm_s16le",
            sample_rate_hz=16_000,
            channels=1,
        )
        service.append(
            stream_id=stream_id,
            chunk_index=0,
            encoding="pcm_s16le",
            data=b"\x00\x00" * 160,
            duration_ms=10,
        )
        emitted = []

        async def emit(event) -> None:
            emitted.append(event)
            timeline.append(f"event:{event.type}")

        returned = await service.finish(stream_id=stream_id, emit=emit)
        assert returned == []
        assert [item for item in timeline if item.startswith("tts:")] == [
            "tts:첫 문장입니다.",
            "tts:두 번째 문장입니다.",
        ]
        assert timeline.index("event:audio.output.chunk") < timeline.index(
            "tts:두 번째 문장입니다."
        )
        chunks = [
            event
            for event in emitted
            if event.type == "audio.output.chunk"
        ]
        assert [event.payload["chunk_index"] for event in chunks] == list(
            range(len(chunks))
        )
        assert len(
            {event.payload["audio_stream_id"] for event in chunks}
        ) == 1
        assert emitted[-1].type == "audio.output.end"
        assert emitted[-1].payload["reason"] == "completed"

    asyncio.run(scenario())


def test_streamed_tts_failure_terminates_the_open_audio_stream() -> None:
    class SentenceConversation:
        async def respond(self, text: str, *, language: str) -> str:
            del text, language
            return "첫 문장입니다. 두 번째 문장입니다."

    class FailingSecondTts:
        calls = 0

        async def synthesize(
            self,
            text: str,
            *,
            language: str,
        ) -> SynthesizedAudio:
            del text, language
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("synthetic TTS failure")
            return SynthesizedAudio(b"\x00\x01" * 32, 24_000)

    async def scenario() -> None:
        service = VoiceTurnService(
            stt=FakeStt(),
            conversation=SentenceConversation(),
            tts=FailingSecondTts(),
        )
        stream_id = uuid4()
        service.start(
            stream_id=stream_id,
            encoding="pcm_s16le",
            sample_rate_hz=16_000,
            channels=1,
        )
        service.append(
            stream_id=stream_id,
            chunk_index=0,
            encoding="pcm_s16le",
            data=b"\x00\x00" * 160,
            duration_ms=10,
        )
        emitted = []

        async def emit(event) -> None:
            emitted.append(event)

        with pytest.raises(RuntimeError, match="synthetic TTS failure"):
            await service.finish(stream_id=stream_id, emit=emit)
        assert emitted[-1].type == "audio.output.end"
        assert emitted[-1].payload["reason"] == "error"

    asyncio.run(scenario())


def test_streamed_llm_continues_while_first_audio_is_synthesized() -> None:
    timeline: list[str] = []

    class StreamingConversation:
        async def respond(self, text: str, *, language: str) -> str:
            del text, language
            raise AssertionError("streaming path must not call respond")

        async def stream(self, text: str, *, language: str):
            assert text
            assert language == "ko"
            yield "첫 번째 설명은 충분히 길어서 먼저 음성으로 재생됩니다. "
            yield "두 번째 "
            yield "문장입니다."

    class StreamingTts:
        async def synthesize(
            self,
            text: str,
            *,
            language: str,
        ) -> SynthesizedAudio:
            assert language == "ko"
            timeline.append(f"tts:{text}")
            return SynthesizedAudio(
                text.encode("utf-8") * 4,
                sample_rate_hz=24_000,
            )

    async def scenario() -> None:
        service = VoiceTurnService(
            stt=FakeStt(),
            conversation=StreamingConversation(),
            tts=StreamingTts(),
            output_chunk_bytes=32,
        )
        stream_id = uuid4()
        service.start(
            stream_id=stream_id,
            encoding="pcm_s16le",
            sample_rate_hz=16_000,
            channels=1,
        )
        service.append(
            stream_id=stream_id,
            chunk_index=0,
            encoding="pcm_s16le",
            data=b"\x00\x00" * 160,
            duration_ms=10,
        )
        emitted = []

        async def emit(event) -> None:
            emitted.append(event)
            suffix = (
                f":{event.payload['text']}"
                if event.type == "assistant.text.delta"
                else ""
            )
            timeline.append(f"event:{event.type}{suffix}")

        assert await service.finish(stream_id=stream_id, emit=emit) == []
        assert timeline.index("event:audio.output.chunk") > timeline.index(
            "event:assistant.text.delta:두 번째 "
        )
        assert [
            event.payload["text"]
            for event in emitted
            if event.type == "assistant.text.delta"
        ] == [
            "첫 번째 설명은 충분히 길어서 먼저 음성으로 재생됩니다. ",
            "두 번째 ",
            "문장입니다.",
        ]
        final = next(
            event
            for event in emitted
            if event.type == "assistant.text.final"
        )
        assert (
            final.payload["text"]
            == "첫 번째 설명은 충분히 길어서 먼저 음성으로 재생됩니다. 두 번째 문장입니다."
        )
        assert [item for item in timeline if item.startswith("tts:")] == [
            "tts:첫 번째 설명은 충분히 길어서 먼저 음성으로 재생됩니다.",
            "tts:두 번째 문장입니다.",
        ]
        assert emitted[-1].type == "audio.output.end"
        assert emitted[-1].payload["reason"] == "completed"

    asyncio.run(scenario())


def test_voice_turn_emits_vad_end_and_closes_worker_state() -> None:
    class FakeVad:
        closed = False

        async def analyze(self, **_: object) -> VoiceActivityDecision:
            return VoiceActivityDecision(
                speech_started=True,
                end_of_speech=True,
                probability=0.88,
                processed_ms=640,
            )

        async def close(self, **_: object) -> None:
            self.closed = True

    async def scenario() -> None:
        vad = FakeVad()
        service = VoiceTurnService(
            stt=FakeStt(),
            conversation=FakeConversation(),
            tts=FakeTts(),
            vad=vad,
        )
        stream_id = uuid4()
        service.start(
            stream_id=stream_id,
            encoding="pcm_s16le",
            sample_rate_hz=16_000,
            channels=1,
        )
        events = await service.append_with_vad(
            stream_id=stream_id,
            chunk_index=0,
            encoding="pcm_s16le",
            data=b"\x00\x00" * 160,
            duration_ms=10,
        )
        assert events[0].payload == {
            "state": "recognizing",
            "detail": "vad_end_detected",
        }
        await service.finish(stream_id=stream_id)
        assert vad.closed is True

    asyncio.run(scenario())
