"""Bounded OpenAI-compatible conversation adapter for a loopback vLLM server."""

from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class VllmConversationError(RuntimeError):
    pass


class VllmConversationAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 120,
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

    async def respond(self, text: str, *, language: str) -> str:
        if not text.strip() or len(text) > 65_536:
            raise ValueError("conversation text is invalid")
        if len(language) > 32:
            raise ValueError("conversation language is invalid")
        payload = {
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
            "stream": False,
        }
        return await asyncio.to_thread(self._request, payload)

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
