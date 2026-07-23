"""Immutable JSON-Schema-backed tool registry adapter."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from ..domain.digests import sha256_json
from ..domain.policy import RiskLevel


SERVER_MANAGED_ARGUMENTS = frozenset({"approval_id", "idempotency_key"})


class ToolRegistryError(ValueError):
    code = "TOOL_REGISTRY_ERROR"


class ToolNotFound(ToolRegistryError):
    code = "TOOL_NOT_FOUND"


class ToolDisabled(ToolRegistryError):
    code = "TOOL_DISABLED"


class ToolArgumentsInvalid(ToolRegistryError):
    code = "SCHEMA_INVALID"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    risk_level: RiskLevel
    parameters: Mapping[str, Any]
    timeout_seconds: int
    idempotency: str
    sha256: str
    enabled: bool

    def model_parameters(self) -> dict[str, Any]:
        parameters = _thaw_json(self.parameters)
        properties = parameters.get("properties", {})
        parameters["properties"] = {
            key: value
            for key, value in properties.items()
            if key not in SERVER_MANAGED_ARGUMENTS
        }
        if "required" in parameters:
            parameters["required"] = [
                key
                for key in parameters["required"]
                if key not in SERVER_MANAGED_ARGUMENTS
            ]
        Draft202012Validator.check_schema(parameters)
        return parameters

    def as_function_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.model_parameters(),
            },
        }


class ToolRegistry:
    def __init__(self, definitions: Mapping[str, ToolDefinition]) -> None:
        self._definitions = MappingProxyType(dict(definitions))

    @classmethod
    def load(
        cls,
        *,
        definitions_dir: Path,
        definition_schema_path: Path,
        disabled_tools: Iterable[str] = (),
    ) -> "ToolRegistry":
        meta_schema = _read_object(definition_schema_path)
        Draft202012Validator.check_schema(meta_schema)
        meta_validator = Draft202012Validator(
            meta_schema,
            format_checker=FormatChecker(),
        )
        disabled = frozenset(disabled_tools)
        definitions: dict[str, ToolDefinition] = {}

        for path in sorted(definitions_dir.glob("*.json")):
            raw = _read_object(path)
            try:
                meta_validator.validate(raw)
                Draft202012Validator.check_schema(raw["parameters"])
            except (ValidationError, SchemaError) as error:
                raise ToolRegistryError(
                    f"{path.name}: invalid tool definition: {error.message}"
                ) from error

            name = raw["name"]
            if path.stem != name:
                raise ToolRegistryError(
                    f"{path.name}: filename must match tool name {name!r}"
                )
            if name in definitions:
                raise ToolRegistryError(f"duplicate tool name: {name}")

            definitions[name] = ToolDefinition(
                name=name,
                description=raw["description"],
                risk_level=RiskLevel(raw["risk_level"]),
                parameters=_freeze_json(raw["parameters"]),
                timeout_seconds=raw["timeout_seconds"],
                idempotency=raw["idempotency"],
                sha256=sha256_json(raw),
                enabled=name not in disabled,
            )

        if not definitions:
            raise ToolRegistryError("tool registry is empty")
        unknown_disabled = disabled.difference(definitions)
        if unknown_disabled:
            raise ToolRegistryError(
                f"disabled tool names are unknown: {sorted(unknown_disabled)!r}"
            )
        return cls(definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    def get(self, name: str, *, require_enabled: bool = False) -> ToolDefinition:
        try:
            definition = self._definitions[name]
        except KeyError as error:
            raise ToolNotFound(name) from error
        if require_enabled and not definition.enabled:
            raise ToolDisabled(name)
        return definition

    def validate_arguments(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        require_enabled: bool = True,
    ) -> str:
        definition = self.get(name, require_enabled=require_enabled)
        validator = Draft202012Validator(
            definition.parameters,
            format_checker=FormatChecker(),
        )
        errors = sorted(validator.iter_errors(dict(arguments)), key=lambda item: list(item.path))
        if errors:
            paths = [
                ".".join(str(part) for part in error.absolute_path) or "$"
                for error in errors[:5]
            ]
            raise ToolArgumentsInvalid(
                f"{name}: invalid arguments at {', '.join(paths)}"
            )
        return sha256_json(dict(arguments))

    def validate_model_arguments(
        self,
        name: str,
        arguments: Mapping[str, Any],
    ) -> str:
        definition = self.get(name, require_enabled=True)
        validator = Draft202012Validator(
            definition.model_parameters(),
            format_checker=FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(dict(arguments)),
            key=lambda item: list(item.path),
        )
        if errors:
            paths = [
                ".".join(str(part) for part in error.absolute_path) or "$"
                for error in errors[:5]
            ]
            raise ToolArgumentsInvalid(
                f"{name}: invalid model arguments at {', '.join(paths)}"
            )
        return sha256_json(dict(arguments))

    def as_function_tools(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            definition.as_function_tool()
            for definition in self._definitions.values()
            if definition.enabled
        )


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolRegistryError(f"{path}: cannot read JSON: {error}") from error
    if not isinstance(value, dict):
        raise ToolRegistryError(f"{path}: expected a JSON object")
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
