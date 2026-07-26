import asyncio
from pathlib import Path

import pytest

from local_voice_agent_server.infrastructure.vllm_omni_tts import (
    VllmOmniTtsAdapter,
    VllmOmniTtsError,
)
from local_voice_agent_server.infrastructure.voice_profiles import (
    VoiceSynthesisOptions,
)


def test_vllm_omni_tts_streams_pcm_and_normalizes_korean_language() -> None:
    payloads = []

    def transport(payload):
        payloads.append(payload)
        return iter((b"\x01\x02" * 4, b"\x03\x04" * 2))

    adapter = VllmOmniTtsAdapter(
        base_url="http://127.0.0.1:46329",
        voice="registered-voice",
        stream_transport=transport,
    )

    async def collect():
        return [
            item
            async for item in adapter.stream_synthesize(
                "  확인해   보겠습니다. ",
                language="ko",
            )
        ]

    chunks = asyncio.run(collect())

    assert [item.pcm_s16le for item in chunks] == [
        b"\x01\x02" * 4,
        b"\x03\x04" * 2,
    ]
    assert payloads == [
        {
            "input": "확인해 보겠습니다.",
            "voice": "registered-voice",
            "language": "Korean",
            "task_type": "Base",
            "response_format": "pcm",
            "stream": True,
            "stream_format": "audio",
            "max_new_tokens": 160,
        }
    ]


def test_vllm_omni_tts_rejects_non_loopback_and_truncated_pcm() -> None:
    with pytest.raises(ValueError):
        VllmOmniTtsAdapter(
            base_url="http://192.168.0.10:46329",
            voice="registered-voice",
        )

    adapter = VllmOmniTtsAdapter(
        base_url="http://localhost:46329",
        voice="registered-voice",
        stream_transport=lambda _: iter((b"\x00",)),
    )

    async def collect() -> None:
        async for _ in adapter.stream_synthesize("테스트입니다.", language="ko"):
            pass

    with pytest.raises(VllmOmniTtsError, match="truncated"):
        asyncio.run(collect())


def test_vllm_omni_tts_reassembles_network_chunks_on_pcm_boundaries() -> None:
    adapter = VllmOmniTtsAdapter(
        base_url="http://localhost:46329",
        voice="registered-voice",
        stream_transport=lambda _: iter((b"\x01", b"\x02\x03", b"\x04")),
    )

    async def collect():
        return [
            item.pcm_s16le
            async for item in adapter.stream_synthesize(
                "테스트입니다.",
                language="ko",
            )
        ]

    assert asyncio.run(collect()) == [b"\x01\x02", b"\x03\x04"]


def test_vllm_omni_tts_uses_registered_custom_profile_voice(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF-reference")
    payloads = []

    adapter = VllmOmniTtsAdapter(
        base_url="http://localhost:46329",
        voice="fallback-voice",
        stream_transport=lambda payload: (
            payloads.append(payload) or iter((b"\x01\x02",))
        ),
        options_provider=lambda _: VoiceSynthesisOptions(
            profile_id="selected-profile",
            reference_audio_path=reference,
            exaggeration=0.5,
            cfg_weight=0.5,
            temperature=0.8,
            reference_text="선택한 목소리의 참조 대사입니다.",
            style="neutral",
        ),
    )

    async def collect() -> list[bytes]:
        return [
            chunk.pcm_s16le
            async for chunk in adapter.stream_synthesize(
                "테스트입니다.",
                language="ko",
            )
        ]

    assert asyncio.run(collect()) == [b"\x01\x02"]
    assert payloads[0]["voice"] == "lva-selected-profile"
    assert "ref_audio" not in payloads[0]
    assert "ref_text" not in payloads[0]
