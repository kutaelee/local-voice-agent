#!/usr/bin/env python3
"""Warm the selected Qwen3-TTS voice and cache the escalation notice."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import wave


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "pc-server" / "src"))

from local_voice_agent_server.infrastructure.audio_workers import (  # noqa: E402
    TtsWorkerAdapter,
    UnixJsonWorkerClient,
)
from local_voice_agent_server.infrastructure.voice_profiles import (  # noqa: E402
    VoiceProfileStore,
)


async def run(args: argparse.Namespace) -> int:
    token = os.environ.get("LVA_AUDIO_WORKER_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("LVA_AUDIO_WORKER_TOKEN is required")
    store = VoiceProfileStore(args.voice_profiles_root)
    options = store.synthesis_options(args.text)
    if options.reference_audio_path is None or options.reference_text is None:
        raise RuntimeError("selected voice is not Qwen3-ready")
    adapter = TtsWorkerAdapter(
        UnixJsonWorkerClient(
            socket_path=args.socket,
            token=token,
            timeout_seconds=args.timeout_seconds,
        ),
        options_provider=store.synthesis_options,
    )
    started = time.perf_counter()
    audio = await adapter.synthesize(args.text, language="ko")
    elapsed_ms = round((time.perf_counter() - started) * 1_000, 1)
    duration_ms = round(
        len(audio.pcm_s16le)
        / (audio.sample_rate_hz * audio.channels * 2)
        * 1_000,
        1,
    )
    write_pcm_wave(
        args.cache_output,
        pcm_s16le=audio.pcm_s16le,
        sample_rate_hz=audio.sample_rate_hz,
        channels=audio.channels,
    )
    print(
        json.dumps(
            {
                "status": "warmed",
                "elapsed_ms": elapsed_ms,
                "audio_duration_ms": duration_ms,
                "profile_id_redacted": True,
                "audio_retained": True,
                "cache_output": str(args.cache_output),
            },
            separators=(",", ":"),
        )
    )
    return 0


def write_pcm_wave(
    path: Path,
    *,
    pcm_s16le: bytes,
    sample_rate_hz: int,
    channels: int,
) -> None:
    if not path.is_absolute():
        raise ValueError("cache output path must be absolute")
    if channels not in {1, 2} or not 8_000 <= sample_rate_hz <= 192_000:
        raise ValueError("synthesized audio format is invalid")
    if len(pcm_s16le) % (channels * 2):
        raise ValueError("synthesized audio is not frame aligned")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with wave.open(str(temporary), "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(2)
            output.setframerate(sample_rate_hz)
            output.writeframes(pcm_s16le)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--voice-profiles-root", type=Path, required=True)
    parser.add_argument("--text", default="잠시만요, 확인해 볼게요.")
    parser.add_argument("--cache-output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    if (
        not args.socket.is_absolute()
        or not args.voice_profiles_root.is_absolute()
        or not args.cache_output.is_absolute()
    ):
        parser.error("socket, voice profile, and cache paths must be absolute")
    if not args.text.strip() or len(args.text) > 40:
        parser.error("warm-up text must contain 1 to 40 characters")
    if not 30 <= args.timeout_seconds <= 300:
        parser.error("timeout must be between 30 and 300 seconds")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
