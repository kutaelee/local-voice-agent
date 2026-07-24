from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from uuid import uuid4

import pytest

from local_voice_agent_server.infrastructure import audio_workers
from local_voice_agent_server.infrastructure.audio_workers import (
    AudioWorkerError,
    SttWorkerAdapter,
    TtsWorkerAdapter,
    UnixJsonWorkerClient,
    VadWorkerAdapter,
)
from local_voice_agent_server.infrastructure.voice_profiles import (
    VoiceSynthesisOptions,
)


TOKEN = "test-only-audio-worker-token-32-chars"


async def run_server(
    path: Path,
    response: dict[str, object],
) -> asyncio.AbstractServer:
    async def handler(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        request = json.loads(await reader.readline())
        assert request["token"] == TOKEN
        writer.write(json.dumps(response).encode() + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    return await asyncio.start_unix_server(handler, path=path)


def test_stt_and_tts_worker_adapters(tmp_path: Path) -> None:
    async def scenario() -> None:
        stt_path = tmp_path / "stt.sock"
        stt_server = await run_server(
            stt_path,
            {
                "status": "ok",
                "text": "안녕하세요.",
                "language": "ko",
                "confidence": 0.98,
            },
        )
        async with stt_server:
            adapter = SttWorkerAdapter(
                UnixJsonWorkerClient(
                    socket_path=stt_path,
                    token=TOKEN,
                    timeout_seconds=2,
                )
            )
            transcript = await adapter.transcribe(
                b"\x00\x00" * 160,
                sample_rate_hz=16000,
                channels=1,
            )
        assert transcript.text == "안녕하세요."

        tts_path = tmp_path / "tts.sock"
        tts_server = await run_server(
            tts_path,
            {
                "status": "ok",
                "pcm_base64": base64.b64encode(b"\x00\x01" * 120).decode(),
                "sample_rate_hz": 24000,
                "channels": 1,
            },
        )
        async with tts_server:
            adapter = TtsWorkerAdapter(
                UnixJsonWorkerClient(
                    socket_path=tts_path,
                    token=TOKEN,
                    timeout_seconds=2,
                )
            )
            audio = await adapter.synthesize("안녕하세요.", language="ko")
        assert audio.sample_rate_hz == 24000
        assert len(audio.pcm_s16le) == 240

    asyncio.run(scenario())


def test_tts_adapter_sends_selected_voice_controls(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "tts-profile.sock"
        reference = tmp_path / "reference.wav"
        reference.write_bytes(b"RIFF")
        observed: dict[str, object] = {}

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            observed.update(json.loads(await reader.readline()))
            writer.write(
                json.dumps(
                    {
                        "status": "ok",
                        "pcm_base64": base64.b64encode(b"\x00\x00").decode(),
                        "sample_rate_hz": 24_000,
                        "channels": 1,
                    }
                ).encode()
                + b"\n"
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(handler, path=path)
        async with server:
            adapter = TtsWorkerAdapter(
                UnixJsonWorkerClient(
                    socket_path=path,
                    token=TOKEN,
                    timeout_seconds=2,
                ),
                options_provider=lambda _: VoiceSynthesisOptions(
                    profile_id="83c1f58c-052d-449d-a598-db0c19023b08",
                    reference_audio_path=reference,
                    exaggeration=0.5,
                    cfg_weight=0.5,
                    temperature=0.8,
                    reference_text="테스트 참조 문장입니다.",
                    style="neutral",
                ),
            )
            await adapter.synthesize("테스트", language="ko")

        assert observed["voice_profile_id"] == (
            "83c1f58c-052d-449d-a598-db0c19023b08"
        )
        assert observed["audio_prompt_path"] == str(reference)
        assert observed["exaggeration"] == 0.5
        assert observed["cfg_weight"] == 0.5
        assert observed["temperature"] == 0.8
        assert observed["reference_text"] == "테스트 참조 문장입니다."
        assert observed["style"] == "neutral"

    asyncio.run(scenario())


def test_worker_error_is_sanitized(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "worker.sock"
        server = await run_server(
            path,
            {"status": "error", "error_code": "REQUEST_INVALID"},
        )
        async with server:
            client = UnixJsonWorkerClient(
                socket_path=path,
                token=TOKEN,
                timeout_seconds=2,
            )
            with pytest.raises(AudioWorkerError, match="REQUEST_INVALID"):
                await client.request({"operation": "health", "request_id": "x"})

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("adapter_kind", "operation"),
    (("stt", "transcribe"), ("tts", "synthesize")),
)
def test_stt_and_tts_timeout_preserve_no_fabricated_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapter_kind: str,
    operation: str,
) -> None:
    async def never_connect(*_: object, **__: object) -> object:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(
        audio_workers.asyncio,
        "open_unix_connection",
        never_connect,
    )
    client = UnixJsonWorkerClient(
        socket_path=tmp_path / f"{adapter_kind}.sock",
        token=TOKEN,
        timeout_seconds=1,
    )
    client._timeout_seconds = 0.01

    async def scenario() -> None:
        with pytest.raises(AudioWorkerError, match="connection failed"):
            if operation == "transcribe":
                await SttWorkerAdapter(client).transcribe(
                    b"\x00\x00" * 160,
                    sample_rate_hz=16_000,
                    channels=1,
                )
            else:
                await TtsWorkerAdapter(client).synthesize(
                    "timeout",
                    language="ko",
                )

    asyncio.run(scenario())


def test_vad_worker_adapter_analyzes_and_closes_stream(tmp_path: Path) -> None:
    async def scenario() -> None:
        stream_id = uuid4()
        path = tmp_path / "vad.sock"
        responses = [
            {
                "status": "ok",
                "speech_started": True,
                "end_of_speech": True,
                "probability": 0.91,
                "processed_ms": 640,
            },
            {
                "status": "ok",
                "closed": True,
            },
        ]

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            request = json.loads(await reader.readline())
            assert request["token"] == TOKEN
            writer.write(json.dumps(responses.pop(0)).encode() + b"\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(handler, path=path)
        async with server:
            adapter = VadWorkerAdapter(
                UnixJsonWorkerClient(
                    socket_path=path,
                    token=TOKEN,
                    timeout_seconds=2,
                )
            )
            decision = await adapter.analyze(
                stream_id=stream_id,
                pcm_s16le=b"\x00\x01" * 512,
                sample_rate_hz=16_000,
                channels=1,
            )
            await adapter.close(stream_id=stream_id)
        assert decision.speech_started is True
        assert decision.end_of_speech is True
        assert decision.probability == 0.91
        assert decision.processed_ms == 640

    asyncio.run(scenario())
