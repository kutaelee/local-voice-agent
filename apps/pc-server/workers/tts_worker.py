#!/usr/bin/env python3
"""Persistent offline Chatterbox V3 worker with local voice profiles."""

from __future__ import annotations

import argparse
import asyncio
import base64
import copy
from pathlib import Path
from uuid import UUID

from chatterbox.mtl_tts import ChatterboxMultilingualTTS
import numpy as np
import torch

from worker_protocol import require_token, serve


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--voice-profiles-root", type=Path, required=True)
    args = parser.parse_args()
    if not args.model.is_dir():
        parser.error("model directory does not exist")
    if not args.voice_profiles_root.is_dir():
        parser.error("voice profile directory does not exist")
    voice_profiles_root = args.voice_profiles_root.resolve(strict=True)
    profiles_root = (voice_profiles_root / "profiles").resolve(strict=True)
    token = require_token()
    model = ChatterboxMultilingualTTS.from_local(
        args.model,
        device="cuda",
        t3_model="v3",
    )
    default_conditions = copy.deepcopy(model.conds)
    active_voice_profile_id = "default"

    def handle(request: dict[str, object]) -> dict[str, object]:
        nonlocal active_voice_profile_id
        legacy_fields = {"operation", "request_id", "text", "language"}
        profile_fields = legacy_fields | {
            "voice_profile_id",
            "audio_prompt_path",
            "exaggeration",
            "cfg_weight",
            "temperature",
        }
        request_fields = frozenset(request)
        if request_fields not in {
            frozenset(legacy_fields),
            frozenset(profile_fields),
        }:
            raise ValueError("synthesis request fields are invalid")
        if request.get("operation") != "synthesize":
            raise ValueError("operation is unsupported")
        UUID(str(request["request_id"]))
        text = str(request["text"])
        language = str(request["language"])
        if not text.strip() or len(text) > 4096 or language != "ko":
            raise ValueError("synthesis input is invalid")
        voice_profile_id = str(request.get("voice_profile_id", "default"))
        audio_prompt_path = request.get("audio_prompt_path")
        exaggeration = float(request.get("exaggeration", 0.5))
        cfg_weight = float(request.get("cfg_weight", 0.5))
        temperature = float(request.get("temperature", 0.8))
        if voice_profile_id != "default":
            UUID(voice_profile_id)
        if (
            not 0.25 <= exaggeration <= 1.0
            or not 0.0 <= cfg_weight <= 1.0
            or not 0.5 <= temperature <= 1.2
        ):
            raise ValueError("synthesis controls are invalid")

        prompt: str | None = None
        if voice_profile_id == "default":
            if audio_prompt_path is not None:
                raise ValueError("default voice cannot include an audio prompt")
            if active_voice_profile_id != "default":
                active_voice_profile_id = "__conditioning__"
                model.conds = copy.deepcopy(default_conditions)
        else:
            if not isinstance(audio_prompt_path, str):
                raise ValueError("reference voice path is required")
            candidate = Path(audio_prompt_path)
            if (
                not candidate.is_absolute()
                or candidate.suffix.lower() != ".wav"
                or candidate.is_symlink()
                or not candidate.is_file()
            ):
                raise ValueError("reference voice path is invalid")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(profiles_root):
                raise ValueError("reference voice path escaped the profile root")
            expected = profiles_root / voice_profile_id / "reference.wav"
            if resolved != expected.resolve(strict=True):
                raise ValueError("reference voice path does not match its profile")
            if active_voice_profile_id != voice_profile_id:
                active_voice_profile_id = "__conditioning__"
                prompt = str(resolved)
        with torch.inference_mode():
            audio = model.generate(
                text,
                language_id=language,
                audio_prompt_path=prompt,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
                temperature=temperature,
            )
        active_voice_profile_id = voice_profile_id
        samples = audio.squeeze(0).detach().cpu().float().numpy()
        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        return {
            "status": "ok",
            "request_id": request["request_id"],
            "pcm_base64": base64.b64encode(pcm).decode("ascii"),
            "sample_rate_hz": model.sr,
            "channels": 1,
        }

    asyncio.run(
        serve(
            socket_path=args.socket,
            token=token,
            handler=handle,
            startup={
                "component": "tts-worker",
                "model_path": str(args.model),
                "variant": "v3",
                "voice_profiles": True,
                "voice_profiles_root": str(voice_profiles_root),
            },
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
