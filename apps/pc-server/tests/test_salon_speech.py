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

    assert tts.requests == [("예약이 확정됐습니다.", "ko")]
    assert events[0].type == "assistant.state"
    assert events[0].payload["state"] == "speaking"
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
