from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "launch-sglang-secure.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("launch_sglang_secure", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_api_key_removes_secret_from_environment() -> None:
    module = load_script()
    environment = {
        "LVA_SGLANG_API_KEY": "a" * 32,
        "SAFE_VALUE": "retained",
    }

    assert module.read_api_key(["--model-path", "/model"], environment) == "a" * 32
    assert "LVA_SGLANG_API_KEY" not in environment
    assert environment["SAFE_VALUE"] == "retained"


@pytest.mark.parametrize(
    "argument",
    [
        "--api-key",
        "--api-key=secret",
        "--admin-api-key",
        "--admin-api-key=secret",
        "--ssl-keyfile-password",
        "--ssl-keyfile-password=secret",
    ],
)
def test_read_api_key_rejects_secrets_in_argv(argument: str) -> None:
    module = load_script()
    environment = {"LVA_SGLANG_API_KEY": "a" * 32}

    with pytest.raises(ValueError, match="forbidden on the command line"):
        module.read_api_key([argument], environment)


def test_redacted_repr_masks_all_sensitive_fields() -> None:
    module = load_script()

    class Example:
        def __init__(self) -> None:
            self.api_key = "api-secret"
            self.admin_api_key = "admin-secret"
            self.ssl_keyfile_password = "tls-secret"

        def __repr__(self) -> str:
            return (
                "Example(api_key='api-secret', admin_api_key='admin-secret', "
                "ssl_keyfile_password='tls-secret')"
            )

    module.install_redacted_repr(Example)
    rendered = repr(Example())

    assert "api-secret" not in rendered
    assert "admin-secret" not in rendered
    assert "tls-secret" not in rendered
    assert rendered.count("<redacted>") == 3
