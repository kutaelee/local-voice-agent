#!/usr/bin/env python3
"""Synthesize one profile and verify the generated words through local STT."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter
import wave


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "pc-server" / "src"))

from local_voice_agent_server.infrastructure.audio_workers import (  # noqa: E402
    SttWorkerAdapter,
    TtsWorkerAdapter,
    UnixJsonWorkerClient,
)
from local_voice_agent_server.infrastructure.voice_profiles import (  # noqa: E402
    VoiceProfileStore,
    VoiceSynthesisOptions,
)


async def run(args: argparse.Namespace) -> dict[str, object]:
    token = os.environ.get("LVA_AUDIO_WORKER_TOKEN", "")
    if not token and args.worker_token_file.is_file():
        token = args.worker_token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("LVA_AUDIO_WORKER_TOKEN is required")
    profiles = VoiceProfileStore(args.voice_profiles_root)
    profile = next(
        (
            item
            for item in profiles.list_profiles()
            if item.profile_id == args.profile_id
        ),
        None,
    )
    if profile is None or profile.is_default or profile.reference_text is None:
        raise RuntimeError("a reference-backed voice profile is required")
    reference = profiles.reference_path(profile.profile_id)
    if reference is None:
        raise RuntimeError("voice reference is unavailable")

    def options_provider(_: str) -> VoiceSynthesisOptions:
        return VoiceSynthesisOptions(
            profile_id=profile.profile_id,
            reference_audio_path=reference,
            exaggeration=args.exaggeration,
            cfg_weight=args.cfg_weight,
            temperature=args.temperature,
            reference_text=profile.reference_text,
            style=profile.style,
        )

    tts = TtsWorkerAdapter(
        UnixJsonWorkerClient(
            socket_path=args.tts_socket,
            token=token,
            timeout_seconds=300,
        ),
        options_provider=options_provider,
    )
    stt = SttWorkerAdapter(
        UnixJsonWorkerClient(
            socket_path=args.stt_socket,
            token=token,
            timeout_seconds=120,
        )
    )
    started = perf_counter()
    audio = await tts.synthesize(args.text, language="ko")
    tts_seconds = perf_counter() - started
    started = perf_counter()
    transcript = await stt.transcribe(
        audio.pcm_s16le,
        sample_rate_hz=audio.sample_rate_hz,
        channels=audio.channels,
    )
    stt_seconds = perf_counter() - started

    args.output_wav.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output_wav), "wb") as output:
        output.setnchannels(audio.channels)
        output.setsampwidth(2)
        output.setframerate(audio.sample_rate_hz)
        output.writeframes(audio.pcm_s16le)
    result = {
        "schema_version": "1.0",
        "test": "voice_profile_content_round_trip",
        "created_at": datetime.now(UTC).isoformat(),
        "profile_id": profile.profile_id,
        "profile_name": profile.name,
        "model_validation": "speaker_similarity_requires_listening",
        "input_text": args.text,
        "stt_transcript": transcript.text,
        "stt_language": transcript.language,
        "stt_confidence": transcript.confidence,
        "exact_text_match": transcript.text.strip() == args.text.strip(),
        "tts_seconds": round(tts_seconds, 3),
        "stt_seconds": round(stt_seconds, 3),
        "audio_duration_seconds": round(
            len(audio.pcm_s16le)
            / (audio.sample_rate_hz * audio.channels * 2),
            3,
        ),
        "output_wav": str(args.output_wav),
        "output_sha256": sha256(args.output_wav.read_bytes()).hexdigest(),
    }
    with args.evidence.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--output-wav", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--voice-profiles-root",
        type=Path,
        default=Path("/mnt/e/Data/LocalVoiceAgent/voice-profiles"),
    )
    parser.add_argument(
        "--tts-socket",
        type=Path,
        default=Path(
            "/home/kutae/.local/share/local-voice-agent/run/tts.sock"
        ),
    )
    parser.add_argument(
        "--stt-socket",
        type=Path,
        default=Path(
            "/home/kutae/.local/share/local-voice-agent/run/stt.sock"
        ),
    )
    parser.add_argument(
        "--worker-token-file",
        type=Path,
        default=Path(
            "/mnt/e/Data/LocalVoiceAgent/secrets/audio-worker-token"
        ),
    )
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--temperature", type=float, default=0.8)
    args = parser.parse_args()
    for path in (args.output_wav, args.evidence):
        if not path.is_absolute() or path.exists():
            parser.error("output paths must be absolute and must not exist")
    return args


def main() -> int:
    result = asyncio.run(run(parse_args()))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["exact_text_match"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
