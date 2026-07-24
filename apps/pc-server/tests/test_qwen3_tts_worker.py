from __future__ import annotations

from pathlib import Path
import sys


WORKERS = Path(__file__).resolve().parents[1] / "workers"
sys.path.insert(0, str(WORKERS))

from qwen3_tts_worker import bounded_max_new_tokens  # noqa: E402


def test_qwen_code_token_bound_scales_and_caps_runaway_generation() -> None:
    assert bounded_max_new_tokens("short", 384) == 128
    assert bounded_max_new_tokens("x" * 30, 384) == 252
    assert bounded_max_new_tokens("x" * 1_000, 384) == 384
