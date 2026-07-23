"""Adapters for isolated STT and TTS Unix-socket worker processes."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from uuid import UUID, uuid4

from ..application.voice_turn import (
    SynthesizedAudio,
    Transcript,
    VoiceActivityDecision,
)


class AudioWorkerError(RuntimeError):
    pass


class UnixJsonWorkerClient:
    def __init__(
        self,
        *,
        socket_path: Path,
        token: str,
        timeout_seconds: float,
        max_response_bytes: int = 24 * 1024 * 1024,
    ) -> None:
        if not socket_path.is_absolute():
            raise ValueError("worker socket path must be absolute")
        if len(token) < 32:
            raise ValueError("worker token must contain at least 32 characters")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("worker timeout is invalid")
        self._socket_path = socket_path
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    async def request(self, payload: dict[str, object]) -> dict[str, object]:
        frame = json.dumps(
            {**payload, "token": self._token},
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        if len(frame) > 12 * 1024 * 1024:
            raise AudioWorkerError("worker request is too large")

        async def exchange() -> dict[str, object]:
            reader, writer = await asyncio.open_unix_connection(
                self._socket_path,
                limit=self._max_response_bytes + 1,
            )
            try:
                writer.write(frame)
                await writer.drain()
                raw = await reader.readline()
            finally:
                writer.close()
                await writer.wait_closed()
            if not raw or len(raw) > self._max_response_bytes:
                raise AudioWorkerError("worker response is invalid")
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get("status") != "ok":
                raise AudioWorkerError(
                    f"worker failed: {value.get('error_code', 'UNKNOWN')}"
                )
            return value

        try:
            return await asyncio.wait_for(exchange(), timeout=self._timeout_seconds)
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            raise AudioWorkerError("worker connection failed") from error


class SttWorkerAdapter:
    def __init__(self, client: UnixJsonWorkerClient) -> None:
        self._client = client

    async def transcribe(
        self,
        audio: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
    ) -> Transcript:
        response = await self._client.request(
            {
                "operation": "transcribe",
                "request_id": str(uuid4()),
                "audio_base64": base64.b64encode(audio).decode("ascii"),
                "sample_rate_hz": sample_rate_hz,
                "channels": channels,
            }
        )
        return Transcript(
            text=str(response["text"]),
            language=str(response["language"]),
            confidence=float(response["confidence"]),
        )


class VadWorkerAdapter:
    def __init__(self, client: UnixJsonWorkerClient) -> None:
        self._client = client

    async def analyze(
        self,
        *,
        stream_id: UUID,
        pcm_s16le: bytes,
        sample_rate_hz: int,
        channels: int,
    ) -> VoiceActivityDecision:
        response = await self._client.request(
            {
                "operation": "analyze",
                "request_id": str(uuid4()),
                "stream_id": str(stream_id),
                "audio_base64": base64.b64encode(pcm_s16le).decode("ascii"),
                "sample_rate_hz": sample_rate_hz,
                "channels": channels,
            }
        )
        return VoiceActivityDecision(
            speech_started=bool(response["speech_started"]),
            end_of_speech=bool(response["end_of_speech"]),
            probability=float(response["probability"]),
            processed_ms=int(response["processed_ms"]),
        )

    async def close(self, *, stream_id: UUID) -> None:
        await self._client.request(
            {
                "operation": "close",
                "request_id": str(uuid4()),
                "stream_id": str(stream_id),
            }
        )


class TtsWorkerAdapter:
    def __init__(self, client: UnixJsonWorkerClient) -> None:
        self._client = client

    async def synthesize(self, text: str, *, language: str) -> SynthesizedAudio:
        response = await self._client.request(
            {
                "operation": "synthesize",
                "request_id": str(uuid4()),
                "text": text,
                "language": language,
            }
        )
        try:
            pcm = base64.b64decode(str(response["pcm_base64"]), validate=True)
        except ValueError as error:
            raise AudioWorkerError("worker returned invalid audio") from error
        if not pcm or len(pcm) > 20 * 1024 * 1024:
            raise AudioWorkerError("worker returned invalid audio size")
        return SynthesizedAudio(
            pcm_s16le=pcm,
            sample_rate_hz=int(response["sample_rate_hz"]),
            channels=int(response["channels"]),
        )
