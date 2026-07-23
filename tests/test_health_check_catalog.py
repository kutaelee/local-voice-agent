from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_health_check_covers_operational_wsl_runtimes() -> None:
    source = (ROOT / "scripts" / "health-check.ps1").read_text(
        encoding="utf-8"
    )

    for runtime_id in (
        "vllm-0.25.1",
        "vllm-b2b8f679d058-cu130",
        "sglang-0.5.15.post1",
        "pc-server-0.1.0",
        "faster-whisper-1.2.1",
        "silero-vad-6.2.1",
        "chatterbox-tts-0.1.7",
        "tls-tools-49.0.0",
    ):
        assert runtime_id in source

    assert "importlib.metadata" in source
    assert "pip install" not in source
    assert "Remove-Item" not in source
    assert "Start-Process" not in source
