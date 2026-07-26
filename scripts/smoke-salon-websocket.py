#!/usr/bin/env python3
"""Exercise the live salon greeting and TTS path without retaining PCM."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
import os
from time import perf_counter
from urllib.parse import urlparse
from uuid import uuid4

from websockets.asyncio.client import connect


def envelope(
    *,
    event_type: str,
    session_id: object,
    request_id: object,
    sequence: int,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "type": event_type,
        "session_id": str(session_id),
        "request_id": str(request_id),
        "sequence": sequence,
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


async def run(url: str, token: str) -> dict[str, object]:
    session_id = uuid4()
    request_id = uuid4()
    started = perf_counter()
    chunk_count = 0
    first_audio_at: float | None = None
    assistant_text_present = False
    async with connect(
        f"{url}/v1/sessions/{session_id}/events",
        additional_headers={"Authorization": f"Bearer {token}"},
        open_timeout=10,
        close_timeout=5,
        max_size=2 * 1024 * 1024,
    ) as socket:
        await asyncio.wait_for(socket.recv(), timeout=5)
        await socket.send(
            json.dumps(
                envelope(
                    event_type="salon.call.start",
                    session_id=session_id,
                    request_id=request_id,
                    sequence=1,
                    payload={"channel": "web_qa"},
                ),
                separators=(",", ":"),
            )
        )
        while True:
            raw = await asyncio.wait_for(socket.recv(), timeout=30)
            event = json.loads(raw)
            if event["type"] == "salon.assistant.message":
                assistant_text_present = bool(event["payload"].get("text"))
            elif event["type"] == "audio.output.chunk":
                chunk_count += 1
                first_audio_at = first_audio_at or perf_counter()
            elif event["type"] == "error":
                raise RuntimeError(
                    f"gateway returned {event['payload'].get('error_code')}"
                )
            elif event["type"] == "audio.output.end":
                return {
                    "status": "passed",
                    "chunks": chunk_count,
                    "first_audio_after_connect_ms": (
                        round((first_audio_at - started) * 1_000, 3)
                        if first_audio_at is not None
                        else None
                    ),
                    "assistant_text_present": assistant_text_present,
                    "end_reason": event["payload"].get("reason"),
                }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:46326")
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if (
        parsed.scheme not in {"ws", "wss"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        parser.error("URL must be uncredentialed loopback WebSocket")
    token = os.environ.get("LVA_PAIRING_TOKEN", "")
    if len(token) < 32:
        parser.error("LVA_PAIRING_TOKEN is required")
    print(json.dumps(asyncio.run(run(args.url.rstrip("/"), token))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
