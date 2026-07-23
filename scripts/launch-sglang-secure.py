#!/usr/bin/env python3
"""Launch SGLang without exposing bearer tokens in argv or startup logs."""

from __future__ import annotations

import os
import sys
from typing import Any, MutableMapping, Sequence


API_KEY_ENV = "LVA_SGLANG_API_KEY"
FORBIDDEN_SECRET_OPTIONS = (
    "--api-key",
    "--admin-api-key",
    "--ssl-keyfile-password",
)
SENSITIVE_SERVER_FIELDS = (
    "api_key",
    "admin_api_key",
    "ssl_keyfile_password",
)


def read_api_key(
    argv: Sequence[str],
    environment: MutableMapping[str, str],
) -> str:
    """Validate the launch contract and remove the secret from the environment."""
    for argument in argv:
        for option in FORBIDDEN_SECRET_OPTIONS:
            if argument == option or argument.startswith(f"{option}="):
                raise ValueError(
                    f"{option} is forbidden on the command line; use {API_KEY_ENV}"
                )

    api_key = environment.pop(API_KEY_ENV, "")
    if len(api_key) < 32:
        raise ValueError(f"{API_KEY_ENV} must contain at least 32 characters")
    return api_key


def install_redacted_repr(server_args_type: type[Any]) -> None:
    """Redact secret-valued dataclass fields from SGLang's generated repr."""
    original_repr = server_args_type.__repr__

    def redacted_repr(instance: Any) -> str:
        rendered = original_repr(instance)
        for field_name in SENSITIVE_SERVER_FIELDS:
            value = getattr(instance, field_name, None)
            if value:
                rendered = rendered.replace(repr(value), "'<redacted>'")
        return rendered

    server_args_type.__repr__ = redacted_repr


def main(argv: Sequence[str] | None = None) -> int:
    launch_args = list(sys.argv[1:] if argv is None else argv)
    try:
        api_key = read_api_key(launch_args, os.environ)
    except ValueError as error:
        print(f"Secure SGLang launch rejected: {error}", file=sys.stderr)
        return 3

    from sglang.launch_server import run_server
    from sglang.srt.plugins import load_plugins
    from sglang.srt.server_args import ServerArgs, prepare_server_args
    from sglang.srt.utils import kill_process_tree

    install_redacted_repr(ServerArgs)
    load_plugins()
    server_args = prepare_server_args(launch_args)
    server_args.api_key = api_key

    try:
        run_server(server_args)
    finally:
        kill_process_tree(os.getpid(), include_parent=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
