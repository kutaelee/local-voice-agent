#!/usr/bin/env python3
"""Run bounded salon-only FAQ checks against the registered local vLLM API."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import perf_counter

from local_voice_agent_server.infrastructure.salon_config import load_salon_policy
from local_voice_agent_server.infrastructure.salon_vllm_faq import (
    SalonVllmFaqAdapter,
)


CASES = (
    ("친구와 두 명이 같은 시간에 커트를 받을 수 있나요?", True),
    ("예약은 며칠 뒤까지 받을 수 있나요?", True),
    ("염색 시간과 가격을 알려주세요.", True),
    ("주차가 가능한가요?", True),
    ("내일 서울 날씨를 알려주세요.", False),
    ("지금 살 만한 주식을 추천해 주세요.", False),
)


async def run(args: argparse.Namespace) -> dict[str, object]:
    api_key = os.environ.get("LVA_VLLM_API_KEY", "")
    adapter = SalonVllmFaqAdapter(
        policy=load_salon_policy(args.policy),
        base_url=args.base_url,
        model=args.model,
        api_key=api_key,
        timeout_seconds=args.timeout_seconds,
    )
    results = []
    passed = True
    for question, expected_scope in CASES:
        started = perf_counter()
        decision = await adapter.answer(question)
        latency_ms = round((perf_counter() - started) * 1000, 3)
        case_passed = (
            decision.in_scope is expected_scope
            and (not expected_scope or bool(decision.answer))
            and (expected_scope or decision.answer == "")
        )
        passed = passed and case_passed
        results.append(
            {
                "question": question,
                "expected_in_scope": expected_scope,
                "actual_in_scope": decision.in_scope,
                "answer": decision.answer,
                "latency_ms": latency_ms,
                "passed": case_passed,
            }
        )
    return {
        "schema_version": "1.0",
        "status": "passed" if passed else "failed",
        "model": args.model,
        "base_url": args.base_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cases": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(
            "/mnt/c/Dev/Repos/local-voice-agent/configs/salon-booking.json"
        ),
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:46322/v1",
    )
    parser.add_argument("--model", default="gemma4-12b")
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "cases": len(result["cases"]),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
