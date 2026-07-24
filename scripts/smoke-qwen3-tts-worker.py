#!/usr/bin/env python3
"""Synthesize one selected local voice through the production TTS adapter."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from hashlib import sha256
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
            timeout_seconds=180,
        ),
        options_provider=store.synthesis_options,
    )
    started = time.perf_counter()
    audio = await adapter.synthesize(args.text, language="ko")
    synthesis_seconds = time.perf_counter() - started

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output), "wb") as output:
        output.setnchannels(audio.channels)
        output.setsampwidth(2)
        output.setframerate(audio.sample_rate_hz)
        output.writeframes(audio.pcm_s16le)
    output_bytes = args.output.read_bytes()
    duration_seconds = (
        len(audio.pcm_s16le) / (audio.sample_rate_hz * audio.channels * 2)
    )
    evidence = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed",
        "engine": "qwen3-tts-12hz-1.7b-base",
        "profile_style": options.style,
        "reference_transcript_present": True,
        "reference_profile_id_redacted": True,
        "input_text": args.text,
        "sample_rate_hz": audio.sample_rate_hz,
        "channels": audio.channels,
        "pcm_bytes": len(audio.pcm_s16le),
        "audio_seconds": round(duration_seconds, 3),
        "synthesis_seconds": round(synthesis_seconds, 3),
        "realtime_factor": round(synthesis_seconds / duration_seconds, 3),
        "output_path": str(args.output),
        "output_size_bytes": len(output_bytes),
        "output_sha256": sha256(output_bytes).hexdigest(),
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--voice-profiles-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    for path in (
        args.socket,
        args.voice_profiles_root,
        args.output,
        args.evidence,
    ):
        if not path.is_absolute():
            parser.error("all paths must be absolute")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
