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
REQUIRED_TOOL_NAMES = {
    "list_files",
    "search_files",
    "read_file",
    "read_file_range",
    "write_file",
    "apply_patch",
    "copy_file",
    "move_file",
    "create_directory",
    "calculate_hash",
    "list_recent_files",
    "archive_files",
    "extract_archive",
    "delete_file",
    "delete_directory",
    "git_status",
    "git_diff",
    "git_diff_stat",
    "git_log",
    "git_branch",
    "git_show",
    "git_blame",
    "git_create_branch",
    "git_apply_patch",
    "git_commit",
    "git_push",
    "git_merge",
    "git_rebase",
    "git_reset",
    "git_clean",
    "run_tests",
    "run_test_file",
    "run_linter",
    "run_formatter",
    "run_build",
    "start_dev_server",
    "stop_dev_server",
    "inspect_build_log",
    "inspect_test_log",
    "check_port",
    "inspect_cpu",
    "inspect_memory",
    "inspect_gpu",
    "inspect_disk",
    "inspect_network",
    "list_processes",
    "inspect_process",
    "start_registered_process",
    "stop_registered_process",
    "list_services",
    "inspect_service",
    "browser_launch",
    "browser_navigate",
    "browser_get_page_state",
    "browser_click",
    "browser_type",
    "browser_select",
    "browser_scroll",
    "browser_screenshot",
    "browser_console_logs",
    "browser_network_errors",
    "browser_download_status",
    "browser_close",
    "ui_list_windows",
    "ui_focus_window",
    "ui_get_accessibility_tree",
    "ui_click_element",
    "ui_type_text",
    "ui_press_key",
    "ui_capture_screen",
    "ui_click_coordinate",
    "ui_drag_coordinate",
    "restricted_shell",
}


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
        required = parameters.get("required", [])
        properties = parameters.get("properties", {})
        if risk >= 1:
            if "idempotency_key" not in required:
                raise ValueError(f"{path}: mutating tool requires idempotency_key")
            if properties.get("idempotency_key") != {
                "type": "string",
                "format": "uuid",
            }:
                raise ValueError(f"{path}: invalid idempotency_key schema")
        if risk >= 2:
            if "approval_id" not in required:
                raise ValueError(f"{path}: Level 2+ tool requires approval_id")
            if properties.get("approval_id") != {
                "type": "string",
                "format": "uuid",
            }:
                raise ValueError(f"{path}: invalid approval_id schema")
    missing = sorted(REQUIRED_TOOL_NAMES - names)
    if missing:
        raise ValueError(f"required tool definitions missing: {missing}")
    return len(paths)


def main() -> int:
    event_count = validate_event_catalog()
    tool_count = validate_tool_definitions()
    print(
        json.dumps(
            {
                "events": event_count,
                "tools": tool_count,
                "required_tools": len(REQUIRED_TOOL_NAMES),
                "status": "contract_catalog_consistency_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
