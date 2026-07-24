#!/usr/bin/env python3
"""Bind four consented same-speaker profiles for local sentence tone routing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from local_voice_agent_server.infrastructure.voice_profiles import VoiceProfileStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--neutral", required=True)
    parser.add_argument("--happy", required=True)
    parser.add_argument("--dark", required=True)
    parser.add_argument("--advert", required=True)
    args = parser.parse_args()
    if not args.root.is_absolute():
        parser.error("--root must be an absolute path")
    profiles = {
        "neutral": args.neutral,
        "happy": args.happy,
        "dark": args.dark,
        "advert": args.advert,
    }
    VoiceProfileStore(args.root).update_style_bindings(
        base_profile_id=args.neutral,
        profile_ids=profiles,
    )
    print(
        json.dumps(
            {
                "status": "configured",
                "styles": sorted(profiles),
                "profile_ids_redacted": True,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
