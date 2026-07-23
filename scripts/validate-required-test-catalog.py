#!/usr/bin/env python3
"""Validate coverage and uniqueness of mandatory failure/security cases."""

from __future__ import annotations

import json
from pathlib import Path


REQUIRED_IDS = {
    "invalid_pairing_token",
    "path_traversal",
    "symlink_reparse_bypass",
    "outside_allowlist_file",
    "concurrent_file_modification",
    "hash_mismatch",
    "duplicate_tool_call",
    "tool_timeout",
    "stt_timeout",
    "llm_timeout",
    "tts_timeout",
    "gpu_oom",
    "mtp_initialization_failure",
    "model_31b_load_failure",
    "wsl_failure",
    "websocket_disconnect",
    "android_reconnect",
    "barge_in_during_tts",
    "not_a_git_repository",
    "large_diff",
    "corrupted_log",
    "browser_element_changed",
    "screen_resolution_changed",
    "rollback_failure",
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "tests" / "required-cases.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    cases = catalog.get("cases")
    if not isinstance(cases, list):
        raise ValueError("cases must be an array")
    ids = [case.get("id") for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate required-case id")
    if set(ids) != REQUIRED_IDS:
        raise ValueError(
            f"required-case mismatch: "
            f"missing={sorted(REQUIRED_IDS - set(ids))}, "
            f"extra={sorted(set(ids) - REQUIRED_IDS)}"
        )
    for case in cases:
        if not case.get("layer") or not case.get("expected"):
            raise ValueError(f"incomplete required case: {case.get('id')}")
    print(
        json.dumps(
            {
                "required_cases": len(cases),
                "status": "required_test_catalog_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
