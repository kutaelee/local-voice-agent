#!/usr/bin/env python3
"""Validate coding-agent status schemas and representative contracts."""

from __future__ import annotations

import json
from pathlib import Path

from referencing import Registry, Resource
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "packages" / "status-adapters" / "schemas"


def load(name: str) -> dict:
    value = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name}: expected object")
    Draft202012Validator.check_schema(value)
    return value


def main() -> int:
    input_schema = load("agent-status-input.schema.json")
    normalized_schema = load("normalized-agent-status.schema.json")
    registry = Registry().with_resource(
        input_schema["$id"],
        Resource.from_contents(input_schema),
    )

    status = {
        "agent": "codex",
        "project": "local-voice-agent",
        "task": "Validate runtime compatibility",
        "phase": "testing",
        "progress_summary": "MTP target download is active.",
        "current_action": "Validating local contracts.",
        "changed_files": ["scripts/validate-status-contracts.py"],
        "tests": {"status": "running", "summary": "Runtime smoke pending."},
        "blockers": [],
        "updated_at": "2026-07-23T18:00:00+09:00"
    }
    Draft202012Validator(input_schema).validate(status)

    observed = {"classification": "observed", "source": "status_json"}
    inferred = {
        "classification": "inferred",
        "source": "git_adapter",
        "explanation": "Phase inferred from active test process."
    }
    normalized = {
        "schema_version": "1.0",
        "adapter_id": "codex-status-json",
        "status": status,
        "provenance": {
            "agent": observed,
            "project": observed,
            "task": observed,
            "phase": inferred,
            "progress_summary": observed,
            "current_action": observed,
            "changed_files": observed,
            "tests": {"status": observed, "summary": observed},
            "blockers": observed,
            "updated_at": observed
        },
        "observed_at": "2026-07-23T18:00:01+09:00"
    }
    validator = Draft202012Validator(normalized_schema, registry=registry)
    validator.validate(normalized)

    invalid = json.loads(json.dumps(normalized))
    invalid["provenance"]["phase"].pop("explanation")
    try:
        validator.validate(invalid)
    except ValidationError:
        pass
    else:
        raise ValueError("inferred field without explanation was accepted")

    forbidden_progress = dict(status)
    forbidden_progress["progress_percent"] = 50
    try:
        Draft202012Validator(input_schema).validate(forbidden_progress)
    except ValidationError:
        pass
    else:
        raise ValueError("invented progress_percent field was accepted")

    print(
        json.dumps(
            {
                "schemas": 2,
                "inferred_explanation_gate": "passed",
                "progress_percent_rejection": "passed",
                "status": "status_contract_validation_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
