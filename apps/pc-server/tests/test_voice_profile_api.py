from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import wave

from fastapi.testclient import TestClient

from local_voice_agent_server.api import ServerSettings, create_app
from local_voice_agent_server.infrastructure.voice_profiles import (
    VoiceProfileStore,
)


TOKEN = "voice-profile-test-token-with-32-characters"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def reference_wav() -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\x00\x00" * 24_000 * 4)
    return output.getvalue()


def test_voice_profile_api_requires_pairing_token(tmp_path: Path) -> None:
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        voice_profile_store=VoiceProfileStore(tmp_path / "voices"),
    )
    api = TestClient(app)
    valid_profile = {
        "name": "Not authorized",
        "wav_base64": base64.b64encode(reference_wav()).decode("ascii"),
        "rights_confirmed": True,
        "local_processing_consent": True,
    }
    valid_settings = {
        "profile_id": "default",
        "playback_rate": 1.0,
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "temperature": 0.8,
    }

    assert api.get("/v1/voice/profiles").status_code == 401
    assert api.post(
        "/v1/voice/profiles",
        json=valid_profile,
    ).status_code == 401
    assert api.put(
        "/v1/voice/settings",
        json=valid_settings,
    ).status_code == 401


def test_voice_profile_api_registers_and_selects_reference(
    tmp_path: Path,
) -> None:
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        voice_profile_store=VoiceProfileStore(tmp_path / "voices"),
    )
    with TestClient(app) as api:
        created = api.post(
            "/v1/voice/profiles",
            headers=HEADERS,
            json={
                "name": "User-owned Korean neutral voice",
                "wav_base64": base64.b64encode(reference_wav()).decode("ascii"),
                "rights_confirmed": True,
                "local_processing_consent": True,
            },
        )
        profile_id = created.json()["profile"]["profile_id"]
        updated = api.put(
            "/v1/voice/settings",
            headers=HEADERS,
            json={
                "profile_id": profile_id,
                "playback_rate": 1.1,
                "exaggeration": 0.5,
                "cfg_weight": 0.5,
                "temperature": 0.8,
            },
        )
        catalog = api.get("/v1/voice/profiles", headers=HEADERS)

    assert created.status_code == 201
    assert updated.status_code == 200
    assert catalog.status_code == 200
    assert len(catalog.json()["profiles"]) == 2
    assert catalog.json()["settings"] == {
        "profile_id": profile_id,
        "playback_rate": 1.1,
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "temperature": 0.8,
    }


def test_voice_profile_api_rejects_unconsented_audio(tmp_path: Path) -> None:
    app = create_app(
        ServerSettings(pairing_token=TOKEN),
        voice_profile_store=VoiceProfileStore(tmp_path / "voices"),
    )
    response = TestClient(app).post(
        "/v1/voice/profiles",
        headers=HEADERS,
        json={
            "name": "No consent",
            "wav_base64": base64.b64encode(reference_wav()).decode("ascii"),
            "rights_confirmed": False,
            "local_processing_consent": True,
        },
    )

    assert response.status_code == 422
