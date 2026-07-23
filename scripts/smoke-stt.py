#!/usr/bin/env python3
"""Load a pinned CTranslate2 Whisper model and transcribe bounded silence."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_path", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--compute-type", required=True)
    parser.add_argument("--seconds", type=float, default=1.0)
    parser.add_argument("--audio-file", type=Path)
    args = parser.parse_args()
    if not args.model_path.is_dir():
        parser.error("model_path must be an existing directory")
    if not 0.1 <= args.seconds <= 10:
        parser.error("seconds must be between 0.1 and 10")
    if args.audio_file is not None and not args.audio_file.is_file():
        parser.error("audio_file must be an existing file")

    started = time.perf_counter()
    model = WhisperModel(
        str(args.model_path),
        device=args.device,
        compute_type=args.compute_type,
    )
    load_seconds = time.perf_counter() - started
    audio: np.ndarray | str
    if args.audio_file is None:
        audio = np.zeros(round(16_000 * args.seconds), dtype=np.float32)
    else:
        audio = str(args.audio_file)
    started = time.perf_counter()
    segments, info = model.transcribe(
        audio,
        language="ko",
        beam_size=1,
        vad_filter=False,
    )
    segment_rows = list(segments)
    transcript = "".join(segment.text for segment in segment_rows).strip()
    inference_seconds = time.perf_counter() - started
    print(
        json.dumps(
            {
                "status": "passed",
                "device": args.device,
                "compute_type": args.compute_type,
                "load_seconds": round(load_seconds, 3),
                "inference_seconds": round(inference_seconds, 3),
                "segments": len(segment_rows),
                "transcript": transcript[:500],
                "language": info.language,
                "audio_seconds": round(info.duration, 3),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
