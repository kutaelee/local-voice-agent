#!/usr/bin/env python3
"""Validate fail-closed network, retention, and pairing defaults."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(relative_path: str) -> dict:
    value = json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def load_yaml(relative_path: str) -> dict:
    value = yaml.safe_load((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{relative_path}: expected mapping")
    return value


def must_reject(
    validator: Draft202012Validator,
    value: dict,
    name: str,
) -> None:
    try:
        validator.validate(value)
    except ValidationError:
        return
    raise ValueError(f"{name} was accepted")


def main() -> int:
    app_validator = Draft202012Validator(
        load_json("configs/schemas/application.schema.json")
    )
    pairing_validator = Draft202012Validator(
        load_json("configs/schemas/android-pairing.schema.json")
    )
    app = load_yaml("configs/application.yaml")
    pairing = load_yaml("configs/android-pairing.yaml")
    app_validator.validate(app)
    pairing_validator.validate(pairing)

    public_bind = deepcopy(app)
    public_bind["server"]["host"] = "0.0.0.0"
    must_reject(app_validator, public_bind, "public bind")

    audio_retention = deepcopy(app)
    audio_retention["retention"]["raw_audio"] = True
    must_reject(app_validator, audio_retention, "raw audio retention")

    cleartext = deepcopy(pairing)
    cleartext["allow_cleartext"] = True
    cleartext["server_url"] = "ws://127.0.0.1:8765"
    must_reject(pairing_validator, cleartext, "cleartext pairing")

    plaintext_token = deepcopy(pairing)
    plaintext_token["token_storage"] = "shared_preferences"
    must_reject(pairing_validator, plaintext_token, "plaintext token storage")

    print(
        json.dumps(
            {
                "schemas": 2,
                "public_bind_rejection": "passed",
                "raw_audio_retention_rejection": "passed",
                "cleartext_pairing_rejection": "passed",
                "plaintext_token_storage_rejection": "passed",
                "status": "security_config_validation_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
