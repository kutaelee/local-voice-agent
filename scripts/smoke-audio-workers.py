#!/usr/bin/env python3
"""Exercise the persistent TTS and STT workers through production adapters."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "pc-server" / "src"))

from local_voice_agent_server.infrastructure.audio_workers import (  # noqa: E402
    SttWorkerAdapter,
    TtsWorkerAdapter,
    UnixJsonWorkerClient,
)


async def main() -> int:
    token = os.environ.get("LVA_AUDIO_WORKER_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("LVA_AUDIO_WORKER_TOKEN is required")
    stt = SttWorkerAdapter(
        UnixJsonWorkerClient(
            socket_path=Path(
                "/home/kutae/.local/share/local-voice-agent/run/stt.sock"
            ),
            token=token,
            timeout_seconds=60,
        )
    )
    tts = TtsWorkerAdapter(
        UnixJsonWorkerClient(
            socket_path=Path(
                "/home/kutae/.local/share/local-voice-agent/run/tts.sock"
            ),
            token=token,
            timeout_seconds=180,
        )
    )
    text = "안녕하세요. 음성 워커 통합 테스트입니다."
    started = time.perf_counter()
    audio = await tts.synthesize(text, language="ko")
    tts_seconds = time.perf_counter() - started
    started = time.perf_counter()
    transcript = await stt.transcribe(
        audio.pcm_s16le,
        sample_rate_hz=audio.sample_rate_hz,
        channels=audio.channels,
    )
    stt_seconds = time.perf_counter() - started
    print(
        json.dumps(
            {
                "status": "passed",
                "input_text": text,
                "transcript": transcript.text,
                "language": transcript.language,
                "tts_seconds": round(tts_seconds, 3),
                "stt_seconds": round(stt_seconds, 3),
                "pcm_bytes": len(audio.pcm_s16le),
                "sample_rate_hz": audio.sample_rate_hz,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
