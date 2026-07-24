from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_physical_android_qa_is_device_bound_and_privacy_preserving() -> None:
    source = (ROOT / "scripts" / "physical-android-qa.ps1").read_text(
        encoding="utf-8"
    )

    assert "C:\\Dev\\SDK\\Android\\platform-tools\\adb.exe" in source
    assert "local-voice-agent-0.6.3-debug.apk" in source
    assert (
        "4a6df7829047b0e126fd860498ecb4301f91935fd7a45382737d23d82177cf8c"
        in source
    )
    assert "Physical QA refuses emulator devices" in source
    assert "Connect exactly one authorized physical Android device" in source
    assert "pairing_token_retained = false" in source
    assert "raw_audio_retained = false" in source
    assert "full_transcript_retained = false" in source
    assert "unrelated_device_logs_retained = false" in source
    assert "logcat" not in source
    assert "pairing token" not in source.lower()


def test_physical_android_qa_covers_all_documented_cases() -> None:
    source = (ROOT / "scripts" / "physical-android-qa.ps1").read_text(
        encoding="utf-8"
    )

    for case in (
        "invalid_pairing_token",
        "microphone_permission",
        "twenty_sequential_turns",
        "speaker",
        "earpiece",
        "bluetooth",
        "barge_in",
        "background_foreground",
        "rotation",
        "network_loss",
        "replay_expiry",
        "approval_denial",
        "server_switch",
    ):
        assert case in source

    assert "Refusing to overwrite existing QA evidence" in source
    assert "Every physical QA case must have a terminal outcome" in source
    assert "Get-FileHash" in source
    assert "Write-EvidenceAtomically" in source
