#!/usr/bin/env python3
"""Check one authenticated local audio-worker Unix socket."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4


async def check(path: Path, token: str) -> dict[str, object]:
    reader, writer = await asyncio.open_unix_connection(path)
    writer.write(
        json.dumps(
            {
                "operation": "health",
                "request_id": str(uuid4()),
                "token": token,
            },
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    await writer.drain()
    raw = await asyncio.wait_for(reader.readline(), timeout=5)
    writer.close()
    await writer.wait_closed()
    value = json.loads(raw)
    if value.get("status") != "ok":
        raise RuntimeError("worker health failed")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("socket", type=Path)
    args = parser.parse_args()
    token = os.environ.get("LVA_AUDIO_WORKER_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("LVA_AUDIO_WORKER_TOKEN is required")
    value = asyncio.run(check(args.socket, token))
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
