"""Bounded authenticated JSON-lines server for local Unix-socket GPU workers."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from pathlib import Path
from typing import Callable


MAX_REQUEST_BYTES = 12 * 1024 * 1024
MAX_RESPONSE_BYTES = 24 * 1024 * 1024


def require_token() -> str:
    token = os.environ.get("LVA_AUDIO_WORKER_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("LVA_AUDIO_WORKER_TOKEN must contain at least 32 characters")
    return token


async def serve(
    *,
    socket_path: Path,
    token: str,
    handler: Callable[[dict[str, object]], dict[str, object]],
    startup: dict[str, object],
) -> None:
    if not socket_path.is_absolute():
        raise ValueError("worker socket path must be absolute")
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        if not socket_path.is_socket():
            raise RuntimeError("refusing to replace a non-socket path")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(socket_path),
                timeout=0.5,
            )
        except (ConnectionError, OSError, TimeoutError):
            socket_path.unlink()
        else:
            writer.close()
            await writer.wait_closed()
            del reader
            raise RuntimeError("worker socket is already active")

    execution_lock = asyncio.Lock()

    async def on_client(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        response: dict[str, object]
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=10)
            if not raw or len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                raise ValueError("request frame is invalid")
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            request_token = request.pop("token", None)
            if not isinstance(request_token, str) or not hmac.compare_digest(
                request_token,
                token,
            ):
                raise PermissionError("worker authentication failed")
            operation = request.get("operation")
            if operation == "health":
                if set(request) != {"operation", "request_id"}:
                    raise ValueError("health request fields are invalid")
                response = {
                    "status": "ok",
                    "request_id": request.get("request_id"),
                    **startup,
                }
            else:
                async with execution_lock:
                    response = await asyncio.to_thread(handler, request)
        except PermissionError:
            response = {"status": "error", "error_code": "UNAUTHORIZED"}
        except (ValueError, json.JSONDecodeError):
            response = {"status": "error", "error_code": "REQUEST_INVALID"}
        except Exception:
            response = {"status": "error", "error_code": "WORKER_FAILED"}
        encoded = json.dumps(
            response,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        if len(encoded) > MAX_RESPONSE_BYTES:
            encoded = b'{"status":"error","error_code":"RESPONSE_TOO_LARGE"}\n'
        writer.write(encoded)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(
        on_client,
        path=socket_path,
        limit=MAX_REQUEST_BYTES + 1,
    )
    os.chmod(socket_path, 0o600)
    try:
        async with server:
            await server.serve_forever()
    finally:
        if socket_path.exists() and socket_path.is_socket():
            socket_path.unlink()
