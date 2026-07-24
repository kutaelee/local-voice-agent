from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import wave

import pytest

from local_voice_agent_server.infrastructure.voice_profiles import (
    DEFAULT_PROFILE_ID,
    VoiceProfileError,
    VoiceProfileStore,
    VoiceSettings,
)


def reference_wav(*, seconds: int = 4, sample_rate: int = 24_000) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * sample_rate * seconds)
    return output.getvalue()


def create_profile(store: VoiceProfileStore) -> str:
    profile = store.create_profile(
        name="My Korean voice",
        wav_base64=base64.b64encode(reference_wav()).decode("ascii"),
        rights_confirmed=True,
        local_processing_consent=True,
    )
    return profile.profile_id


def test_reference_profile_is_local_hashed_and_selectable(tmp_path: Path) -> None:
    store = VoiceProfileStore(tmp_path / "voice-profiles")

    profile_id = create_profile(store)
    selected = store.update_settings(
        VoiceSettings(
            profile_id=profile_id,
            playback_rate=1.15,
            exaggeration=0.7,
            cfg_weight=0.3,
            temperature=0.8,
        )
    )
    profiles = store.list_profiles()
    options = store.synthesis_options()

    assert profiles[0].profile_id == DEFAULT_PROFILE_ID
    assert profiles[0].is_default is True
    assert profiles[1].profile_id == profile_id
    assert profiles[1].sha256 is not None
    assert profiles[1].duration_ms == 4_000
    assert selected == store.get_settings()
    assert options.profile_id == profile_id
    assert options.reference_audio_path == (
        tmp_path
        / "voice-profiles"
        / "profiles"
        / profile_id
        / "reference.wav"
    ).resolve()
    assert options.exaggeration == 0.7
    assert options.cfg_weight == 0.3
    assert options.temperature == 0.8


@pytest.mark.parametrize(
    ("rights_confirmed", "local_processing_consent"),
    ((False, True), (True, False), (False, False)),
)
def test_reference_profile_requires_both_consents(
    tmp_path: Path,
    rights_confirmed: bool,
    local_processing_consent: bool,
) -> None:
    store = VoiceProfileStore(tmp_path / "voice-profiles")

    with pytest.raises(VoiceProfileError, match="consent"):
        store.create_profile(
            name="Unapproved",
            wav_base64=base64.b64encode(reference_wav()).decode("ascii"),
            rights_confirmed=rights_confirmed,
            local_processing_consent=local_processing_consent,
        )


@pytest.mark.parametrize("seconds", (1, 31))
def test_reference_profile_rejects_unsafe_duration(
    tmp_path: Path,
    seconds: int,
) -> None:
    store = VoiceProfileStore(tmp_path / "voice-profiles")

    with pytest.raises(VoiceProfileError, match="duration"):
        store.create_profile(
            name="Invalid duration",
            wav_base64=base64.b64encode(
                reference_wav(seconds=seconds)
            ).decode("ascii"),
            rights_confirmed=True,
            local_processing_consent=True,
        )


def test_settings_reject_unknown_profile(tmp_path: Path) -> None:
    store = VoiceProfileStore(tmp_path / "voice-profiles")

    with pytest.raises(VoiceProfileError):
        store.update_settings(
            VoiceSettings(profile_id="8cf8b3df-2589-408a-a1fa-0df84824968e")
        )


def test_selected_reference_integrity_is_rechecked(tmp_path: Path) -> None:
    store = VoiceProfileStore(tmp_path / "voice-profiles")
    profile_id = create_profile(store)
    store.update_settings(VoiceSettings(profile_id=profile_id))
    reference = (
        tmp_path
        / "voice-profiles"
        / "profiles"
        / profile_id
        / "reference.wav"
    )
    reference.write_bytes(reference.read_bytes() + b"tampered")

    with pytest.raises(VoiceProfileError, match="integrity"):
        store.synthesis_options()
