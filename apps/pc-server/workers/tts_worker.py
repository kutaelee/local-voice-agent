#!/usr/bin/env python3
"""Persistent offline Chatterbox V3 worker with voice cloning disabled."""

from __future__ import annotations

import argparse
import asyncio
import base64
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
    args = parser.parse_args()
    if not args.model.is_dir():
        parser.error("model directory does not exist")
    token = require_token()
    model = ChatterboxMultilingualTTS.from_local(
        args.model,
        device="cuda",
        t3_model="v3",
    )

    def handle(request: dict[str, object]) -> dict[str, object]:
        if set(request) != {"operation", "request_id", "text", "language"}:
            raise ValueError("synthesis request fields are invalid")
        if request.get("operation") != "synthesize":
            raise ValueError("operation is unsupported")
        UUID(str(request["request_id"]))
        text = str(request["text"])
        language = str(request["language"])
        if not text.strip() or len(text) > 4096 or language != "ko":
            raise ValueError("synthesis input is invalid")
        with torch.inference_mode():
            audio = model.generate(text, language_id=language)
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
                "voice_cloning": False,
            },
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
