from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def script(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_installer_pins_release_archives_and_hashes() -> None:
    installer = script("install-llama-cpp.ps1")

    assert "b10092" in installer
    assert "3ce7da2c852c538c4c5f9806da27029cf8c9cc4a" in installer
    assert "6f3375d5029b677ea2049963439ee7f2b970626da42f56da34d1d203b1833875" in installer
    assert "1462a050eb4c684921ba51dcc4cc488a036674c3e73e9945ee705b854808d03e" in installer
    assert "refusing overwrite" in installer


def test_fallback_start_uses_environment_only_api_key() -> None:
    start = script("start-fallback.ps1")

    assert "$env:LLAMA_API_KEY = $apiKey" in start
    assert "Remove-Item Env:LVA_FALLBACK_API_KEY" in start
    assert "--api-key" not in start
    assert "127.0.0.1" in start
    assert "12000 MiB" in start
    assert "-CpuOnly" in start


def test_fallback_stop_validates_exact_executable() -> None:
    stop = script("stop-fallback.ps1")

    assert "$processRecord.ExecutablePath -ne $serverPath" in stop
    assert "refusing to signal" in stop
    assert "Stop-Process -Id $pidValue -Force" in stop
