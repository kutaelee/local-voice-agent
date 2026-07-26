"""Loopback-only raw PCM streaming adapter for vLLM-Omni Speech API."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
import json
import re
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..application.voice_turn import SynthesizedAudio
from .voice_profiles import VoiceSynthesisOptions


class VllmOmniTtsError(RuntimeError):
    pass


StreamTransport = Callable[[dict[str, object]], Iterator[bytes]]
_STREAM_END = object()


class VllmOmniTtsAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        voice: str,
        timeout_seconds: float = 180,
        sample_rate_hz: int = 24_000,
        stream_transport: StreamTransport | None = None,
        options_provider: Callable[[str], VoiceSynthesisOptions] | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "vLLM-Omni TTS URL must be an uncredentialed loopback HTTP URL"
            )
        if not voice or len(voice) > 128:
            raise ValueError("vLLM-Omni TTS voice is invalid")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("vLLM-Omni TTS timeout is invalid")
        if not 8_000 <= sample_rate_hz <= 192_000:
            raise ValueError("vLLM-Omni TTS sample rate is invalid")
        self._endpoint = base_url.rstrip("/") + "/v1/audio/speech"
        self._voice = voice
        self._timeout_seconds = timeout_seconds
        self._sample_rate_hz = sample_rate_hz
        self._stream_transport = stream_transport or self._stream_request
        self._options_provider = options_provider

    async def synthesize(self, text: str, *, language: str) -> SynthesizedAudio:
        chunks = [
            chunk
            async for chunk in self.stream_synthesize(
                text,
                language=language,
            )
        ]
        if not chunks:
            raise VllmOmniTtsError("vLLM-Omni returned no audio")
        return SynthesizedAudio(
            pcm_s16le=b"".join(item.pcm_s16le for item in chunks),
            sample_rate_hz=self._sample_rate_hz,
            channels=1,
        )

    async def stream_synthesize(
        self,
        text: str,
        *,
        language: str,
    ) -> AsyncIterator[SynthesizedAudio]:
        payload = self._payload(text, language=language)
        iterator = await asyncio.to_thread(
            lambda: iter(self._stream_transport(payload))
        )
        total_bytes = 0
        pending_byte = b""
        try:
            while True:
                item = await asyncio.to_thread(_next_or_end, iterator)
                if item is _STREAM_END:
                    break
                if not isinstance(item, bytes) or not item:
                    continue
                total_bytes += len(item)
                if total_bytes > 20 * 1024 * 1024:
                    raise VllmOmniTtsError("vLLM-Omni audio stream is too large")
                aligned = pending_byte + item
                if len(aligned) % 2:
                    pending_byte = aligned[-1:]
                    aligned = aligned[:-1]
                else:
                    pending_byte = b""
                if not aligned:
                    continue
                yield SynthesizedAudio(
                    pcm_s16le=aligned,
                    sample_rate_hz=self._sample_rate_hz,
                    channels=1,
                )
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                try:
                    await asyncio.to_thread(close)
                except Exception:
                    pass
        if pending_byte:
            raise VllmOmniTtsError("vLLM-Omni returned truncated PCM16 audio")
        if total_bytes == 0:
            raise VllmOmniTtsError("vLLM-Omni returned empty audio")

    def _payload(self, text: str, *, language: str) -> dict[str, object]:
        normalized = " ".join(text.strip().split())
        if not normalized or len(normalized) > 4_096:
            raise ValueError("TTS text is invalid")
        if not language or len(language) > 32:
            raise ValueError("TTS language is invalid")
        resolved_language = "Korean" if language.lower() in {"ko", "kor"} else language
        # Korean endings were occasionally truncated when short response
        # units hit the earlier 64-token floor. EOS still terminates normal
        # generations, so the larger ceiling is only a safety bound.
        max_new_tokens = min(768, max(160, len(normalized) * 8))
        payload: dict[str, object] = {
            "input": normalized,
            "voice": self._voice,
            "language": resolved_language,
            "task_type": "Base",
            "response_format": "pcm",
            "stream": True,
            "stream_format": "audio",
            "max_new_tokens": max_new_tokens,
        }
        if self._options_provider is not None:
            options = self._options_provider(normalized)
            if (
                options.reference_audio_path is not None
                and options.reference_text is not None
            ):
                profile_id = options.profile_id.strip().lower()
                if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", profile_id):
                    raise VllmOmniTtsError(
                        "voice profile ID is invalid for vLLM-Omni"
                    )
                # The GPU-stack supervisor registers every consented local
                # profile through vLLM-Omni's official voices endpoint before
                # it reports ready. Sending only the stable registered name
                # keeps private reference audio out of every speech request.
                payload["voice"] = f"lva-{profile_id}"
        return payload

    def _stream_request(self, payload: dict[str, object]) -> Iterator[bytes]:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            self._endpoint,
            data=encoded,
            method="POST",
            headers={
                "Accept": "application/octet-stream",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            response = urlopen(request, timeout=self._timeout_seconds)
        except (HTTPError, URLError, TimeoutError) as error:
            raise VllmOmniTtsError("vLLM-Omni TTS request failed") from error
        try:
            reader: BinaryIO = response
            read = getattr(reader, "read1", reader.read)
            while chunk := read(8 * 1024):
                yield bytes(chunk)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise VllmOmniTtsError("vLLM-Omni TTS stream failed") from error
        finally:
            response.close()


def _next_or_end(iterator: Iterator[bytes]) -> bytes | object:
    try:
        return next(iterator)
    except StopIteration:
        return _STREAM_END
