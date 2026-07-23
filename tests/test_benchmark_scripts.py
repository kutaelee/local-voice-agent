from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_latency_benchmark_has_korean_prompts_and_no_replace_output() -> None:
    source = text("benchmark-openai-latency.py")

    ast.parse(source)
    assert "로컬 AI의 장점을" in source
    assert 'args.output.open("x"' in source
    assert '"temperature": 0' in source
    assert '"concurrency": 1' in source


def test_benchmark_wrapper_is_loopback_only_and_never_controls_runtime() -> None:
    source = text("benchmark.ps1")

    assert "'localhost', '127.0.0.1', '::1'" in source
    assert "Refusing to overwrite benchmark evidence" in source
    assert "E:\\Data\\LocalVoiceAgent\\benchmarks\\results" in source
    assert "start-vllm" not in source
    assert "stop-vllm" not in source
    assert "start-sglang" not in source
    assert "stop-sglang" not in source
