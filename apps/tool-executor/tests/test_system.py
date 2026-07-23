from __future__ import annotations

import os
from pathlib import Path
import socket

import pytest

from local_voice_agent_tool_executor.system import (
    SYSTEM_TOOLS,
    WindowsSystemInspector,
    _numeric_or_text,
    _redact_command_line,
)


def test_system_tool_catalog_is_closed() -> None:
    assert SYSTEM_TOOLS == {
        "check_port",
        "inspect_cpu",
        "inspect_disk",
        "inspect_gpu",
        "inspect_memory",
        "inspect_network",
        "inspect_process",
        "inspect_service",
        "list_processes",
        "list_services",
    }


def test_command_line_redaction_masks_common_secret_forms() -> None:
    redacted = _redact_command_line(
        "agent --token secret-value --password='hidden' "
        "https://user:pass@example.test/"
    )
    assert redacted is not None
    assert "secret-value" not in redacted
    assert "hidden" not in redacted
    assert "pass@" not in redacted
    assert redacted.count("<redacted>") == 3


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("42", 42),
        ("3.5", 3.5),
        ("N/A", None),
        ("RTX 5090", "RTX 5090"),
    ],
)
def test_numeric_normalization(value: str, expected: object) -> None:
    assert _numeric_or_text(value) == expected


@pytest.mark.skipif(os.name != "nt", reason="Windows-native integration")
def test_live_windows_system_observation() -> None:
    inspector = WindowsSystemInspector()
    cpu = inspector.execute("inspect_cpu", {})
    memory = inspector.execute("inspect_memory", {})
    gpu = inspector.execute("inspect_gpu", {"include_processes": False})
    disks = inspector.execute("inspect_disk", {"volume": "C:"})
    processes = inspector.execute(
        "list_processes",
        {"name_contains": "python", "include_command_line": True, "limit": 10},
    )
    services = inspector.execute(
        "list_services",
        {"state": "running", "limit": 10},
    )
    assert cpu["processors"]
    assert memory["total_bytes"] > memory["available_bytes"] > 0
    assert gpu["gpus"]
    assert disks["volumes"][0]["DeviceID"].casefold() == "c:"
    assert len(processes["processes"]) <= 10
    assert len(services["services"]) <= 10


@pytest.mark.skipif(os.name != "nt", reason="Windows-native integration")
def test_live_loopback_port_probe() -> None:
    inspector = WindowsSystemInspector()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert inspector.execute(
            "check_port",
            {"host": "127.0.0.1", "port": port},
        )["listening"]
