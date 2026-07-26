#!/usr/bin/env python3
"""Register consented local voice profiles with loopback vLLM-Omni."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlparse

import httpx


def _profile(profile_dir: Path) -> tuple[str, Path, str] | None:
    if profile_dir.is_symlink():
        raise RuntimeError(f"voice profile directory is a symlink: {profile_dir}")
    metadata_path = profile_dir / "metadata.json"
    reference_path = profile_dir / "reference.wav"
    if not metadata_path.is_file() or not reference_path.is_file():
        return None
    if metadata_path.is_symlink() or reference_path.is_symlink():
        raise RuntimeError(f"voice profile contains a symlink: {profile_dir}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    profile_id = metadata.get("profile_id")
    reference_text = metadata.get("reference_text")
    expected_digest = metadata.get("sha256")
    if not isinstance(profile_id, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,95}",
        profile_id,
    ):
        raise RuntimeError(f"invalid voice profile ID: {profile_dir}")
    if not isinstance(reference_text, str) or not reference_text.strip():
        return None
    actual_digest = sha256(reference_path.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise RuntimeError(f"voice profile digest mismatch: {profile_id}")
    return f"lva-{profile_id}", reference_path, reference_text.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles-root", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    parsed = urlparse(args.base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
    ):
        parser.error("base URL must be uncredentialed loopback HTTP")
    root = args.profiles_root.resolve(strict=True)
    if not root.is_dir():
        parser.error("profiles root must be a directory")

    registered: list[str] = []
    timeout = httpx.Timeout(connect=5, read=60, write=60, pool=5)
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=timeout) as client:
        health = client.get("/health")
        health.raise_for_status()
        for profile_dir in sorted(root.iterdir()):
            if not profile_dir.is_dir():
                continue
            value = _profile(profile_dir)
            if value is None:
                continue
            voice_name, reference_path, reference_text = value
            with reference_path.open("rb") as reference:
                response = client.post(
                    "/v1/audio/voices",
                    data={
                        "consent": f"local-profile-{profile_dir.name}",
                        "name": voice_name,
                        "ref_text": reference_text,
                        "speaker_description": "consented local voice profile",
                    },
                    files={
                        "audio_sample": (
                            "reference.wav",
                            reference,
                            "audio/wav",
                        )
                    },
                )
            response.raise_for_status()
            registered.append(voice_name)

        voices = client.get("/v1/audio/voices")
        voices.raise_for_status()
        available = set(voices.json().get("voices", []))
        missing = sorted(set(registered) - available)
        if missing:
            raise RuntimeError(f"registered voices not listed: {missing}")

    print(
        json.dumps(
            {"registered_count": len(registered), "voices": registered},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
