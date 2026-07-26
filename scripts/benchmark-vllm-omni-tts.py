#!/usr/bin/env python3
"""Measure Qwen3-TTS raw PCM streaming without involving the LLM."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import statistics
import time
from urllib.parse import urlparse
import wave

import httpx


SAMPLE_RATE_HZ = 24_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, int(len(ordered) * fraction + 0.999999) - 1))
    return ordered[position]


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "p50": round(statistics.median(values), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


async def ensure_voice(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    voice_name: str,
    reference_wav: Path,
    reference_text: str,
) -> bool:
    response = await client.get(f"{base_url}/v1/audio/voices")
    response.raise_for_status()
    existing = response.json()
    if voice_name in existing.get("voices", []):
        return False
    with reference_wav.open("rb") as handle:
        response = await client.post(
            f"{base_url}/v1/audio/voices",
            data={
                "consent": "user-provided-reference-2026-07-24",
                "name": voice_name,
                "ref_text": reference_text,
                "speaker_description": "Korean male customer-service voice",
            },
            files={"audio_sample": ("reference.wav", handle, "audio/wav")},
        )
    response.raise_for_status()
    return True


async def synthesize_once(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    voice_name: str,
    text: str,
) -> tuple[dict[str, object], bytes]:
    payload = {
        "input": text,
        "voice": voice_name,
        "language": "Korean",
        "task_type": "Base",
        "response_format": "pcm",
        "stream": True,
        "stream_format": "audio",
        "max_new_tokens": min(384, max(64, len(text) * 4)),
    }
    t5 = time.perf_counter()
    first_byte_at: float | None = None
    chunks: list[bytes] = []
    chunk_hashes: list[str] = []
    async with client.stream(
        "POST",
        f"{base_url}/v1/audio/speech",
        json=payload,
    ) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            if not chunk:
                continue
            if first_byte_at is None:
                first_byte_at = time.perf_counter()
            chunks.append(chunk)
            chunk_hashes.append(sha256(chunk).hexdigest())
    t9 = time.perf_counter()
    if first_byte_at is None:
        raise RuntimeError("TTS response contained no PCM bytes")
    pcm = b"".join(chunks)
    if len(pcm) % (CHANNELS * SAMPLE_WIDTH_BYTES):
        raise RuntimeError("TTS response is not PCM16 frame aligned")
    audio_seconds = len(pcm) / (
        SAMPLE_RATE_HZ * CHANNELS * SAMPLE_WIDTH_BYTES
    )
    repeated_adjacent_chunks = sum(
        left == right
        for left, right in zip(chunk_hashes, chunk_hashes[1:], strict=False)
    )
    nonzero_bytes = sum(value != 0 for value in pcm)
    result = {
        "server_ttfa_ms": (first_byte_at - t5) * 1_000,
        "stream_complete_ms": (t9 - t5) * 1_000,
        "audio_seconds": audio_seconds,
        "realtime_factor": (t9 - t5) / audio_seconds,
        "pcm_bytes": len(pcm),
        "http_chunks": len(chunks),
        "adjacent_duplicate_chunks": repeated_adjacent_chunks,
        "nonzero_byte_ratio": nonzero_bytes / len(pcm),
        "client_enqueue_ms": (first_byte_at - t5) * 1_000,
        "actual_playback_start_ms": None,
    }
    return result, pcm


async def run(args: argparse.Namespace) -> int:
    metadata = json.loads(args.profile_metadata.read_text(encoding="utf-8"))
    reference_text = metadata.get("reference_text")
    if not isinstance(reference_text, str) or not reference_text.strip():
        raise RuntimeError("selected voice profile has no reference transcript")
    timeout = httpx.Timeout(connect=10, read=300, write=30, pool=10)
    limits = httpx.Limits(
        max_connections=max(4, args.concurrency),
        max_keepalive_connections=max(4, args.concurrency),
    )
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        uploaded = await ensure_voice(
            client,
            base_url=args.base_url,
            voice_name=args.voice_name,
            reference_wav=args.reference_wav,
            reference_text=reference_text,
        )
        results: list[dict[str, object]] = []
        last_pcm = b""
        for start in range(0, args.runs, args.concurrency):
            count = min(args.concurrency, args.runs - start)
            batch = await asyncio.gather(
                *(
                    synthesize_once(
                        client,
                        base_url=args.base_url,
                        voice_name=args.voice_name,
                        text=args.text,
                    )
                    for _ in range(count)
                )
            )
            for result, pcm in batch:
                results.append(result)
                last_pcm = pcm

    args.output_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output_wav), "wb") as output:
        output.setnchannels(CHANNELS)
        output.setsampwidth(SAMPLE_WIDTH_BYTES)
        output.setframerate(SAMPLE_RATE_HZ)
        output.writeframes(last_pcm)
    ttfa = [float(item["server_ttfa_ms"]) for item in results]
    complete = [float(item["stream_complete_ms"]) for item in results]
    rtf = [float(item["realtime_factor"]) for item in results]
    evidence = {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "runtime": "vllm-omni-0.24.0",
        "model_id": args.model_id,
        "model_revision": args.model_revision,
        "transport": "http_raw_pcm_stream",
        "voice_uploaded_this_run": uploaded,
        "reference_audio_sha256": sha256(args.reference_wav.read_bytes()).hexdigest(),
        "runs": args.runs,
        "concurrency": args.concurrency,
        "server_ttfa_ms": summarize(ttfa),
        "stream_complete_ms": summarize(complete),
        "realtime_factor": summarize(rtf),
        "actual_playback_start": "not_measured_by_cli_poc",
        "corruption_checks": {
            "all_pcm16_frame_aligned": True,
            "adjacent_duplicate_chunks_total": sum(
                int(item["adjacent_duplicate_chunks"]) for item in results
            ),
            "minimum_nonzero_byte_ratio": min(
                float(item["nonzero_byte_ratio"]) for item in results
            ),
        },
        "samples": results,
        "output_wav": str(args.output_wav),
        "output_sha256": sha256(args.output_wav.read_bytes()).hexdigest(),
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.evidence.with_name(
        f".{args.evidence.name}.{time.time_ns()}.tmp"
    )
    temporary.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.evidence)
    print(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:46329")
    parser.add_argument("--voice-name", default="local-voice-agent-active")
    parser.add_argument(
        "--model-id",
        default="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    )
    parser.add_argument(
        "--model-revision",
        default="5d83992436eae1d760afd27aff78a71d676296fc",
    )
    parser.add_argument("--reference-wav", type=Path, required=True)
    parser.add_argument("--profile-metadata", type=Path, required=True)
    parser.add_argument("--output-wav", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--text",
        default="네, 확인해 보겠습니다. 잠시만 기다려 주세요.",
    )
    args = parser.parse_args()
    parsed_url = urlparse(args.base_url)
    if (
        parsed_url.scheme != "http"
        or parsed_url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed_url.username
        or parsed_url.password
        or parsed_url.query
        or parsed_url.fragment
    ):
        parser.error("base URL must be uncredentialed loopback HTTP")
    for path in (
        args.reference_wav,
        args.profile_metadata,
        args.output_wav,
        args.evidence,
    ):
        if not path.is_absolute():
            parser.error(f"path must be absolute: {path}")
    if not args.reference_wav.is_file() or not args.profile_metadata.is_file():
        parser.error("reference voice inputs are unavailable")
    if args.output_wav.exists() or args.evidence.exists():
        parser.error("refusing to overwrite benchmark output or evidence")
    if not 1 <= args.runs <= 1_000:
        parser.error("runs must be between 1 and 1000")
    if not 1 <= args.concurrency <= 4:
        parser.error("concurrency must be between 1 and 4")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
