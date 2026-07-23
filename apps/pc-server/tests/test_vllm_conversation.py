import asyncio
from collections.abc import Iterator

import pytest

from local_voice_agent_server.infrastructure import vllm_conversation
from local_voice_agent_server.infrastructure.vllm_conversation import (
    VllmConversationAdapter,
    VllmConversationError,
)


API_KEY = "test-only-api-key-with-at-least-32-characters"


def _collect(adapter: VllmConversationAdapter) -> list[str]:
    async def scenario() -> list[str]:
        return [
            delta
            async for delta in adapter.stream(
                "컴퓨터 상태를 알려줘.",
                language="ko",
            )
        ]

    return asyncio.run(scenario())


def test_stream_yields_ordered_deltas_and_requests_usage() -> None:
    payloads: list[dict[str, object]] = []

    def transport(payload: dict[str, object]) -> Iterator[str]:
        payloads.append(payload)
        return iter(("현재 ", "상태는 ", "정상입니다."))

    adapter = VllmConversationAdapter(
        base_url="http://127.0.0.1:8000/v1",
        model="local-gemma",
        api_key=API_KEY,
        stream_transport=transport,
    )

    assert _collect(adapter) == ["현재 ", "상태는 ", "정상입니다."]
    assert payloads[0]["stream"] is True
    assert payloads[0]["stream_options"] == {"include_usage": True}


def test_stream_rejects_empty_content() -> None:
    adapter = VllmConversationAdapter(
        base_url="http://127.0.0.1:8000/v1",
        model="local-gemma",
        api_key=API_KEY,
        stream_transport=lambda _: iter(("", "")),
    )

    with pytest.raises(VllmConversationError, match="empty content"):
        _collect(adapter)


def test_stream_parses_sse_and_closes_http_response(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self) -> None:
            self.closed = False

        def __iter__(self):
            return iter(
                (
                    b": keepalive\n",
                    b'data: {"choices":[{"delta":{"content":"hello"}}]}\n',
                    b'data:{"choices":[],"usage":{"completion_tokens":1}}\n',
                    b"data: [DONE]\n",
                )
            )

        def close(self) -> None:
            self.closed = True

    response = FakeResponse()

    def fake_urlopen(request, *, timeout):
        assert request.full_url == "http://127.0.0.1:8000/v1/chat/completions"
        assert request.get_header("Accept") == "text/event-stream"
        assert timeout == 120
        return response

    monkeypatch.setattr(vllm_conversation, "urlopen", fake_urlopen)
    adapter = VllmConversationAdapter(
        base_url="http://127.0.0.1:8000/v1",
        model="local-gemma",
        api_key=API_KEY,
    )

    assert _collect(adapter) == ["hello"]
    assert response.closed is True


def test_stream_closes_transport_when_consumer_stops() -> None:
    class CloseTrackingIterator:
        def __init__(self) -> None:
            self.closed = False
            self._items = iter(("first", "second"))

        def __iter__(self) -> "CloseTrackingIterator":
            return self

        def __next__(self) -> str:
            return next(self._items)

        def close(self) -> None:
            self.closed = True

    source = CloseTrackingIterator()
    adapter = VllmConversationAdapter(
        base_url="http://127.0.0.1:8000/v1",
        model="local-gemma",
        api_key=API_KEY,
        stream_transport=lambda _: source,
    )

    async def scenario() -> None:
        stream = adapter.stream("hello", language="en")
        assert await anext(stream) == "first"
        await stream.aclose()

    asyncio.run(scenario())
    assert source.closed is True
