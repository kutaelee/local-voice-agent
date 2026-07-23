#!/usr/bin/env python3
"""Validate approval/policy schemas and fail-closed invariants."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]


def load(relative_path: str) -> dict:
    value = json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def must_reject(validator: Draft202012Validator, value: dict, name: str) -> None:
    try:
        validator.validate(value)
    except ValidationError:
        return
    raise ValueError(f"{name} was accepted")


def main() -> int:
    request_validator = Draft202012Validator(
        load("packages/approval-engine/schemas/approval-request.schema.json")
    )
    response_validator = Draft202012Validator(
        load("packages/approval-engine/schemas/approval-response.schema.json")
    )
    policy_validator = Draft202012Validator(
        load("packages/policy-engine/schemas/policy-decision.schema.json")
    )

    arguments = {
        "workspace_id": "local-voice-agent",
        "relative_path": "README.md",
    }
    digest = canonical_digest(arguments)
    request = {
        "schema_version": "1.0",
        "approval_id": "11111111-1111-4111-8111-111111111111",
        "session_id": "22222222-2222-4222-8222-222222222222",
        "request_id": "33333333-3333-4333-8333-333333333333",
        "tool_call_id": "44444444-4444-4444-8444-444444444444",
        "tool_name": "write_file",
        "risk_level": 1,
        "workspace_id": "local-voice-agent",
        "normalized_arguments": arguments,
        "normalized_arguments_sha256": digest,
        "precondition_version": 7,
        "target": "README.md",
        "expected_changes": ["Replace reviewed UTF-8 content."],
        "impact_scope": "One allowlisted workspace file.",
        "rollback": {"possible": True, "steps": ["Restore captured backup."]},
        "ordered_steps": ["Check hash.", "Write file.", "Verify hash."],
        "state": "PENDING",
        "created_at": "2026-07-23T18:00:00+09:00",
        "expires_at": "2026-07-23T18:02:00+09:00",
    }
    request_validator.validate(request)
    if not datetime.fromisoformat(request["created_at"]) < datetime.fromisoformat(
        request["expires_at"]
    ):
        raise ValueError("approval expiry must follow creation")
    if canonical_digest(request["normalized_arguments"]) != digest:
        raise ValueError("approval argument digest mismatch")

    response_validator.validate(
        {
            "schema_version": "1.0",
            "approval_id": request["approval_id"],
            "decision": "APPROVED",
            "normalized_arguments_sha256": digest,
            "precondition_version": request["precondition_version"],
            "responded_at": "2026-07-23T18:01:00+09:00",
        }
    )

    level_2_allow = {
        "schema_version": "1.0",
        "decision": "ALLOW",
        "risk_level": 2,
        "tool_name": "delete_file",
        "tool_definition_sha256": "a" * 64,
        "normalized_arguments_sha256": "b" * 64,
        "reason_codes": ["WITHIN_SCOPE"],
        "evaluated_at": "2026-07-23T18:01:00+09:00",
    }
    must_reject(policy_validator, level_2_allow, "Level 2 ALLOW")
    level_3_approval = dict(level_2_allow)
    level_3_approval["risk_level"] = 3
    level_3_approval["decision"] = "REQUIRE_APPROVAL"
    must_reject(policy_validator, level_3_approval, "Level 3 approval")

    print(
        json.dumps(
            {
                "schemas": 3,
                "argument_digest_binding": "passed",
                "level_2_allow_rejection": "passed",
                "level_3_default_deny": "passed",
                "status": "approval_contract_validation_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
