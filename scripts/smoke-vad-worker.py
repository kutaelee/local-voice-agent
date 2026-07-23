#!/usr/bin/env python3
"""Exercise the authenticated Silero VAD worker with local Korean audio."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
from time import perf_counter
import wave
from uuid import uuid4

import numpy as np


async def exchange(
    socket_path: Path,
    token: str,
    payload: dict[str, object],
) -> dict[str, object]:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    writer.write(
        json.dumps(
            {**payload, "token": token},
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    await writer.drain()
    raw = await asyncio.wait_for(reader.readline(), timeout=10)
    writer.close()
    await writer.wait_closed()
    value = json.loads(raw)
    if value.get("status") != "ok":
        raise RuntimeError(f"VAD worker failed: {value.get('error_code')}")
    return value


async def run(socket_path: Path, sample: Path, token: str) -> dict[str, object]:
    with wave.open(str(sample), "rb") as source:
        sample_rate_hz = source.getframerate()
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        pcm = source.readframes(source.getnframes())
    if sample_width != 2 or channels != 1:
        raise RuntimeError("smoke sample must be mono PCM16")
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    if sample_rate_hz != 16_000:
        output_length = round(len(audio) * 16_000 / sample_rate_hz)
        positions = np.arange(output_length) * sample_rate_hz / 16_000
        audio = np.interp(
            positions,
            np.arange(len(audio)),
            audio,
        ).astype("<i2")
    else:
        audio = audio.astype("<i2")
    audio = np.concatenate(
        (audio, np.zeros(16_000, dtype="<i2"))
    )

    stream_id = uuid4()
    first_speech_ms: int | None = None
    end_ms: int | None = None
    requests = 0
    started = perf_counter()
    for offset in range(0, len(audio), 512):
        chunk = audio[offset : offset + 512]
        if len(chunk) < 512:
            chunk = np.pad(chunk, (0, 512 - len(chunk)))
        response = await exchange(
            socket_path,
            token,
            {
                "operation": "analyze",
                "request_id": str(uuid4()),
                "stream_id": str(stream_id),
                "audio_base64": base64.b64encode(chunk.tobytes()).decode(),
                "sample_rate_hz": 16_000,
                "channels": 1,
            },
        )
        requests += 1
        processed_ms = int(response["processed_ms"])
        if response["speech_started"] and first_speech_ms is None:
            first_speech_ms = processed_ms
        if response["end_of_speech"]:
            end_ms = processed_ms
            break
    await exchange(
        socket_path,
        token,
        {
            "operation": "close",
            "request_id": str(uuid4()),
            "stream_id": str(stream_id),
        },
    )
    if first_speech_ms is None or end_ms is None:
        raise RuntimeError("VAD did not detect speech and endpoint")
    return {
        "status": "passed",
        "runtime": "silero-vad-6.2.1-onnx-cpu",
        "sample": str(sample),
        "requests": requests,
        "first_speech_processed_ms": first_speech_ms,
        "end_of_speech_processed_ms": end_ms,
        "wall_latency_ms": round((perf_counter() - started) * 1_000, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--socket",
        type=Path,
        default=Path(
            "/home/kutae/.local/share/local-voice-agent/run/vad.sock"
        ),
    )
    parser.add_argument(
        "--sample",
        type=Path,
        default=Path(
            "/mnt/e/Data/LocalVoiceAgent/runtime/evidence/audio/"
            "chatterbox-v3-ko-smoke.wav"
        ),
    )
    args = parser.parse_args()
    token = os.environ.get("LVA_AUDIO_WORKER_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("LVA_AUDIO_WORKER_TOKEN is required")
    if not args.socket.is_absolute() or not args.sample.is_file():
        raise RuntimeError("VAD smoke paths are invalid")
    result = asyncio.run(run(args.socket, args.sample, token))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
