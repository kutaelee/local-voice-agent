from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest

from local_voice_agent_tool_executor.browser import (
    BrowserAutomation,
    is_allowed_browser_url,
    is_allowed_websocket_url,
)
from local_voice_agent_tool_executor.errors import ToolArgumentsInvalid


def test_browser_url_policy_is_explicit_loopback_only() -> None:
    assert is_allowed_browser_url("http://127.0.0.1:46321/app")
    assert is_allowed_browser_url("https://localhost:9443/app")
    assert not is_allowed_browser_url("https://example.com/app")
    assert not is_allowed_browser_url("http://localhost/app")
    assert not is_allowed_browser_url("http://user@127.0.0.1:46321/app")
    assert not is_allowed_browser_url("http://127.0.0.1:46321/app#fragment")
    assert is_allowed_websocket_url("ws://127.0.0.1:46321/socket")
    assert not is_allowed_websocket_url("wss://example.com/socket")


@pytest.mark.skipif(os.name != "nt", reason="Windows Playwright runtime")
def test_browser_loopback_state_actions_and_evidence(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            content = b"""<!doctype html><html><head><title>Local smoke</title>
            <script>console.warn('bounded warning')</script></head><body>
            <input aria-label="Name" value="">
            <select aria-label="Mode"><option value="safe">Safe</option></select>
            <button type="button"
              onclick="document.querySelector('h1').textContent='Clicked'">
              Update
            </button>
            <h1>Ready</h1></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    browser = BrowserAutomation(artifact_root=tmp_path)
    key = str(uuid4())
    try:
        launched = browser.execute(
            "browser_launch",
            {
                "browser_profile_id": "local-loopback",
                "headless": True,
                "idempotency_key": key,
            },
        )
        session_id = str(launched["browser_session_id"])
        browser.execute(
            "browser_navigate",
            {
                "browser_session_id": session_id,
                "url": f"http://127.0.0.1:{server.server_port}/",
                "idempotency_key": str(uuid4()),
            },
        )
        state = browser.execute(
            "browser_get_page_state",
            {
                "browser_session_id": session_id,
                "include_dom": True,
                "include_accessibility_tree": True,
                "max_bytes": 262_144,
            },
        )
        assert state["title"] == "Local smoke"
        elements = state["elements"]
        input_ref = next(
            item["element_ref"] for item in elements if item["tag"] == "input"
        )
        button_ref = next(
            item["element_ref"] for item in elements if item["tag"] == "button"
        )
        fingerprint = str(state["page_state_fingerprint"])
        typed = browser.execute(
            "browser_type",
            {
                "browser_session_id": session_id,
                "element_ref": input_ref,
                "page_state_fingerprint": fingerprint,
                "text": "local only",
                "submit": False,
                "idempotency_key": str(uuid4()),
            },
        )
        assert typed == {"typed_characters": 10, "submitted": False}
        with pytest.raises(ToolArgumentsInvalid):
            browser.execute(
                "browser_click",
                {
                    "browser_session_id": session_id,
                    "element_ref": button_ref,
                    "page_state_fingerprint": fingerprint,
                    "external_submission": False,
                    "idempotency_key": str(uuid4()),
                },
            )
        refreshed = browser.execute(
            "browser_get_page_state",
            {"browser_session_id": session_id},
        )
        button_ref = next(
            item["element_ref"]
            for item in refreshed["elements"]
            if item["tag"] == "button"
        )
        browser.execute(
            "browser_click",
            {
                "browser_session_id": session_id,
                "element_ref": button_ref,
                "page_state_fingerprint": refreshed[
                    "page_state_fingerprint"
                ],
                "external_submission": False,
                "idempotency_key": str(uuid4()),
            },
        )
        screenshot = browser.execute(
            "browser_screenshot",
            {"browser_session_id": session_id, "full_page": False},
        )
        assert screenshot["size_bytes"] > 1_000
        assert len(list(tmp_path.glob("*.png"))) == 1
        logs = browser.execute(
            "browser_console_logs",
            {
                "browser_session_id": session_id,
                "minimum_level": "warning",
                "limit": 10,
            },
        )
        assert logs["count"] == 1
        browser.execute(
            "browser_close",
            {
                "browser_session_id": session_id,
                "idempotency_key": str(uuid4()),
            },
        )
    finally:
        browser.close_all()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
