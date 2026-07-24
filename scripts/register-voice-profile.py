#!/usr/bin/env python3
"""Register a consented local reference WAV without starting GPU services."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from local_voice_agent_server.infrastructure.voice_profiles import (
    VoiceProfileStore,
    VoiceSettings,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--playback-rate", type=float, default=1.0)
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--confirm-rights", action="store_true")
    parser.add_argument("--consent-local-processing", action="store_true")
    args = parser.parse_args()
    if not args.wav.is_absolute() or not args.wav.is_file():
        parser.error("--wav must be an existing absolute path")
    if not args.root.is_absolute():
        parser.error("--root must be an absolute path")

    store = VoiceProfileStore(args.root)
    wav_bytes = args.wav.read_bytes()
    profile = store.create_profile(
        name=args.name,
        wav_base64=base64.b64encode(wav_bytes).decode("ascii"),
        rights_confirmed=args.confirm_rights,
        local_processing_consent=args.consent_local_processing,
    )
    settings = store.update_settings(
        VoiceSettings(
            profile_id=profile.profile_id,
            playback_rate=args.playback_rate,
            exaggeration=args.exaggeration,
            cfg_weight=args.cfg_weight,
            temperature=args.temperature,
        )
    )
    print(
        json.dumps(
            {
                "profile": profile.to_dict(),
                "settings": settings.to_dict(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
