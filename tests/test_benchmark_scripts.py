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


def test_vllm_omni_tts_benchmark_is_bounded_and_append_only() -> None:
    source = text("benchmark-vllm-omni-tts.py")

    ast.parse(source)
    assert '{"127.0.0.1", "localhost", "::1"}' in source
    assert "refusing to overwrite benchmark output or evidence" in source
    assert "1 <= args.runs <= 1_000" in source
    assert "1 <= args.concurrency <= 4" in source
    assert '"actual_playback_start": "not_measured_by_cli_poc"' in source


def test_salon_websocket_smoke_is_loopback_only_and_does_not_retain_pcm() -> None:
    source = text("smoke-salon-websocket.py")

    ast.parse(source)
    assert '{"127.0.0.1", "localhost", "::1"}' in source
    assert 'additional_headers={"Authorization": f"Bearer {token}"}' in source
    assert "audio.output.chunk" in source
    assert "data_base64" not in source
