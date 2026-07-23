#!/usr/bin/env python3
"""Run dependency-free consistency checks for protocol and tool contracts."""

from __future__ import annotations

import json
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = REPO_ROOT / "packages" / "protocol"
TOOL_ROOT = REPO_ROOT / "packages" / "tool-registry"
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def validate_event_catalog() -> int:
    envelope = load_json(
        PROTOCOL_ROOT / "schemas" / "websocket-message.schema.json"
    )
    catalog = load_json(PROTOCOL_ROOT / "event-catalog.json")
    schema_types = envelope["properties"]["type"]["enum"]
    catalog_types = [event["type"] for event in catalog["events"]]
    if len(catalog_types) != len(set(catalog_types)):
        raise ValueError("event catalog contains duplicate types")
    if set(schema_types) != set(catalog_types):
        missing = sorted(set(schema_types) - set(catalog_types))
        extra = sorted(set(catalog_types) - set(schema_types))
        raise ValueError(f"event catalog mismatch: missing={missing}, extra={extra}")
    directions = {"android_to_pc", "pc_to_android", "bidirectional"}
    for event in catalog["events"]:
        if event["direction"] not in directions:
            raise ValueError(f"invalid direction for {event['type']}")
        if not isinstance(event["replayable"], bool):
            raise ValueError(f"invalid replayable flag for {event['type']}")

    payloads = load_json(
        PROTOCOL_ROOT / "schemas" / "event-payloads.schema.json"
    )
    payload_types = {
        name for name in payloads["$defs"] if not name.startswith("_")
    }
    if set(catalog_types) != payload_types:
        missing = sorted(set(catalog_types) - payload_types)
        extra = sorted(payload_types - set(catalog_types))
        raise ValueError(
            f"payload schema mismatch: missing={missing}, extra={extra}"
        )
    return len(catalog_types)


def validate_tool_definitions() -> int:
    names: set[str] = set()
    paths = sorted((TOOL_ROOT / "definitions").glob("*.json"))
    if not paths:
        raise ValueError("no tool definitions found")
    for path in paths:
        definition = load_json(path)
        expected = {
            "schema_version",
            "name",
            "description",
            "risk_level",
            "parameters",
            "timeout_seconds",
            "idempotency",
        }
        if set(definition) != expected:
            raise ValueError(f"{path}: unexpected top-level fields")
        name = definition["name"]
        if not isinstance(name, str) or not TOOL_NAME.fullmatch(name):
            raise ValueError(f"{path}: invalid tool name")
        if path.stem != name or name in names:
            raise ValueError(f"{path}: filename/name mismatch or duplicate")
        names.add(name)
        risk = definition["risk_level"]
        if not isinstance(risk, int) or risk not in range(4):
            raise ValueError(f"{path}: invalid risk level")
        timeout = definition["timeout_seconds"]
        if not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            raise ValueError(f"{path}: invalid timeout")
        idempotency = definition["idempotency"]
        if idempotency not in {"read_only", "required", "not_applicable"}:
            raise ValueError(f"{path}: invalid idempotency policy")
        if risk == 0 and idempotency != "read_only":
            raise ValueError(f"{path}: Level 0 tool must be read-only")
        if risk >= 1 and idempotency == "read_only":
            raise ValueError(f"{path}: mutating tool cannot be read-only")
        parameters = definition["parameters"]
        if (
            not isinstance(parameters, dict)
            or parameters.get("type") != "object"
            or parameters.get("additionalProperties") is not False
        ):
            raise ValueError(f"{path}: parameter object must be closed")
    return len(paths)


def main() -> int:
    event_count = validate_event_catalog()
    tool_count = validate_tool_definitions()
    print(
        json.dumps(
            {
                "events": event_count,
                "tools": tool_count,
                "status": "contract_catalog_consistency_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
