#!/usr/bin/env python3
"""Persistent offline Qwen3-TTS Base voice-cloning worker."""

from __future__ import annotations

import argparse
import asyncio
import base64
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from worker_protocol import require_token, serve


SUPPORTED_STYLES = frozenset({"neutral", "happy", "dark", "advert"})


def bounded_max_new_tokens(text: str, configured_limit: int) -> int:
    if not text or not 96 <= configured_limit <= 512:
        raise ValueError("code token bound input is invalid")
    return min(configured_limit, max(96, len(text) * 4 + 48))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--voice-profiles-root", type=Path, required=True)
    parser.add_argument("--tail-silence-ms", type=int, default=160)
    parser.add_argument("--max-cached-prompts", type=int, default=4)
    parser.add_argument("--max-code-tokens", type=int, default=256)
    args = parser.parse_args()
    if not args.model.is_dir():
        parser.error("model directory does not exist")
    if not args.voice_profiles_root.is_dir():
        parser.error("voice profile directory does not exist")
    if not 0 <= args.tail_silence_ms <= 500:
        parser.error("tail silence must be between 0 and 500 ms")
    if not 1 <= args.max_cached_prompts <= 16:
        parser.error("prompt cache size must be between 1 and 16")
    if not 96 <= args.max_code_tokens <= 512:
        parser.error("max code tokens must be between 96 and 512")

    import numpy as np
    from qwen_tts import Qwen3TTSModel
    import torch

    voice_profiles_root = args.voice_profiles_root.resolve(strict=True)
    profiles_root = (voice_profiles_root / "profiles").resolve(strict=True)
    token = require_token()
    if "qwen3-tts-12hz-0.6b-base" in str(args.model).lower():
        engine_name = "qwen3-tts-12hz-0.6b-base"
    elif "qwen3-tts-12hz-1.7b-base" in str(args.model).lower():
        engine_name = "qwen3-tts-12hz-1.7b-base"
    else:
        raise ValueError("Qwen3-TTS model variant is not registered")
    model = Qwen3TTSModel.from_pretrained(
        str(args.model),
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    prompt_cache: OrderedDict[
        tuple[str, str, str], list[object]
    ] = OrderedDict()

    def handle(request: dict[str, object]) -> dict[str, object]:
        expected_fields = {
            "operation",
            "request_id",
            "text",
            "language",
            "voice_profile_id",
            "audio_prompt_path",
            "exaggeration",
            "cfg_weight",
            "temperature",
            "reference_text",
            "style",
        }
        if set(request) != expected_fields:
            raise ValueError("synthesis request fields are invalid")
        if request.get("operation") != "synthesize":
            raise ValueError("operation is unsupported")
        UUID(str(request["request_id"]))
        text = str(request["text"]).strip()
        language = str(request["language"])
        profile_id = str(request["voice_profile_id"])
        audio_prompt_path = request["audio_prompt_path"]
        reference_text = request["reference_text"]
        style = str(request["style"])
        exaggeration = float(request["exaggeration"])
        cfg_weight = float(request["cfg_weight"])
        temperature = float(request["temperature"])
        UUID(profile_id)
        if (
            not text
            or len(text) > 1_000
            or language != "ko"
            or not isinstance(audio_prompt_path, str)
            or not isinstance(reference_text, str)
            or not reference_text.strip()
            or len(reference_text) > 1_000
            or style not in SUPPORTED_STYLES
            or not 0.25 <= exaggeration <= 1.0
            or not 0.0 <= cfg_weight <= 1.0
            or not 0.5 <= temperature <= 1.2
        ):
            raise ValueError("synthesis input is invalid")

        reference = Path(audio_prompt_path)
        if (
            not reference.is_absolute()
            or reference.suffix.lower() != ".wav"
            or reference.is_symlink()
            or not reference.is_file()
        ):
            raise ValueError("reference voice path is invalid")
        resolved = reference.resolve(strict=True)
        expected = profiles_root / profile_id / "reference.wav"
        if (
            not resolved.is_relative_to(profiles_root)
            or resolved != expected.resolve(strict=True)
        ):
            raise ValueError("reference voice path does not match its profile")

        audio_digest = sha256(resolved.read_bytes()).hexdigest()
        text_digest = sha256(reference_text.encode("utf-8")).hexdigest()
        cache_key = (profile_id, audio_digest, text_digest)
        prompt = prompt_cache.get(cache_key)
        if prompt is None:
            prompt = model.create_voice_clone_prompt(
                ref_audio=str(resolved),
                ref_text=reference_text,
                x_vector_only_mode=False,
            )
            prompt_cache[cache_key] = prompt
            while len(prompt_cache) > args.max_cached_prompts:
                prompt_cache.popitem(last=False)
        else:
            prompt_cache.move_to_end(cache_key)

        max_new_tokens = bounded_max_new_tokens(text, args.max_code_tokens)
        with torch.inference_mode():
            wavs, sample_rate = model.generate_voice_clone(
                text=text,
                language="Korean",
                voice_clone_prompt=prompt,
                non_streaming_mode=False,
                temperature=temperature,
                max_new_tokens=max_new_tokens,
            )
        if len(wavs) != 1:
            raise RuntimeError("Qwen3-TTS returned an invalid batch")
        samples = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
        if samples.size == 0 or not np.isfinite(samples).all():
            raise RuntimeError("Qwen3-TTS returned invalid samples")
        pcm = (
            np.clip(samples, -1.0, 1.0) * np.float32(32767.0)
        ).astype("<i2").tobytes()
        tail_frames = round(int(sample_rate) * args.tail_silence_ms / 1_000)
        pcm += b"\x00\x00" * tail_frames
        return {
            "status": "ok",
            "request_id": request["request_id"],
            "pcm_base64": base64.b64encode(pcm).decode("ascii"),
            "sample_rate_hz": int(sample_rate),
            "channels": 1,
            "engine": engine_name,
            "style": style,
            "tail_silence_ms": args.tail_silence_ms,
            "max_new_tokens": max_new_tokens,
        }

    asyncio.run(
        serve(
            socket_path=args.socket,
            token=token,
            handler=handle,
            startup={
                "worker": "tts",
                "engine": engine_name,
                "model_path": str(args.model.resolve(strict=True)),
                "voice_profiles": True,
                "voice_profiles_root": str(voice_profiles_root),
                "reference_transcript_required": True,
                "prompt_cache_entries": args.max_cached_prompts,
                "tail_silence_ms": args.tail_silence_ms,
                "max_code_tokens": args.max_code_tokens,
                "dual_track_input": True,
                "device": "cuda",
            },
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
