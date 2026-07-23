"""Independent validation of the executor's supported tool contracts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from .errors import ToolArgumentsInvalid, ToolContractError, ToolNotSupported


SUPPORTED_READ_TOOLS = frozenset(
    {
        "calculate_hash",
        "list_files",
        "list_recent_files",
        "read_file",
        "read_file_range",
        "search_files",
    }
)


@dataclass(frozen=True, slots=True)
class ReadToolContract:
    name: str
    timeout_seconds: int
    validator: Draft202012Validator


class ReadToolContracts:
    def __init__(self, contracts: Mapping[str, ReadToolContract]) -> None:
        if frozenset(contracts) != SUPPORTED_READ_TOOLS:
            raise ToolContractError("supported read-tool contract set is incomplete")
        self._contracts = MappingProxyType(dict(contracts))

    @classmethod
    def load(
        cls,
        *,
        definitions_dir: Path,
        definition_schema_path: Path,
    ) -> "ReadToolContracts":
        meta_schema = _read_object(definition_schema_path)
        try:
            Draft202012Validator.check_schema(meta_schema)
        except SchemaError as error:
            raise ToolContractError("tool definition schema is invalid") from error
        meta_validator = Draft202012Validator(
            meta_schema,
            format_checker=FormatChecker(),
        )
        contracts: dict[str, ReadToolContract] = {}

        for name in sorted(SUPPORTED_READ_TOOLS):
            path = definitions_dir / f"{name}.json"
            raw = _read_object(path)
            try:
                meta_validator.validate(raw)
                Draft202012Validator.check_schema(raw["parameters"])
            except (ValidationError, SchemaError) as error:
                raise ToolContractError(
                    f"{path.name}: invalid definition: {error.message}"
                ) from error
            if raw["name"] != name:
                raise ToolContractError(f"{path.name}: tool name mismatch")
            if raw["risk_level"] != 0 or raw["idempotency"] != "read_only":
                raise ToolContractError(
                    f"{name}: executor accepts only Level 0 read-only contracts"
                )
            contracts[name] = ReadToolContract(
                name=name,
                timeout_seconds=raw["timeout_seconds"],
                validator=Draft202012Validator(
                    raw["parameters"],
                    format_checker=FormatChecker(),
                ),
            )
        return cls(contracts)

    def validate(self, name: str, arguments: Mapping[str, Any]) -> None:
        try:
            contract = self._contracts[name]
        except KeyError as error:
            raise ToolNotSupported(name) from error
        errors = sorted(
            contract.validator.iter_errors(dict(arguments)),
            key=lambda item: list(item.absolute_path),
        )
        if errors:
            locations = [
                ".".join(str(part) for part in error.absolute_path) or "$"
                for error in errors[:5]
            ]
            raise ToolArgumentsInvalid(
                f"{name}: invalid arguments at {', '.join(locations)}"
            )


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolContractError(f"{path}: cannot read JSON") from error
    if not isinstance(value, dict):
        raise ToolContractError(f"{path}: expected a JSON object")
    return value
