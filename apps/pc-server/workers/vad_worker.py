#!/usr/bin/env python3
"""Persistent CPU ONNX Silero VAD worker with bounded per-stream state."""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import numpy as np
from silero_vad import load_silero_vad
import torch

from worker_protocol import require_token, serve


MODEL_SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512
MAX_STREAMS = 4
MAX_STREAM_SAMPLES = MODEL_SAMPLE_RATE * 120


@dataclass(slots=True)
class StreamState:
    model: object
    pending: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float32)
    )
    processed_samples: int = 0
    voiced_samples: int = 0
    silence_samples: int = 0
    speech_started: bool = False
    end_of_speech: bool = False
    probability: float = 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--negative-threshold", type=float, default=0.35)
    parser.add_argument("--min-silence-ms", type=int, default=500)
    parser.add_argument("--min-speech-ms", type=int, default=100)
    args = parser.parse_args()
    if not 0.0 < args.negative_threshold < args.threshold < 1.0:
        parser.error("VAD thresholds are invalid")
    if not 100 <= args.min_silence_ms <= 2_000:
        parser.error("minimum silence is invalid")
    if not 32 <= args.min_speech_ms <= 5_000:
        parser.error("minimum speech is invalid")
    token = require_token()
    streams: dict[UUID, StreamState] = {}
    min_silence_samples = round(
        MODEL_SAMPLE_RATE * args.min_silence_ms / 1_000
    )
    min_speech_samples = round(
        MODEL_SAMPLE_RATE * args.min_speech_ms / 1_000
    )

    def handle(request: dict[str, object]) -> dict[str, object]:
        operation = request.get("operation")
        if operation == "close":
            if set(request) != {"operation", "request_id", "stream_id"}:
                raise ValueError("VAD close fields are invalid")
            UUID(str(request["request_id"]))
            stream_id = UUID(str(request["stream_id"]))
            streams.pop(stream_id, None)
            return {
                "status": "ok",
                "request_id": request["request_id"],
                "stream_id": str(stream_id),
                "closed": True,
            }
        required = {
            "operation",
            "request_id",
            "stream_id",
            "audio_base64",
            "sample_rate_hz",
            "channels",
        }
        if set(request) != required or operation != "analyze":
            raise ValueError("VAD request fields are invalid")
        UUID(str(request["request_id"]))
        stream_id = UUID(str(request["stream_id"]))
        sample_rate_hz = int(request["sample_rate_hz"])
        channels = int(request["channels"])
        if sample_rate_hz not in {16_000, 24_000, 48_000}:
            raise ValueError("VAD sample rate is unsupported")
        if channels not in {1, 2}:
            raise ValueError("VAD channel count is unsupported")
        try:
            pcm = base64.b64decode(str(request["audio_base64"]), validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("VAD audio is not valid base64") from error
        if (
            not pcm
            or len(pcm) > 384 * 1024
            or len(pcm) % (2 * channels)
        ):
            raise ValueError("VAD audio size is invalid")

        state = streams.get(stream_id)
        if state is None:
            if len(streams) >= MAX_STREAMS:
                raise ValueError("VAD stream limit reached")
            state = StreamState(model=load_silero_vad(onnx=True))
            streams[stream_id] = state
        if state.end_of_speech:
            return _response(request, stream_id, state)

        audio = np.frombuffer(pcm, dtype="<i2").reshape(-1, channels)
        mono = audio.astype(np.float32).mean(axis=1) / 32768.0
        mono = _resample(mono, sample_rate_hz)
        state.pending = np.concatenate((state.pending, mono))
        while len(state.pending) >= FRAME_SAMPLES:
            frame = state.pending[:FRAME_SAMPLES]
            state.pending = state.pending[FRAME_SAMPLES:]
            probability = float(
                state.model(torch.from_numpy(frame), MODEL_SAMPLE_RATE).item()
            )
            state.probability = probability
            state.processed_samples += FRAME_SAMPLES
            if state.processed_samples > MAX_STREAM_SAMPLES:
                state.end_of_speech = True
                break
            if probability >= args.threshold:
                state.speech_started = True
                state.voiced_samples += FRAME_SAMPLES
                state.silence_samples = 0
            elif (
                state.speech_started
                and probability < args.negative_threshold
            ):
                state.silence_samples += FRAME_SAMPLES
            elif state.speech_started:
                state.silence_samples = 0
            if (
                state.voiced_samples >= min_speech_samples
                and state.silence_samples >= min_silence_samples
            ):
                state.end_of_speech = True
                break
        return _response(request, stream_id, state)

    asyncio.run(
        serve(
            socket_path=args.socket,
            token=token,
            handler=handle,
            startup={
                "component": "vad-worker",
                "runtime": "silero-vad-6.2.1-onnx-cpu",
                "sample_rate_hz": MODEL_SAMPLE_RATE,
                "threshold": args.threshold,
                "negative_threshold": args.negative_threshold,
                "min_silence_ms": args.min_silence_ms,
                "min_speech_ms": args.min_speech_ms,
            },
        )
    )
    return 0


def _resample(audio: np.ndarray, sample_rate_hz: int) -> np.ndarray:
    if sample_rate_hz == MODEL_SAMPLE_RATE:
        return audio.astype(np.float32, copy=False)
    output_length = round(len(audio) * MODEL_SAMPLE_RATE / sample_rate_hz)
    if output_length < 1:
        raise ValueError("VAD audio is too short to resample")
    source = np.arange(len(audio), dtype=np.float64)
    target = np.arange(output_length, dtype=np.float64)
    target *= sample_rate_hz / MODEL_SAMPLE_RATE
    return np.interp(target, source, audio).astype(np.float32)


def _response(
    request: dict[str, object],
    stream_id: UUID,
    state: StreamState,
) -> dict[str, object]:
    return {
        "status": "ok",
        "request_id": request["request_id"],
        "stream_id": str(stream_id),
        "speech_started": state.speech_started,
        "end_of_speech": state.end_of_speech,
        "probability": round(state.probability, 6),
        "processed_ms": round(
            state.processed_samples * 1_000 / MODEL_SAMPLE_RATE
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
