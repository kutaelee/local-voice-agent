import asyncio
import base64

from local_voice_agent_server.application.salon_speech import SalonSpeechService
from local_voice_agent_server.application.voice_turn import SynthesizedAudio


class FakeTts:
    def __init__(self) -> None:
        self.requests = []

    async def synthesize(self, text: str, *, language: str) -> SynthesizedAudio:
        self.requests.append((text, language))
        return SynthesizedAudio(
            pcm_s16le=(1000).to_bytes(2, "little", signed=True) * 240,
            sample_rate_hz=24_000,
            channels=1,
        )


def test_salon_speech_emits_one_ordered_stream_with_natural_tail() -> None:
    tts = FakeTts()
    service = SalonSpeechService(
        tts=tts,
        output_chunk_bytes=128,
        release_fade_ms=24,
        final_silence_ms=200,
    )

    events = asyncio.run(
        service.synthesize(
            "예약이 확정됐습니다.",
            resume_state="listening",
        )
    )

    assert tts.requests == [("예약이 확정됐습니다…", "ko")]
    assert events[0].payload == {"state": "synthesizing"}
    assert events[1].payload == {"state": "speaking"}
    chunks = [event for event in events if event.type == "audio.output.chunk"]
    assert len(chunks) > 1
    assert [event.payload["chunk_index"] for event in chunks] == list(
        range(len(chunks))
    )
    assert len({event.payload["audio_stream_id"] for event in chunks}) == 1
    pcm = b"".join(
        base64.b64decode(str(event.payload["data_base64"])) for event in chunks
    )
    assert pcm.endswith(b"\x00" * (24_000 * 2 * 200 // 1_000))
    assert events[-2].type == "audio.output.end"
    assert events[-2].payload["reason"] == "completed"
    assert events[-1].payload == {"state": "listening"}


def test_salon_speech_can_resume_idle_after_hangup() -> None:
    service = SalonSpeechService(tts=FakeTts())

    events = asyncio.run(service.synthesize("감사합니다.", resume_state="idle"))

    assert events[-1].type == "assistant.state"
    assert events[-1].payload == {"state": "idle"}


def test_salon_speech_keeps_normal_two_sentence_reply_in_one_generation() -> None:
    tts = FakeTts()
    service = SalonSpeechService(tts=tts)

    asyncio.run(
        service.synthesize(
            "안녕하세요, 윤슬 헤어 예약 도우미 수아입니다. "
            "예약, 변경, 취소, 시술 가격과 영업시간을 도와드릴게요."
        )
    )

    assert len(tts.requests) == 1
    assert "수아입니다" in tts.requests[0][0]
    assert "도와드릴게요" in tts.requests[0][0]


def test_salon_speech_streams_first_unit_before_synthesizing_the_next() -> None:
    tts = FakeTts()
    service = SalonSpeechService(
        tts=tts,
        output_chunk_bytes=1_024,
        release_fade_ms=8,
        unit_silence_ms=80,
        final_silence_ms=260,
    )
    emitted = []

    async def scenario() -> None:
        async def emit(event) -> None:
            emitted.append(event)

        await service.synthesize(
                (
                    "다음 주 화요일은 오전 열 시부터 예약하실 수 있어요. "
                    "원하시는 시간을 말씀해 주시면 바로 확인해 드릴게요. "
                    "담당 디자이너를 지정하시면 가능한 시간도 함께 안내해 드립니다."
                ),
            emit=emit,
        )

    asyncio.run(scenario())

    assert len(tts.requests) >= 2
    first_audio = next(
        index
        for index, event in enumerate(emitted)
        if event.type == "audio.output.chunk"
    )
    assert first_audio > 0
    assert emitted[first_audio].payload["chunk_index"] == 0
    assert emitted[-2].type == "audio.output.end"


def test_salon_speech_forwards_streamed_pcm_before_generation_finishes() -> None:
    timeline = []

    class StreamingTts:
        async def synthesize(self, text: str, *, language: str):
            raise AssertionError("streaming path should be selected")

        async def stream_synthesize(self, text: str, *, language: str):
            assert text
            assert language == "ko"
            timeline.append("tts:first")
            yield SynthesizedAudio(
                pcm_s16le=(1000).to_bytes(2, "little", signed=True) * 2_000,
                sample_rate_hz=24_000,
                channels=1,
            )
            timeline.append("tts:second")
            yield SynthesizedAudio(
                pcm_s16le=(500).to_bytes(2, "little", signed=True) * 2_000,
                sample_rate_hz=24_000,
                channels=1,
            )

    service = SalonSpeechService(
        tts=StreamingTts(),
        output_chunk_bytes=1_024,
        release_fade_ms=24,
    )

    async def scenario() -> None:
        async def emit(event) -> None:
            if event.type == "audio.output.chunk":
                timeline.append("client:audio")

        await service.synthesize("바로 확인해 드리겠습니다.", emit=emit)

    asyncio.run(scenario())

    assert timeline.index("client:audio") < timeline.index("tts:second")
