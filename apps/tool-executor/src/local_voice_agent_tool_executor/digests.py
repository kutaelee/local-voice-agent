"""Canonical JSON hashing shared by executor binding and evidence."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()
