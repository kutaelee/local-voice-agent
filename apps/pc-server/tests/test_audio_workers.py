from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest

from local_voice_agent_server.infrastructure.audio_workers import (
    AudioWorkerError,
    SttWorkerAdapter,
    TtsWorkerAdapter,
    UnixJsonWorkerClient,
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
