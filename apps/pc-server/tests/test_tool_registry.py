from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from local_voice_agent_server.domain.digests import sha256_json
from local_voice_agent_server.domain.policy import RiskLevel
from local_voice_agent_server.infrastructure.tool_registry import (
    ToolArgumentsInvalid,
    ToolDisabled,
    ToolNotFound,
    ToolRegistry,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = REPO_ROOT / "packages/tool-registry/definitions"
META_SCHEMA = REPO_ROOT / "packages/tool-registry/schemas/tool-definition.schema.json"


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    return ToolRegistry.load(
        definitions_dir=DEFINITIONS,
        definition_schema_path=META_SCHEMA,
        disabled_tools={"restricted_shell"},
    )


def test_all_tracked_definitions_load(registry: ToolRegistry) -> None:
    assert len(registry) == 75


def test_definition_exposes_stable_risk_and_digest(registry: ToolRegistry) -> None:
    definition = registry.get("read_file")
    assert definition.risk_level is RiskLevel.OBSERVE
    assert len(definition.sha256) == 64
    assert definition.sha256 == sha256_json(
        json.loads((DEFINITIONS / "read_file.json").read_text(encoding="utf-8"))
    )


def test_definition_is_deeply_immutable_and_export_is_json(
    registry: ToolRegistry,
) -> None:
    definition = registry.get("read_file")
    with pytest.raises(TypeError):
        definition.parameters["properties"]["workspace_id"]["type"] = "integer"
    json.dumps(definition.as_function_tool())


def test_valid_arguments_return_canonical_digest(registry: ToolRegistry) -> None:
    arguments = {"workspace_id": "repo", "relative_path": "README.md"}
    assert registry.validate_arguments("read_file", arguments) == sha256_json(
        arguments
    )


def test_missing_required_argument_is_rejected(registry: ToolRegistry) -> None:
    with pytest.raises(ToolArgumentsInvalid):
        registry.validate_arguments("read_file", {"workspace_id": "repo"})


def test_additional_argument_is_rejected(registry: ToolRegistry) -> None:
    with pytest.raises(ToolArgumentsInvalid):
        registry.validate_arguments(
            "read_file",
            {
                "workspace_id": "repo",
                "relative_path": "README.md",
                "command": "whoami",
            },
        )


def test_uuid_format_is_enforced(registry: ToolRegistry) -> None:
    with pytest.raises(ToolArgumentsInvalid):
        registry.validate_arguments(
            "delete_file",
            {
                "workspace_id": "repo",
                "relative_path": "old.txt",
                "expected_sha256": "a" * 64,
                "approval_id": "not-a-uuid",
                "idempotency_key": str(uuid4()),
            },
        )


def test_disabled_tool_cannot_be_selected_for_execution(
    registry: ToolRegistry,
) -> None:
    with pytest.raises(ToolDisabled):
        registry.validate_arguments(
            "restricted_shell",
            {},
            require_enabled=True,
        )


def test_disabled_tool_is_omitted_from_model_schema(
    registry: ToolRegistry,
) -> None:
    names = {
        item["function"]["name"] for item in registry.as_function_tools()
    }
    assert "restricted_shell" not in names
    assert len(names) == 74


def test_server_managed_fields_are_not_exposed_to_model(
    registry: ToolRegistry,
) -> None:
    for item in registry.as_function_tools():
        parameters = item["function"]["parameters"]
        properties = parameters.get("properties", {})
        required = parameters.get("required", [])
        assert "approval_id" not in properties
        assert "idempotency_key" not in properties
        assert "approval_id" not in required
        assert "idempotency_key" not in required


def test_model_and_execution_argument_validation_are_separate(
    registry: ToolRegistry,
) -> None:
    model_arguments = {
        "workspace_id": "repo",
        "relative_path": "notes.txt",
        "expected_sha256": None,
        "content": "draft",
    }
    registry.validate_model_arguments("write_file", model_arguments)
    with pytest.raises(ToolArgumentsInvalid):
        registry.validate_arguments("write_file", model_arguments)


def test_unknown_tool_fails_closed(registry: ToolRegistry) -> None:
    with pytest.raises(ToolNotFound):
        registry.get("invented_tool", require_enabled=True)
