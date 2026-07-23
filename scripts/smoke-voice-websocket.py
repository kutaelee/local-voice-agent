#!/usr/bin/env python3
"""Run the production WebSocket voice path against live local workers."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import wave
from uuid import uuid4


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "pc-server" / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from local_voice_agent_server.api import create_app_from_environment  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-wav", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    return parser.parse_args()


def _event(
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


def main() -> int:
    args = _arguments()
    if len(os.environ.get("LVA_PAIRING_TOKEN", "")) < 32:
        raise RuntimeError("LVA_PAIRING_TOKEN is required")
    with wave.open(str(args.input_wav), "rb") as source:
        sample_rate_hz = source.getframerate()
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        pcm = source.readframes(source.getnframes())
    if sample_width != 2 or sample_rate_hz not in {16000, 24000, 48000}:
        raise RuntimeError("input must be 16-bit PCM WAV at 16, 24, or 48 kHz")
    if channels not in {1, 2}:
        raise RuntimeError("input must contain one or two channels")

    session_id = uuid4()
    request_id = uuid4()
    stream_id = uuid4()
    sequence = 0
    received: list[dict[str, object]] = []
    output = bytearray()
    app = create_app_from_environment()
    headers = {
        "Authorization": "Bearer " + os.environ["LVA_PAIRING_TOKEN"],
    }
    with TestClient(app).websocket_connect(
        f"/v1/sessions/{session_id}/events",
        headers=headers,
    ) as socket:
        received.append(socket.receive_json())
        sequence += 1
        socket.send_json(
            _event(
                event_type="audio.input.start",
                session_id=session_id,
                request_id=request_id,
                sequence=sequence,
                payload={
                    "audio_stream_id": str(stream_id),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": sample_rate_hz,
                    "channels": channels,
                },
            )
        )
        received.append(socket.receive_json())
        bytes_per_millisecond = sample_rate_hz * channels * 2 / 1000
        for chunk_index, offset in enumerate(range(0, len(pcm), 32 * 1024)):
            chunk = pcm[offset : offset + 32 * 1024]
            sequence += 1
            socket.send_json(
                _event(
                    event_type="audio.input.chunk",
                    session_id=session_id,
                    request_id=request_id,
                    sequence=sequence,
                    payload={
                        "audio_stream_id": str(stream_id),
                        "chunk_index": chunk_index,
                        "encoding": "pcm_s16le",
                        "duration_ms": max(
                            1,
                            round(len(chunk) / bytes_per_millisecond),
                        ),
                        "data_base64": base64.b64encode(chunk).decode("ascii"),
                    },
                )
            )
        sequence += 1
        socket.send_json(
            _event(
                event_type="audio.input.end",
                session_id=session_id,
                request_id=request_id,
                sequence=sequence,
                payload={
                    "audio_stream_id": str(stream_id),
                    "reason": "vad_end",
                },
            )
        )
        while True:
            message = socket.receive_json()
            received.append(message)
            if message["type"] == "audio.output.chunk":
                output.extend(
                    base64.b64decode(
                        message["payload"]["data_base64"],
                        validate=True,
                    )
                )
            if message["type"] in {"audio.output.end", "error"}:
                break

    final_type = received[-1]["type"]
    result = {
        "schema_version": "1.0",
        "status": "passed" if final_type == "audio.output.end" else "failed",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "path": str(args.input_wav),
            "pcm_bytes": len(pcm),
            "sample_rate_hz": sample_rate_hz,
            "channels": channels,
            "sha256": hashlib.sha256(pcm).hexdigest(),
        },
        "transcript": next(
            (
                message["payload"]["text"]
                for message in received
                if message["type"] == "transcript.user.final"
            ),
            None,
        ),
        "assistant_text": next(
            (
                message["payload"]["text"]
                for message in received
                if message["type"] == "assistant.text.final"
            ),
            None,
        ),
        "output": {
            "chunks": sum(
                message["type"] == "audio.output.chunk"
                for message in received
            ),
            "pcm_bytes": len(output),
            "sha256": hashlib.sha256(output).hexdigest(),
        },
        "event_types": [
            message["type"]
            for message in received
            if message["type"] != "audio.output.chunk"
        ],
    }
    serialized = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.evidence.with_suffix(args.evidence.suffix + ".tmp")
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(args.evidence)
    print(serialized, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
