#!/usr/bin/env python3
"""Verify the salon speech projection through the real local TTS worker."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter

from local_voice_agent_server.application.salon_speech import SalonSpeechService
from local_voice_agent_server.infrastructure.audio_workers import (
    TtsWorkerAdapter,
    UnixJsonWorkerClient,
)
from local_voice_agent_server.infrastructure.voice_profiles import VoiceProfileStore


TEXTS = (
    "안녕하세요, 윤슬 헤어 예약 도우미 수아입니다. 어떤 예약을 도와드릴까요?",
    "예약이 확정됐습니다. 일요일 오후 두 시 커트, 담당 민지입니다.",
)


async def run(args: argparse.Namespace) -> dict[str, object]:
    token = os.environ.get("LVA_AUDIO_WORKER_TOKEN", "")
    profiles = VoiceProfileStore(args.voice_profiles_root)
    tts = TtsWorkerAdapter(
        UnixJsonWorkerClient(
            socket_path=args.socket,
            token=token,
            timeout_seconds=180,
        ),
        options_provider=profiles.synthesis_options,
    )
    service = SalonSpeechService(
        tts=tts,
        release_fade_ms=24,
        final_silence_ms=200,
    )
    results = []
    for text in TEXTS:
        started = perf_counter()
        events = await service.synthesize(text)
        latency_ms = round((perf_counter() - started) * 1_000, 3)
        chunks = [
            event
            for event in events
            if event.type == "audio.output.chunk"
        ]
        encoded = "".join(str(item.payload["data_base64"]) for item in chunks)
        result = {
            "text_sha256": sha256(text.encode("utf-8")).hexdigest(),
            "latency_ms": latency_ms,
            "chunk_count": len(chunks),
            "duration_ms": sum(
                int(item.payload["duration_ms"]) for item in chunks
            ),
            "sample_rate_hz": chunks[0].payload["sample_rate_hz"],
            "channels": chunks[0].payload["channels"],
            "encoded_event_digest": sha256(encoded.encode("ascii")).hexdigest(),
            "audio_end_reason": events[-2].payload["reason"],
            "resume_state": events[-1].payload["state"],
        }
        results.append(result)
    return {
        "schema_version": "1.0",
        "status": "passed",
        "engine": "qwen3-tts-1.7b-base",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile_id": profiles.get_settings().profile_id,
        "release_fade_ms": 24,
        "final_silence_ms": 200,
        "samples": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--socket",
        type=Path,
        default=Path("/home/kutae/.local/share/local-voice-agent/run/tts.sock"),
    )
    parser.add_argument(
        "--voice-profiles-root",
        type=Path,
        default=Path("/mnt/e/Data/LocalVoiceAgent/voice-profiles"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "samples": len(result["samples"]),
                "output": str(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
