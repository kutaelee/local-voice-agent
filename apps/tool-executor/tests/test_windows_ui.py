from __future__ import annotations

import os
from pathlib import Path

import pytest

from local_voice_agent_tool_executor.windows_ui import WindowsUiAutomation


@pytest.mark.skipif(os.name != "nt", reason="Microsoft UI Automation")
def test_windows_ui_observation_and_capture_are_bounded(tmp_path: Path) -> None:
    ui = WindowsUiAutomation(artifact_root=tmp_path)
    try:
        result = ui.execute(
            "ui_list_windows",
            {"limit": 10},
        )
        assert 0 < result["count"] <= 10
        assert all(
            len(item["window_state_fingerprint"]) == 64
            for item in result["windows"]
        )
        captured = ui.execute(
            "ui_capture_screen",
            {"include_cursor": False},
        )
        assert captured["scope"] == "virtual_desktop"
        assert captured["size_bytes"] > 1_000
        assert captured["width"] > 0
        assert captured["height"] > 0
        assert len(list(tmp_path.glob("*.png"))) == 1
    finally:
        ui.close()
