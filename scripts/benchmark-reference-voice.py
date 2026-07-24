#!/usr/bin/env python3
"""One-shot local reference-voice smoke without an LLM server."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import time
import wave

from chatterbox.mtl_tts import ChatterboxMultilingualTTS
import torch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--reference-wav", type=Path, required=True)
    parser.add_argument("--text-file", type=Path, required=True)
    parser.add_argument("--output-wav", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--profile-label", required=True)
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--temperature", type=float, default=0.8)
    args = parser.parse_args()
    for path in (args.model, args.reference_wav, args.text_file):
        if not path.is_absolute() or not path.exists():
            parser.error(f"input path is unavailable: {path}")
    for path in (args.output_wav, args.evidence):
        if not path.is_absolute():
            parser.error(f"output path must be absolute: {path}")
        if path.exists():
            parser.error(f"refusing to overwrite output: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

    text_bytes = args.text_file.read_bytes()
    text = text_bytes.decode("utf-8-sig").strip()
    if not text or len(text) > 4096:
        parser.error("test text is empty or too long")
    reference_bytes = args.reference_wav.read_bytes()

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    model = ChatterboxMultilingualTTS.from_local(
        args.model,
        device="cuda",
        t3_model="v3",
    )
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started

    synthesis_started = time.perf_counter()
    with torch.inference_mode():
        audio = model.generate(
            text,
            language_id="ko",
            audio_prompt_path=str(args.reference_wav),
            exaggeration=args.exaggeration,
            cfg_weight=args.cfg_weight,
            temperature=args.temperature,
        )
    torch.cuda.synchronize()
    synthesis_seconds = time.perf_counter() - synthesis_started
    samples = (
        audio.squeeze(0)
        .detach()
        .cpu()
        .clamp(-1.0, 1.0)
        .mul(32767.0)
        .to(torch.int16)
        .numpy()
        .astype("<i2", copy=False)
        .tobytes()
    )
    with wave.open(str(args.output_wav), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(model.sr)
        output.writeframes(samples)
    output_bytes = args.output_wav.read_bytes()
    audio_seconds = audio.shape[-1] / model.sr
    evidence = {
        "schema_version": "1.0",
        "test": "chatterbox_reference_voice_smoke",
        "created_at": datetime.now(UTC).isoformat(),
        "profile_id": args.profile_id,
        "profile_label": args.profile_label,
        "model_path": str(args.model),
        "reference_sha256": sha256(reference_bytes).hexdigest(),
        "text_sha256": sha256(text_bytes).hexdigest(),
        "text_characters": len(text),
        "parameters": {
            "language": "ko",
            "exaggeration": args.exaggeration,
            "cfg_weight": args.cfg_weight,
            "temperature": args.temperature,
        },
        "measurements": {
            "model_load_seconds": round(load_seconds, 3),
            "synthesis_seconds": round(synthesis_seconds, 3),
            "audio_seconds": round(audio_seconds, 3),
            "realtime_factor": round(synthesis_seconds / audio_seconds, 3),
            "peak_allocated_vram_bytes": torch.cuda.max_memory_allocated(),
        },
        "output": {
            "path": str(args.output_wav),
            "sha256": sha256(output_bytes).hexdigest(),
            "size_bytes": len(output_bytes),
            "sample_rate_hz": model.sr,
            "channels": int(audio.shape[0]),
        },
        "validation_status": "synthesis_completed_physical_listening_pending",
    }
    temporary = args.evidence.with_name(
        f".{args.evidence.name}.{time.time_ns()}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
            )
        temporary.replace(args.evidence)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
