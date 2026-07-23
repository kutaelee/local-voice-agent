#!/usr/bin/env python3
"""Load pinned Chatterbox V3 weights and synthesize a bounded Korean sample."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import soundfile
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_path", type=Path)
    parser.add_argument("output_wav", type=Path)
    parser.add_argument("--text", default="안녕하세요. 로컬 음성 에이전트입니다.")
    args = parser.parse_args()
    if not args.model_path.is_dir():
        parser.error("model_path must be an existing directory")
    if not 1 <= len(args.text) <= 200:
        parser.error("text length must be between 1 and 200")

    torch.manual_seed(0)
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = ChatterboxMultilingualTTS.from_local(
        args.model_path,
        device="cuda",
        t3_model="v3",
    )
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    audio = model.generate(args.text, language_id="ko")
    synthesis_seconds = time.perf_counter() - started
    args.output_wav.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(
        str(args.output_wav),
        audio.squeeze(0).detach().cpu().numpy(),
        model.sr,
        subtype="PCM_16",
    )
    audio_seconds = audio.shape[-1] / model.sr
    payload = args.output_wav.read_bytes()
    print(
        json.dumps(
            {
                "status": "passed",
                "model_variant": "v3",
                "language": "ko",
                "sample_rate_hz": model.sr,
                "audio_seconds": round(audio_seconds, 3),
                "load_seconds": round(load_seconds, 3),
                "synthesis_seconds": round(synthesis_seconds, 3),
                "realtime_factor": round(synthesis_seconds / audio_seconds, 3),
                "peak_vram_bytes": torch.cuda.max_memory_allocated(),
                "output_bytes": len(payload),
                "output_sha256": hashlib.sha256(payload).hexdigest(),
                "output_path": str(args.output_wav),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
