"""Independent validation of the executor's supported tool contracts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from .browser import BROWSER_MUTATION_TOOLS, BROWSER_READ_TOOLS
from .development import DEVELOPMENT_TOOLS
from .windows_ui import UI_MUTATION_TOOLS, UI_READ_TOOLS
from .system import SYSTEM_TOOLS
from .digests import sha256_json
from .errors import ToolArgumentsInvalid, ToolContractError, ToolNotSupported


FILESYSTEM_READ_TOOLS = frozenset(
    {
        "calculate_hash",
        "list_files",
        "list_recent_files",
        "read_file",
        "read_file_range",
        "search_files",
    }
)
GIT_READ_TOOLS = frozenset(
    {
        "git_blame",
        "git_branch",
        "git_diff",
        "git_diff_stat",
        "git_log",
        "git_show",
        "git_status",
    }
)
FILESYSTEM_MUTATION_TOOLS = frozenset(
    {
        "apply_patch",
        "rollback_file_change",
        "write_file",
    }
)
SUPPORTED_READ_TOOLS = (
    FILESYSTEM_READ_TOOLS
    | GIT_READ_TOOLS
    | BROWSER_READ_TOOLS
    | UI_READ_TOOLS
    | SYSTEM_TOOLS
    | (DEVELOPMENT_TOOLS - {"run_tests"})
)
SUPPORTED_TOOLS = (
    SUPPORTED_READ_TOOLS
    | FILESYSTEM_MUTATION_TOOLS
    | BROWSER_MUTATION_TOOLS
    | UI_MUTATION_TOOLS
    | (DEVELOPMENT_TOOLS & {"run_tests"})
)
LEVEL_2_TOOLS = frozenset(
    {
        "ui_click_coordinate",
        "ui_drag_coordinate",
    }
)


@dataclass(frozen=True, slots=True)
class ReadToolContract:
    name: str
    risk_level: int
    idempotency: str
    timeout_seconds: int
    definition_sha256: str
    validator: Draft202012Validator


class ReadToolContracts:
    def __init__(self, contracts: Mapping[str, ReadToolContract]) -> None:
        if frozenset(contracts) != SUPPORTED_TOOLS:
            raise ToolContractError("supported tool contract set is incomplete")
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

        for name in sorted(SUPPORTED_TOOLS):
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
            expected_risk = (
                0
                if name in SUPPORTED_READ_TOOLS
                else 2
                if name in LEVEL_2_TOOLS
                else 1
            )
            expected_idempotency = (
                "read_only" if name in SUPPORTED_READ_TOOLS else "required"
            )
            if (
                raw["risk_level"] != expected_risk
                or raw["idempotency"] != expected_idempotency
            ):
                raise ToolContractError(f"{name}: unsafe risk/idempotency contract")
            contracts[name] = ReadToolContract(
                name=name,
                risk_level=expected_risk,
                idempotency=expected_idempotency,
                timeout_seconds=raw["timeout_seconds"],
                definition_sha256=sha256_json(raw),
                validator=Draft202012Validator(
                    raw["parameters"],
                    format_checker=FormatChecker(),
                ),
            )
        return cls(contracts)

    def validate(self, name: str, arguments: Mapping[str, Any]) -> str:
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
        return sha256_json(dict(arguments))

    def timeout_seconds(self, name: str) -> int:
        try:
            return self._contracts[name].timeout_seconds
        except KeyError as error:
            raise ToolNotSupported(name) from error

    def definition_sha256(self, name: str) -> str:
        try:
            return self._contracts[name].definition_sha256
        except KeyError as error:
            raise ToolNotSupported(name) from error

    def risk_level(self, name: str) -> int:
        try:
            return self._contracts[name].risk_level
        except KeyError as error:
            raise ToolNotSupported(name) from error

    def idempotency(self, name: str) -> str:
        try:
            return self._contracts[name].idempotency
        except KeyError as error:
            raise ToolNotSupported(name) from error


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolContractError(f"{path}: cannot read JSON") from error
    if not isinstance(value, dict):
        raise ToolContractError(f"{path}: expected a JSON object")
    return value
