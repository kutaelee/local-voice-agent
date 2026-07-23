#!/usr/bin/env python3
"""Measure fixed single-request latency against a loopback OpenAI chat API."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any
from urllib.request import Request, urlopen


PROMPTS = (
    ("conversation-01", "로컬 AI의 장점을 정확히 두 문장으로 설명해."),
    ("conversation-02", "대한민국의 수도와 대표적인 강 하나를 설명해."),
    ("development-01", "테스트가 간헐적으로 실패할 때 확인할 항목을 세 가지로 요약해."),
    ("planning-01", "파일을 안전하게 수정하고 검증하는 절차를 네 단계로 정리해."),
    ("recovery-01", "모델 로딩 실패 후 안전한 복구 순서를 간단히 설명해."),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--api-key-env", default="LVA_RUNTIME_API_KEY")
    parser.add_argument("--mtp-enabled", action="store_true")
    parser.add_argument("--mtp-config", default="disabled")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 1 or args.samples > 100:
        parser.error("--samples must be between 1 and 100")
    if args.max_tokens < 8 or args.max_tokens > 4096:
        parser.error("--max-tokens must be between 8 and 4096")
    return args


def gpu_snapshot() -> dict[str, int | str]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    values = [value.strip() for value in completed.stdout.strip().split(",")]
    if len(values) != 5:
        raise ValueError(f"Unexpected nvidia-smi output: {completed.stdout!r}")
    return {
        "name": values[0],
        "memory_total_mib": int(values[1]),
        "memory_used_mib": int(values[2]),
        "memory_free_mib": int(values[3]),
        "utilization_percent": int(values[4]),
    }


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (
        position - lower
    )


def request_sample(
    *,
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    timeout: float,
    api_key: str,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json; charset=utf-8",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    started = time.perf_counter()
    first_token_at: float | None = None
    text_parts: list[str] = []
    usage: dict[str, Any] = {}
    with urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            event = json.loads(data)
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                text_parts.append(content)
    completed_at = time.perf_counter()

    if first_token_at is None or not text_parts:
        raise ValueError("Streaming sample returned no content token")
    completion_tokens = usage.get("completion_tokens")
    prompt_tokens = usage.get("prompt_tokens")
    if not isinstance(completion_tokens, int) or completion_tokens < 1:
        raise ValueError(f"Streaming sample returned invalid usage: {usage!r}")
    if not isinstance(prompt_tokens, int) or prompt_tokens < 1:
        raise ValueError(f"Streaming sample returned invalid usage: {usage!r}")

    ttft_ms = (first_token_at - started) * 1000
    total_ms = (completed_at - started) * 1000
    decode_ms = max(total_ms - ttft_ms, 0.001)
    return {
        "ttft_ms": round(ttft_ms, 3),
        "total_ms": round(total_ms, 3),
        "tpot_ms": round(
            decode_ms / max(completion_tokens - 1, 1),
            3,
        ),
        "output_tokens_per_second": round(
            completion_tokens / (decode_ms / 1000),
            3,
        ),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "output_characters": sum(len(part) for part in text_parts),
    }


def aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = (
        "ttft_ms",
        "total_ms",
        "tpot_ms",
        "output_tokens_per_second",
    )
    result: dict[str, Any] = {"successful_samples": len(samples)}
    for metric in metrics:
        values = [float(sample[metric]) for sample in samples]
        result[metric] = {
            "mean": round(statistics.fmean(values), 3),
            "p50": round(percentile(values, 0.50), 3),
            "p95": round(percentile(values, 0.95), 3),
        }
    return result


def main() -> int:
    args = parse_args()
    api_key = os.environ.get(args.api_key_env, "")
    started_at = time.time()
    before = gpu_snapshot()
    samples: list[dict[str, Any]] = []
    for index in range(args.samples):
        prompt_id, prompt = PROMPTS[index % len(PROMPTS)]
        sample = request_sample(
            base_url=args.base_url,
            model=args.model,
            prompt=prompt,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
            api_key=api_key,
        )
        sample["index"] = index
        sample["prompt_id"] = prompt_id
        samples.append(sample)
    after = gpu_snapshot()
    result = {
        "schema_version": "1.0",
        "status": "passed",
        "runtime": args.runtime,
        "condition": args.condition,
        "model": args.model,
        "model_revision": args.model_revision,
        "mtp_enabled": args.mtp_enabled,
        "mtp_config": args.mtp_config,
        "fixed_conditions": {
            "samples": args.samples,
            "max_tokens": args.max_tokens,
            "temperature": 0,
            "concurrency": 1,
            "stream": True,
            "prompt_catalog": [prompt_id for prompt_id, _ in PROMPTS],
        },
        "started_at_unix": started_at,
        "completed_at_unix": time.time(),
        "gpu_before": before,
        "gpu_after": after,
        "samples": samples,
        "aggregate": aggregate(samples),
    }
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
