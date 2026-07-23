#!/usr/bin/env python3
"""Persistent faster-whisper worker isolated from the PC-server runtime."""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
from pathlib import Path
from uuid import UUID

import numpy as np
from faster_whisper import WhisperModel

from worker_protocol import require_token, serve


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--compute-type", default="float16")
    args = parser.parse_args()
    if not args.model.is_dir():
        parser.error("model directory does not exist")
    token = require_token()
    model = WhisperModel(
        str(args.model),
        device=args.device,
        compute_type=args.compute_type,
    )

    def handle(request: dict[str, object]) -> dict[str, object]:
        required = {
            "operation",
            "request_id",
            "audio_base64",
            "sample_rate_hz",
            "channels",
        }
        if set(request) != required or request.get("operation") != "transcribe":
            raise ValueError("transcription request fields are invalid")
        UUID(str(request["request_id"]))
        sample_rate_hz = int(request["sample_rate_hz"])
        channels = int(request["channels"])
        if sample_rate_hz not in {16000, 24000, 48000} or channels not in {1, 2}:
            raise ValueError("audio format is unsupported")
        try:
            pcm = base64.b64decode(str(request["audio_base64"]), validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("audio is not valid base64") from error
        if not pcm or len(pcm) > 8 * 1024 * 1024 or len(pcm) % (2 * channels):
            raise ValueError("audio size is invalid")
        audio = np.frombuffer(pcm, dtype="<i2").reshape(-1, channels)
        mono = audio.astype(np.float32).mean(axis=1) / 32768.0
        if sample_rate_hz != 16000:
            output_length = round(len(mono) * 16000 / sample_rate_hz)
            if output_length < 1:
                raise ValueError("audio is too short to resample")
            source_positions = np.linspace(0.0, 1.0, len(mono), endpoint=False)
            target_positions = np.linspace(
                0.0,
                1.0,
                output_length,
                endpoint=False,
            )
            mono = np.interp(target_positions, source_positions, mono).astype(
                np.float32
            )
        segments, info = model.transcribe(
            mono,
            language="ko",
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        text = "".join(segment.text for segment in segments).strip()
        return {
            "status": "ok",
            "request_id": request["request_id"],
            "text": text,
            "language": info.language,
            "confidence": info.language_probability,
        }

    asyncio.run(
        serve(
            socket_path=args.socket,
            token=token,
            handler=handle,
            startup={
                "component": "stt-worker",
                "model_path": str(args.model),
                "device": args.device,
                "compute_type": args.compute_type,
            },
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
