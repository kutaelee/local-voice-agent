"""Bounded OpenAI-compatible conversation adapter for a loopback vLLM server."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Callable, Iterable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class VllmConversationError(RuntimeError):
    pass


StreamTransport = Callable[[dict[str, object]], Iterable[str]]
_STREAM_END = object()


class VllmConversationAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 120,
        stream_transport: StreamTransport | None = None,
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
            raise ValueError("vLLM URL must be an uncredentialed loopback HTTP URL")
        if not model or len(model) > 512:
            raise ValueError("vLLM model name is invalid")
        if len(api_key) < 32:
            raise ValueError("vLLM API key must contain at least 32 characters")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("vLLM timeout is invalid")
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._stream_transport = stream_transport or self._stream_request

    async def respond(self, text: str, *, language: str) -> str:
        payload = self._payload(text, language=language, stream=False)
        return await asyncio.to_thread(self._request, payload)

    async def stream(
        self,
        text: str,
        *,
        language: str,
    ) -> AsyncIterator[str]:
        payload = self._payload(text, language=language, stream=True)
        iterator = await asyncio.to_thread(
            lambda: iter(self._stream_transport(payload))
        )
        total_characters = 0
        try:
            while True:
                item = await asyncio.to_thread(_next_or_end, iterator)
                if item is _STREAM_END:
                    break
                if not isinstance(item, str):
                    raise VllmConversationError(
                        "vLLM stream returned invalid content"
                    )
                if not item:
                    continue
                total_characters += len(item)
                if total_characters > 2 * 1024 * 1024:
                    raise VllmConversationError("vLLM stream is too large")
                yield item
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                try:
                    await asyncio.to_thread(close)
                except Exception:
                    pass
        if total_characters == 0:
            raise VllmConversationError("vLLM stream returned empty content")

    def _payload(
        self,
        text: str,
        *,
        language: str,
        stream: bool,
    ) -> dict[str, object]:
        if not text.strip() or len(text) > 65_536:
            raise ValueError("conversation text is invalid")
        if len(language) > 32:
            raise ValueError("conversation language is invalid")
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a local voice assistant. Reply concisely in the "
                        f"user's language ({language}). Never claim a tool ran unless "
                        "the tool execution system returned verified evidence."
                    ),
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
            "max_tokens": 512,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _request(self, payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            self._endpoint,
            data=encoded,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except (HTTPError, URLError, TimeoutError) as error:
            raise VllmConversationError("vLLM request failed") from error
        if len(raw) > 2 * 1024 * 1024:
            raise VllmConversationError("vLLM response is too large")
        try:
            value = json.loads(raw)
            text = value["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise VllmConversationError("vLLM response shape is invalid") from error
        if not isinstance(text, str) or not text.strip():
            raise VllmConversationError("vLLM returned empty content")
        return text

    def _stream_request(
        self,
        payload: dict[str, object],
    ) -> Iterable[str]:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            self._endpoint,
            data=encoded,
            method="POST",
            headers={
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            response = urlopen(request, timeout=self._timeout_seconds)
        except (HTTPError, URLError, TimeoutError) as error:
            raise VllmConversationError("vLLM stream request failed") from error
        try:
            for raw_line in response:
                if len(raw_line) > 2 * 1024 * 1024:
                    raise VllmConversationError("vLLM stream event is too large")
                try:
                    line = raw_line.decode("utf-8").strip()
                except UnicodeDecodeError as error:
                    raise VllmConversationError(
                        "vLLM stream is not valid UTF-8"
                    ) from error
                if not line.startswith("data:"):
                    continue
                encoded_event = line[5:].lstrip()
                if encoded_event == "[DONE]":
                    break
                try:
                    event = json.loads(encoded_event)
                    choices = event.get("choices") or []
                    delta = choices[0].get("delta") if choices else None
                    content = delta.get("content") if isinstance(delta, dict) else None
                except (json.JSONDecodeError, AttributeError, IndexError) as error:
                    raise VllmConversationError(
                        "vLLM stream event shape is invalid"
                    ) from error
                if content is not None:
                    if not isinstance(content, str):
                        raise VllmConversationError(
                            "vLLM stream content is invalid"
                        )
                    yield content
        finally:
            response.close()


def _next_or_end(iterator: Iterator[str]) -> str | object:
    try:
        return next(iterator)
    except StopIteration:
        return _STREAM_END
