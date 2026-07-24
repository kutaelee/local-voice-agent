#!/usr/bin/env python3
"""Run deterministic OpenAI-compatible API smoke checks against a local model."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import struct
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zlib


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:46322")
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--include-image", action="store_true")
    parser.add_argument(
        "--skip-thinking",
        action="store_true",
        help="Skip the optional reasoning smoke for limited fallback runtimes",
    )
    parser.add_argument(
        "--disable-thinking",
        action="store_true",
        help="Disable model reasoning for ordinary smoke requests",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--api-key-env",
        default="LVA_RUNTIME_API_KEY",
        help="Environment variable containing the bearer token",
    )
    return parser.parse_args()


def request(
    base_url: str,
    path: str,
    timeout: float,
    payload: dict[str, Any] | None = None,
    api_key: str = "",
):
    data = None
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    method = "GET"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
        method = "POST"
    req = Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        return urlopen(req, timeout=timeout)
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path}: HTTP {error.code}: {body}") from error


def request_json(
    base_url: str,
    path: str,
    timeout: float,
    payload: dict[str, Any] | None = None,
    api_key: str = "",
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    with request(base_url, path, timeout, payload, api_key) as response:
        body = response.read()
        status = response.status
    elapsed_ms = (time.perf_counter() - started) * 1000
    if status < 200 or status >= 300:
        raise RuntimeError(f"{path}: unexpected HTTP {status}")
    return json.loads(body or b"{}"), elapsed_ms


def completion_payload(
    model: str,
    prompt: str,
    *,
    disable_thinking: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 64,
    }
    if disable_thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return payload


def red_png_data_url(width: int = 32, height: int = 32) -> str:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + (b"\xff\x00\x00" * width) for _ in range(height))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def response_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("response has no message")
    return message


def run_stream(
    base_url: str,
    timeout: float,
    payload: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    payload["stream"] = True
    started = time.perf_counter()
    first_delta_ms: float | None = None
    chunks = 0
    text_parts: list[str] = []
    with request(
        base_url,
        "/v1/chat/completions",
        timeout,
        payload,
        api_key,
    ) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            event = json.loads(data)
            chunks += 1
            delta = event["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                if first_delta_ms is None:
                    first_delta_ms = (time.perf_counter() - started) * 1000
                text_parts.append(content)
    total_ms = (time.perf_counter() - started) * 1000
    text = "".join(text_parts)
    if first_delta_ms is None or not text:
        raise ValueError("stream returned no text delta")
    return {
        "status": "passed",
        "chunks": chunks,
        "ttft_ms": round(first_delta_ms, 3),
        "total_ms": round(total_ms, 3),
        "text": text,
    }


def run_thinking_stream(
    base_url: str,
    timeout: float,
    model: str,
    api_key: str,
) -> dict[str, Any]:
    payload = completion_payload(
        model,
        "시속 60km로 2.5시간 이동한 거리를 계산해.",
    )
    payload["max_tokens"] = 1024
    payload["stream"] = True
    payload["chat_template_kwargs"] = {"enable_thinking": True}
    reasoning_characters = 0
    answer_parts: list[str] = []
    chunks = 0
    started = time.perf_counter()
    with request(
        base_url,
        "/v1/chat/completions",
        timeout,
        payload,
        api_key,
    ) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            event = json.loads(data)
            chunks += 1
            delta = event["choices"][0].get("delta", {})
            reasoning = delta.get("reasoning_content")
            if reasoning:
                reasoning_characters += len(reasoning)
            content = delta.get("content")
            if content:
                answer_parts.append(content)
    total_ms = (time.perf_counter() - started) * 1000
    answer = "".join(answer_parts)
    if reasoning_characters == 0:
        raise ValueError("thinking stream returned no reasoning_content")
    if "150" not in answer:
        raise ValueError(f"thinking answer check failed: {answer!r}")
    return {
        "status": "passed",
        "chunks": chunks,
        "reasoning_characters": reasoning_characters,
        "answer": answer,
        "total_ms": round(total_ms, 3),
    }


def main() -> int:
    args = parse_args()
    api_key = os.environ.get(args.api_key_env, "")
    results: dict[str, Any] = {
        "base_url": args.base_url,
        "model": args.model,
        "started_at_unix": time.time(),
        "checks": {},
    }

    _, health_ms = request_json(
        args.base_url,
        "/health",
        args.timeout,
        api_key=api_key,
    )
    results["checks"]["health"] = {
        "status": "passed",
        "latency_ms": round(health_ms, 3),
    }

    models, models_ms = request_json(
        args.base_url,
        "/v1/models",
        args.timeout,
        api_key=api_key,
    )
    model_ids = [item.get("id") for item in models.get("data", [])]
    if args.model not in model_ids:
        raise ValueError(f"served model {args.model!r} not in {model_ids!r}")
    results["checks"]["models"] = {
        "status": "passed",
        "latency_ms": round(models_ms, 3),
        "ids": model_ids,
    }

    text_response, text_ms = request_json(
        args.base_url,
        "/v1/chat/completions",
        args.timeout,
        completion_payload(
            args.model,
            "대한민국의 수도를 한 문장으로 답해.",
            disable_thinking=args.disable_thinking,
        ),
        api_key,
    )
    text_content = str(response_message(text_response).get("content") or "")
    if "서울" not in text_content:
        raise ValueError(f"Korean text check failed: {text_content!r}")
    results["checks"]["korean_text"] = {
        "status": "passed",
        "latency_ms": round(text_ms, 3),
        "content": text_content,
    }

    tool_payload = completion_payload(
        args.model,
        "현재 GPU 상태를 확인하려면 제공된 도구를 호출해.",
        disable_thinking=args.disable_thinking,
    )
    tool_payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "inspect_gpu",
                "description": "현재 GPU 상태를 조회한다.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
    ]
    tool_response, tool_ms = request_json(
        args.base_url,
        "/v1/chat/completions",
        args.timeout,
        tool_payload,
        api_key,
    )
    tool_calls = response_message(tool_response).get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        raise ValueError("tool check returned no tool call")
    function = tool_calls[0].get("function", {})
    arguments = json.loads(function.get("arguments", "null"))
    if function.get("name") != "inspect_gpu" or arguments != {}:
        raise ValueError(f"unexpected tool call: {tool_calls[0]!r}")
    results["checks"]["tool_call"] = {
        "status": "passed",
        "latency_ms": round(tool_ms, 3),
        "name": function["name"],
        "arguments": arguments,
    }

    schema_payload = completion_payload(
        args.model,
        "대한민국의 국가명과 수도를 JSON으로 답해.",
        disable_thinking=args.disable_thinking,
    )
    schema_payload["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "country_capital",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "country": {"type": "string"},
                    "capital": {"type": "string"},
                },
                "required": ["country", "capital"],
                "additionalProperties": False,
            },
        },
    }
    schema_response, schema_ms = request_json(
        args.base_url,
        "/v1/chat/completions",
        args.timeout,
        schema_payload,
        api_key,
    )
    structured = json.loads(
        str(response_message(schema_response).get("content") or "")
    )
    if set(structured) != {"country", "capital"}:
        raise ValueError(f"structured output keys failed: {structured!r}")
    results["checks"]["structured_output"] = {
        "status": "passed",
        "latency_ms": round(schema_ms, 3),
        "value": structured,
    }

    results["checks"]["streaming"] = run_stream(
        args.base_url,
        args.timeout,
        completion_payload(
            args.model,
            "로컬 AI의 장점을 두 문장으로 설명해.",
            disable_thinking=args.disable_thinking,
        ),
        api_key,
    )
    if not args.skip_thinking:
        results["checks"]["thinking"] = run_thinking_stream(
            args.base_url,
            args.timeout,
            args.model,
            api_key,
        )

    if args.include_image:
        image_payload = completion_payload(
            args.model,
            "",
            disable_thinking=args.disable_thinking,
        )
        image_payload["messages"] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": red_png_data_url()},
                    },
                    {
                        "type": "text",
                        "text": "이 이미지의 주된 색상을 한 단어로 답해.",
                    },
                ],
            }
        ]
        image_response, image_ms = request_json(
            args.base_url,
            "/v1/chat/completions",
            args.timeout,
            image_payload,
            api_key,
        )
        image_content = str(response_message(image_response).get("content") or "")
        lowered = image_content.lower()
        if not any(token in lowered for token in ("red", "빨강", "빨간")):
            raise ValueError(f"image check failed: {image_content!r}")
        results["checks"]["image"] = {
            "status": "passed",
            "latency_ms": round(image_ms, 3),
            "content": image_content,
        }

    results["completed_at_unix"] = time.time()
    results["status"] = "passed"
    serialized = json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
