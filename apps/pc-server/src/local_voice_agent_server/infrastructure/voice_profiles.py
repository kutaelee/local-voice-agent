"""Local-only reference voice profiles and synthesis settings."""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import wave
from uuid import UUID, uuid4


MAX_REFERENCE_BYTES = 8 * 1024 * 1024
MIN_REFERENCE_SECONDS = 3.0
MAX_REFERENCE_SECONDS = 30.0
MAX_REFERENCE_TEXT_CHARS = 1_000
DEFAULT_PROFILE_ID = "default"
_PROFILE_NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,64}$")
_REFERENCE_TEXT = re.compile(r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+$")
VOICE_STYLES = frozenset({"neutral", "happy", "dark", "advert"})


class VoiceProfileError(ValueError):
    """A reference voice or settings update failed closed."""


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    profile_id: str
    name: str
    is_default: bool
    created_at: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    duration_ms: int | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    style: str = "neutral"
    reference_text: str | None = None

    def to_dict(self) -> dict[str, object]:
        public = {
            key: value
            for key, value in asdict(self).items()
            if value is not None and key != "reference_text"
        }
        public["has_reference_text"] = self.reference_text is not None
        return public

    def to_metadata_dict(self) -> dict[str, object]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    profile_id: str = DEFAULT_PROFILE_ID
    playback_rate: float = 1.0
    exaggeration: float = 0.5
    cfg_weight: float = 0.5
    temperature: float = 0.8

    def __post_init__(self) -> None:
        if self.profile_id != DEFAULT_PROFILE_ID:
            UUID(self.profile_id)
        if not 0.85 <= self.playback_rate <= 1.25:
            raise VoiceProfileError("playback rate must be between 0.85 and 1.25")
        if not 0.25 <= self.exaggeration <= 1.0:
            raise VoiceProfileError("exaggeration must be between 0.25 and 1.0")
        if not 0.0 <= self.cfg_weight <= 1.0:
            raise VoiceProfileError("CFG weight must be between 0 and 1")
        if not 0.5 <= self.temperature <= 1.2:
            raise VoiceProfileError("temperature must be between 0.5 and 1.2")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VoiceSynthesisOptions:
    profile_id: str
    reference_audio_path: Path | None
    exaggeration: float
    cfg_weight: float
    temperature: float
    reference_text: str | None
    style: str


class VoiceProfileStore:
    """Stores consented reference clips outside the source repository."""

    def __init__(
        self,
        root: Path,
        *,
        enable_style_routing: bool = True,
    ) -> None:
        if not root.is_absolute():
            raise VoiceProfileError("voice profile root must be absolute")
        self._root = root
        self._profiles_root = root / "profiles"
        self._settings_path = root / "settings.json"
        self._style_bindings_path = root / "style-bindings.json"
        self._enable_style_routing = enable_style_routing
        self._profiles_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @property
    def root(self) -> Path:
        return self._root

    def list_profiles(self) -> tuple[VoiceProfile, ...]:
        profiles = [
            VoiceProfile(
                profile_id=DEFAULT_PROFILE_ID,
                name="Default Korean",
                is_default=True,
            )
        ]
        for metadata_path in sorted(self._profiles_root.glob("*/metadata.json")):
            profiles.append(self._read_profile(metadata_path))
        return tuple(profiles)

    def get_settings(self) -> VoiceSettings:
        if not self._settings_path.exists():
            return VoiceSettings()
        try:
            value = json.loads(self._settings_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or set(value) != {
                "profile_id",
                "playback_rate",
                "exaggeration",
                "cfg_weight",
                "temperature",
            }:
                raise VoiceProfileError("voice settings file is invalid")
            settings = VoiceSettings(
                profile_id=str(value["profile_id"]),
                playback_rate=float(value["playback_rate"]),
                exaggeration=float(value["exaggeration"]),
                cfg_weight=float(value["cfg_weight"]),
                temperature=float(value["temperature"]),
            )
        except (OSError, json.JSONDecodeError, TypeError, VoiceProfileError) as error:
            raise VoiceProfileError("voice settings file is invalid") from error
        self._require_profile(settings.profile_id)
        return settings

    def update_settings(self, settings: VoiceSettings) -> VoiceSettings:
        self._require_profile(settings.profile_id)
        self._atomic_json(self._settings_path, settings.to_dict())
        return settings

    def create_profile(
        self,
        *,
        name: str,
        wav_base64: str,
        rights_confirmed: bool,
        local_processing_consent: bool,
        reference_text: str | None = None,
        style: str = "neutral",
    ) -> VoiceProfile:
        normalized_name = name.strip()
        if not _PROFILE_NAME.fullmatch(normalized_name):
            raise VoiceProfileError("voice profile name is invalid")
        if not rights_confirmed or not local_processing_consent:
            raise VoiceProfileError(
                "voice ownership and local processing consent are required"
            )
        normalized_reference_text = _normalize_reference_text(reference_text)
        if style not in VOICE_STYLES:
            raise VoiceProfileError("voice profile style is invalid")
        try:
            wav_bytes = base64.b64decode(wav_base64, validate=True)
        except (ValueError, binascii.Error) as error:
            raise VoiceProfileError("reference audio is not valid base64") from error
        if not 0 < len(wav_bytes) <= MAX_REFERENCE_BYTES:
            raise VoiceProfileError("reference audio size is invalid")
        sample_rate, channels, duration_ms = _validate_reference_wav(wav_bytes)

        profile_id = str(uuid4())
        profile_root = self._profiles_root / profile_id
        profile_root.mkdir(mode=0o700)
        audio_path = profile_root / "reference.wav"
        metadata_path = profile_root / "metadata.json"
        try:
            _atomic_bytes(audio_path, wav_bytes)
            profile = VoiceProfile(
                profile_id=profile_id,
                name=normalized_name,
                is_default=False,
                created_at=datetime.now(UTC).isoformat(),
                sha256=sha256(wav_bytes).hexdigest(),
                size_bytes=len(wav_bytes),
                duration_ms=duration_ms,
                sample_rate_hz=sample_rate,
                channels=channels,
                style=style,
                reference_text=normalized_reference_text,
            )
            self._atomic_json(metadata_path, profile.to_metadata_dict())
        except Exception:
            audio_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            try:
                profile_root.rmdir()
            except OSError:
                pass
            raise
        return profile

    def synthesis_options(self, text: str = "") -> VoiceSynthesisOptions:
        settings = self.get_settings()
        profile_id = self._routed_profile_id(
            base_profile_id=settings.profile_id,
            text=text,
        )
        profile = (
            None
            if profile_id == DEFAULT_PROFILE_ID
            else self._read_profile(
                self._profile_root(profile_id) / "metadata.json"
            )
        )
        return VoiceSynthesisOptions(
            profile_id=profile_id,
            reference_audio_path=self.reference_path(profile_id),
            exaggeration=settings.exaggeration,
            cfg_weight=settings.cfg_weight,
            temperature=settings.temperature,
            reference_text=profile.reference_text if profile else None,
            style=profile.style if profile else "neutral",
        )

    def update_style_bindings(
        self,
        *,
        base_profile_id: str,
        profile_ids: dict[str, str],
    ) -> None:
        if set(profile_ids) != VOICE_STYLES:
            raise VoiceProfileError("all voice styles must be bound")
        self._require_profile(base_profile_id)
        for style, profile_id in profile_ids.items():
            self._require_profile(profile_id)
            profile = self._read_profile(
                self._profile_root(profile_id) / "metadata.json"
            )
            if profile.style != style or profile.reference_text is None:
                raise VoiceProfileError("voice style binding does not match metadata")
        if profile_ids["neutral"] != base_profile_id:
            raise VoiceProfileError("neutral style must be the base profile")
        self._atomic_json(
            self._style_bindings_path,
            {
                "base_profile_id": base_profile_id,
                "profiles": profile_ids,
            },
        )

    def reference_path(self, profile_id: str) -> Path | None:
        if profile_id == DEFAULT_PROFILE_ID:
            return None
        profile_root = self._profile_root(profile_id)
        reference = profile_root / "reference.wav"
        if reference.is_symlink() or not reference.is_file():
            raise VoiceProfileError("reference audio is unavailable")
        resolved = reference.resolve(strict=True)
        if not resolved.is_relative_to(self._profiles_root.resolve(strict=True)):
            raise VoiceProfileError("reference audio escaped the profile root")
        return resolved

    def _require_profile(self, profile_id: str) -> None:
        if profile_id == DEFAULT_PROFILE_ID:
            return
        profile = self._read_profile(
            self._profile_root(profile_id) / "metadata.json"
        )
        reference = self.reference_path(profile_id)
        reference_bytes = reference.read_bytes()
        if (
            len(reference_bytes) != profile.size_bytes
            or sha256(reference_bytes).hexdigest() != profile.sha256
        ):
            raise VoiceProfileError("reference audio integrity check failed")

    def _routed_profile_id(self, *, base_profile_id: str, text: str) -> str:
        if (
            not self._enable_style_routing
            or not text
            or not self._style_bindings_path.exists()
        ):
            return base_profile_id
        try:
            value = json.loads(
                self._style_bindings_path.read_text(encoding="utf-8")
            )
            if (
                not isinstance(value, dict)
                or set(value) != {"base_profile_id", "profiles"}
                or value["base_profile_id"] != base_profile_id
                or not isinstance(value["profiles"], dict)
                or set(value["profiles"]) != VOICE_STYLES
            ):
                return base_profile_id
            profile_id = str(value["profiles"][_infer_voice_style(text)])
            self._require_profile(profile_id)
            return profile_id
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return base_profile_id

    def _profile_root(self, profile_id: str) -> Path:
        try:
            normalized = str(UUID(profile_id))
        except ValueError as error:
            raise VoiceProfileError("voice profile ID is invalid") from error
        return self._profiles_root / normalized

    def _read_profile(self, metadata_path: Path) -> VoiceProfile:
        profile_root = metadata_path.parent
        if (
            profile_root.is_symlink()
            or metadata_path.is_symlink()
            or not metadata_path.is_file()
        ):
            raise VoiceProfileError("voice profile metadata is unavailable")
        try:
            value = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise VoiceProfileError("voice profile metadata is invalid")
            profile = VoiceProfile(
                profile_id=str(value["profile_id"]),
                name=str(value["name"]),
                is_default=bool(value["is_default"]),
                created_at=str(value["created_at"]),
                sha256=str(value["sha256"]),
                size_bytes=int(value["size_bytes"]),
                duration_ms=int(value["duration_ms"]),
                sample_rate_hz=int(value["sample_rate_hz"]),
                channels=int(value["channels"]),
                style=str(value.get("style", "neutral")),
                reference_text=(
                    str(value["reference_text"])
                    if value.get("reference_text") is not None
                    else None
                ),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise VoiceProfileError("voice profile metadata is invalid") from error
        expected_root = self._profile_root(profile.profile_id)
        if (
            profile.is_default
            or profile_root.resolve(strict=True)
            != expected_root.resolve(strict=True)
            or not profile_root.resolve(strict=True).is_relative_to(
                self._profiles_root.resolve(strict=True)
            )
            or not _PROFILE_NAME.fullmatch(profile.name)
            or not re.fullmatch(r"[a-f0-9]{64}", profile.sha256 or "")
            or profile.style not in VOICE_STYLES
        ):
            raise VoiceProfileError("voice profile metadata is invalid")
        _normalize_reference_text(profile.reference_text)
        return profile

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, object]) -> None:
        encoded = (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        _atomic_bytes(path, encoded)


def _validate_reference_wav(wav_bytes: bytes) -> tuple[int, int, int]:
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            frames = audio.getnframes()
            compression = audio.getcomptype()
    except (EOFError, wave.Error) as error:
        raise VoiceProfileError("reference audio must be a valid WAV file") from error
    if (
        channels not in {1, 2}
        or sample_width != 2
        or sample_rate not in {16_000, 22_050, 24_000, 44_100, 48_000}
        or compression != "NONE"
        or frames <= 0
    ):
        raise VoiceProfileError(
            "reference WAV must be 16-bit PCM mono/stereo at a supported rate"
        )
    duration = frames / sample_rate
    if not MIN_REFERENCE_SECONDS <= duration <= MAX_REFERENCE_SECONDS:
        raise VoiceProfileError("reference WAV duration must be 3 to 30 seconds")
    return sample_rate, channels, round(duration * 1000)


def _normalize_reference_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if (
        not 1 <= len(normalized) <= MAX_REFERENCE_TEXT_CHARS
        or not _REFERENCE_TEXT.fullmatch(normalized)
    ):
        raise VoiceProfileError("reference transcript is invalid")
    return normalized


def _infer_voice_style(text: str) -> str:
    normalized = text.casefold()
    dark_markers = (
        "오류",
        "실패",
        "위험",
        "문제",
        "죄송",
        "불가능",
        "중단",
        "복구",
    )
    happy_markers = (
        "완료",
        "성공",
        "좋아요",
        "좋습니다",
        "축하",
        "기뻐",
        "반가",
    )
    if any(marker in normalized for marker in dark_markers):
        return "dark"
    if "!" in text or any(marker in normalized for marker in happy_markers):
        return "happy"
    return "neutral"


def _atomic_bytes(path: Path, value: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
