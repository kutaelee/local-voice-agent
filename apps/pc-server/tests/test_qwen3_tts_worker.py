from __future__ import annotations

from pathlib import Path
import sys


WORKERS = Path(__file__).resolve().parents[1] / "workers"
sys.path.insert(0, str(WORKERS))

from qwen3_tts_worker import (  # noqa: E402
    bounded_max_new_tokens,
    stable_speaker_seed,
)


def test_qwen_code_token_bound_scales_and_caps_runaway_generation() -> None:
    assert bounded_max_new_tokens("short", 384) == 128
    assert bounded_max_new_tokens("x" * 30, 384) == 252
    assert bounded_max_new_tokens("x" * 1_000, 384) == 384


def test_qwen_speaker_seed_is_stable_per_profile() -> None:
    first = "0a482ccb-ec37-4e4c-aef6-44c999c61c77"
    second = "5b15d8d3-396e-4cdb-bde9-28061bbdea26"

    assert stable_speaker_seed(first) == stable_speaker_seed(first)
    assert stable_speaker_seed(first) != stable_speaker_seed(second)
    assert 0 <= stable_speaker_seed(first) < 2**63
