from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from local_voice_agent_tool_executor import windows_ui
from local_voice_agent_tool_executor.errors import ToolArgumentsInvalid
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


@pytest.mark.skipif(os.name != "nt", reason="Microsoft UI Automation")
def test_coordinate_action_rejects_screen_geometry_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = WindowsUiAutomation(artifact_root=tmp_path)
    try:
        captured = ui.execute(
            "ui_capture_screen",
            {"include_cursor": False},
        )
        monkeypatch.setattr(
            windows_ui,
            "_virtual_screen_geometry",
            lambda: (
                int(captured["origin_x"]),
                int(captured["origin_y"]),
                int(captured["width"]) + 1,
                int(captured["height"]),
            ),
        )
        with pytest.raises(ToolArgumentsInvalid, match="geometry changed"):
            ui.execute(
                "ui_click_coordinate",
                {
                    "screenshot_evidence_id": captured["artifact_id"],
                    "screenshot_sha256": captured["sha256"],
                    "screen_width": captured["width"],
                    "screen_height": captured["height"],
                    "x": 0,
                    "y": 0,
                    "approval_id": str(uuid4()),
                    "idempotency_key": str(uuid4()),
                },
            )
    finally:
        ui.close()
