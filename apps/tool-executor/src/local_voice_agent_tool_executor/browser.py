"""Isolated loopback-only Playwright browser owned by one worker thread."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
from io import BytesIO
import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any, Mapping
from urllib.parse import urlparse
from uuid import UUID, uuid4

from .errors import BrowserAutomationError, ToolArgumentsInvalid, ToolNotSupported


BROWSER_READ_TOOLS = frozenset(
    {
        "browser_console_logs",
        "browser_download_status",
        "browser_get_page_state",
        "browser_network_errors",
        "browser_screenshot",
    }
)
BROWSER_MUTATION_TOOLS = frozenset(
    {
        "browser_click",
        "browser_close",
        "browser_launch",
        "browser_navigate",
        "browser_scroll",
        "browser_select",
        "browser_type",
    }
)
BROWSER_TOOLS = BROWSER_READ_TOOLS | BROWSER_MUTATION_TOOLS
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
MAX_STATE_SOURCE_CHARS = 2 * 1024 * 1024
MAX_EVENTS = 1_000
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class BrowserSession:
    browser: Any
    context: Any
    page: Any
    console: list[dict[str, object]] = field(default_factory=list)
    network_errors: list[dict[str, object]] = field(default_factory=list)
    downloads: dict[str, dict[str, object]] = field(default_factory=dict)
    fingerprint: str | None = None
    elements: dict[str, str] = field(default_factory=dict)


class BrowserAutomation:
    """Serialize Playwright calls and keep all browser objects thread-affine."""

    def __init__(self, *, artifact_root: Path) -> None:
        if not artifact_root.is_absolute():
            raise ValueError("browser artifact root must be absolute")
        artifact_root.mkdir(parents=True, exist_ok=True)
        self._artifact_root = artifact_root
        self._pool = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="lva-browser",
        )
        self._submit_lock = Lock()
        self._playwright: Any | None = None
        self._sessions: dict[UUID, BrowserSession] = {}

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, object]:
        if tool_name not in BROWSER_TOOLS:
            raise ToolNotSupported(tool_name)
        with self._submit_lock:
            future = self._pool.submit(
                self._execute_on_worker,
                tool_name,
                dict(arguments),
            )
        return future.result(timeout=65)

    def close_all(self) -> None:
        with self._submit_lock:
            self._pool.submit(self._close_on_worker).result(timeout=30)
            self._pool.shutdown(wait=True, cancel_futures=True)

    def _execute_on_worker(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, object]:
        arguments.pop("idempotency_key", None)
        handler = getattr(self, f"_{tool_name}")
        return handler(**arguments)

    def _ensure_playwright(self) -> Any:
        if self._playwright is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
        return self._playwright

    def _browser_launch(
        self,
        *,
        browser_profile_id: str,
        headless: bool,
    ) -> dict[str, object]:
        if browser_profile_id != "local-loopback":
            raise ToolArgumentsInvalid("browser profile is not registered")
        playwright = self._ensure_playwright()
        try:
            browser = playwright.chromium.launch(headless=headless)
        except Exception as error:
            LOGGER.error(
                "browser launch failed: %s: %s",
                type(error).__name__,
                str(error).replace("\r", " ").replace("\n", " ")[:2048],
            )
            raise BrowserAutomationError("isolated browser launch failed") from error
        context = browser.new_context(
            accept_downloads=False,
            service_workers="block",
        )
        context.route("**/*", self._route_request)
        context.route_web_socket("**/*", self._route_websocket)
        page = context.new_page()
        session_id = uuid4()
        session = BrowserSession(browser=browser, context=context, page=page)
        page.on(
            "console",
            lambda message: self._append_event(
                session.console,
                {
                    "level": message.type,
                    "text": message.text[:4096],
                },
            ),
        )
        page.on(
            "requestfailed",
            lambda request: self._append_event(
                session.network_errors,
                {
                    "kind": "request_failed",
                    "url": _redacted_url(request.url),
                    "error": (
                        str(request.failure or "request failed")[:1024]
                    ),
                },
            ),
        )
        page.on(
            "response",
            lambda response: (
                self._append_event(
                    session.network_errors,
                    {
                        "kind": "http_error",
                        "url": _redacted_url(response.url),
                        "status": response.status,
                    },
                )
                if response.status >= 400
                else None
            ),
        )
        page.on("download", lambda download: self._record_download(session, download))
        self._sessions[session_id] = session
        return {
            "browser_session_id": str(session_id),
            "browser_profile_id": browser_profile_id,
            "headless": headless,
            "network_policy": "loopback_only",
        }

    def _browser_navigate(
        self,
        *,
        browser_session_id: str,
        url: str,
        wait_until: str = "domcontentloaded",
    ) -> dict[str, object]:
        session = self._session(browser_session_id)
        if not is_allowed_browser_url(url):
            raise ToolArgumentsInvalid("browser navigation is not loopback-only")
        response = session.page.goto(
            url,
            wait_until=wait_until,
            timeout=60_000,
        )
        if not is_allowed_browser_url(session.page.url):
            raise ToolArgumentsInvalid("browser redirect escaped the loopback boundary")
        session.fingerprint = None
        session.elements.clear()
        return {
            "url": session.page.url,
            "title": session.page.title()[:2048],
            "status": response.status if response is not None else None,
        }

    def _browser_get_page_state(
        self,
        *,
        browser_session_id: str,
        include_dom: bool = False,
        include_accessibility_tree: bool = True,
        max_bytes: int = 262_144,
    ) -> dict[str, object]:
        session = self._session(browser_session_id)
        fingerprint = self._current_fingerprint(session)
        raw_elements = session.page.locator(
            "a,button,input,textarea,select,[role],[contenteditable='true']"
        ).evaluate_all(
            """nodes => nodes.slice(0, 500).map((node, index) => ({
                index,
                tag: node.tagName.toLowerCase(),
                type: (node.getAttribute('type') || '').toLowerCase(),
                role: node.getAttribute('role') || '',
                name: (node.getAttribute('aria-label')
                    || node.getAttribute('title')
                    || node.innerText
                    || node.getAttribute('placeholder')
                    || '').trim().slice(0, 512),
                visible: !!(node.offsetWidth || node.offsetHeight
                    || node.getClientRects().length),
                disabled: !!node.disabled,
                editable: ['input','textarea','select'].includes(
                    node.tagName.toLowerCase())
                    || node.getAttribute('contenteditable') === 'true'
            }))"""
        )
        session.elements.clear()
        elements: list[dict[str, object]] = []
        for record in raw_elements:
            element_ref = f"element:{uuid4()}"
            session.elements[element_ref] = (
                "a,button,input,textarea,select,[role],"
                "[contenteditable='true']"
                f" >> nth={record['index']}"
            )
            elements.append({"element_ref": element_ref, **record})
        session.fingerprint = fingerprint
        accessibility_tree = None
        if include_accessibility_tree:
            accessibility_tree = session.page.locator("body").aria_snapshot(
                timeout=5_000
            )
            accessibility_tree = _truncate_utf8(accessibility_tree, max_bytes)
        dom = None
        if include_dom:
            dom = session.page.locator("body").evaluate(
                "node => node.outerHTML"
            )
            dom = _truncate_utf8(dom, max_bytes)
        return {
            "url": session.page.url,
            "title": session.page.title()[:2048],
            "page_state_fingerprint": fingerprint,
            "accessibility_tree": accessibility_tree,
            "dom": dom,
            "elements": elements,
            "element_count_truncated": len(raw_elements) >= 500,
        }

    def _browser_click(
        self,
        *,
        browser_session_id: str,
        element_ref: str,
        page_state_fingerprint: str,
        external_submission: bool,
    ) -> dict[str, object]:
        if external_submission:
            raise ToolArgumentsInvalid("external submission is unavailable")
        session, locator = self._fresh_element(
            browser_session_id,
            element_ref,
            page_state_fingerprint,
        )
        properties = locator.evaluate(
            """node => ({
                tag: node.tagName.toLowerCase(),
                type: (node.getAttribute('type') || '').toLowerCase(),
                href: node.href || '',
                formAction: node.getAttribute('formaction') || ''
            })"""
        )
        if properties["type"] == "submit" or properties["formAction"]:
            raise ToolArgumentsInvalid("submit-capable browser element is blocked")
        if properties["href"] and not is_allowed_browser_url(properties["href"]):
            raise ToolArgumentsInvalid("external browser link is blocked")
        locator.click(timeout=30_000)
        session.fingerprint = None
        return {"clicked": True, "url": session.page.url}

    def _browser_type(
        self,
        *,
        browser_session_id: str,
        element_ref: str,
        page_state_fingerprint: str,
        text: str,
        submit: bool,
    ) -> dict[str, object]:
        if submit:
            raise ToolArgumentsInvalid("submit typing is unavailable")
        session, locator = self._fresh_element(
            browser_session_id,
            element_ref,
            page_state_fingerprint,
        )
        if not locator.is_editable():
            raise ToolArgumentsInvalid("browser element is not editable")
        locator.fill(text, timeout=30_000)
        session.fingerprint = None
        return {"typed_characters": len(text), "submitted": False}

    def _browser_select(
        self,
        *,
        browser_session_id: str,
        element_ref: str,
        page_state_fingerprint: str,
        option_value: str,
    ) -> dict[str, object]:
        session, locator = self._fresh_element(
            browser_session_id,
            element_ref,
            page_state_fingerprint,
        )
        if locator.evaluate("node => node.tagName.toLowerCase()") != "select":
            raise ToolArgumentsInvalid("browser element is not a select")
        values = locator.select_option(value=option_value, timeout=30_000)
        session.fingerprint = None
        return {"selected_values": values}

    def _browser_scroll(
        self,
        *,
        browser_session_id: str,
        delta_y: int,
        delta_x: int = 0,
    ) -> dict[str, object]:
        session = self._session(browser_session_id)
        session.page.mouse.wheel(delta_x, delta_y)
        return {
            "scroll_x": session.page.evaluate("window.scrollX"),
            "scroll_y": session.page.evaluate("window.scrollY"),
        }

    def _browser_screenshot(
        self,
        *,
        browser_session_id: str,
        full_page: bool = False,
    ) -> dict[str, object]:
        session = self._session(browser_session_id)
        content = session.page.screenshot(
            full_page=full_page,
            type="png",
            timeout=30_000,
        )
        artifact_id = uuid4()
        path = self._artifact_root / f"{artifact_id}.png"
        with path.open("xb") as handle:
            handle.write(content)
        from PIL import Image

        with Image.open(BytesIO(content)) as image:
            width, height = image.size
        return {
            "artifact_id": str(artifact_id),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "width": width,
            "height": height,
            "full_page": full_page,
        }

    def _browser_console_logs(
        self,
        *,
        browser_session_id: str,
        minimum_level: str = "warning",
        limit: int = 100,
    ) -> dict[str, object]:
        session = self._session(browser_session_id)
        levels = {"debug": 0, "info": 1, "log": 1, "warning": 2, "error": 3}
        minimum = levels[minimum_level]
        events = [
            event
            for event in session.console
            if levels.get(str(event["level"]), 1) >= minimum
        ][-limit:]
        return {"events": events, "count": len(events)}

    def _browser_network_errors(
        self,
        *,
        browser_session_id: str,
        limit: int = 100,
    ) -> dict[str, object]:
        session = self._session(browser_session_id)
        events = session.network_errors[-limit:]
        return {"events": events, "count": len(events)}

    def _browser_download_status(
        self,
        *,
        browser_session_id: str,
        download_id: str,
    ) -> dict[str, object]:
        session = self._session(browser_session_id)
        try:
            UUID(download_id)
            return dict(session.downloads[download_id])
        except (ValueError, KeyError) as error:
            raise ToolArgumentsInvalid("browser download is unknown") from error

    def _browser_close(
        self,
        *,
        browser_session_id: str,
    ) -> dict[str, object]:
        session_id = _canonical_uuid(browser_session_id)
        try:
            session = self._sessions.pop(session_id)
        except KeyError as error:
            raise ToolArgumentsInvalid("browser session is unknown") from error
        session.context.close()
        session.browser.close()
        return {"browser_session_id": browser_session_id, "closed": True}

    def _session(self, value: str) -> BrowserSession:
        session_id = _canonical_uuid(value)
        try:
            return self._sessions[session_id]
        except KeyError as error:
            raise ToolArgumentsInvalid("browser session is unknown") from error

    def _fresh_element(
        self,
        browser_session_id: str,
        element_ref: str,
        fingerprint: str,
    ) -> tuple[BrowserSession, Any]:
        session = self._session(browser_session_id)
        if (
            session.fingerprint != fingerprint
            or self._current_fingerprint(session) != fingerprint
        ):
            raise ToolArgumentsInvalid("browser page state is stale")
        try:
            selector = session.elements[element_ref]
        except KeyError as error:
            raise ToolArgumentsInvalid("browser element reference is stale") from error
        locator = session.page.locator(selector)
        if locator.count() != 1 or not locator.is_visible():
            raise ToolArgumentsInvalid("browser element is unavailable")
        return session, locator

    @staticmethod
    def _current_fingerprint(session: BrowserSession) -> str:
        snapshot = session.page.evaluate(
            """limit => ({
                url: location.href,
                title: document.title,
                length: document.documentElement.outerHTML.length,
                source: document.documentElement.outerHTML.slice(0, limit)
            })""",
            MAX_STATE_SOURCE_CHARS,
        )
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _route_request(route: Any, request: Any) -> None:
        parsed = urlparse(request.url)
        if parsed.scheme in {"data", "blob", "about"} or is_allowed_browser_url(
            request.url
        ):
            route.continue_()
        else:
            route.abort("blockedbyclient")

    @staticmethod
    def _route_websocket(websocket: Any) -> None:
        if is_allowed_websocket_url(websocket.url):
            websocket.connect_to_server()
        else:
            websocket.close(code=1008, reason="loopback-only policy")

    @staticmethod
    def _append_event(
        target: list[dict[str, object]],
        event: dict[str, object],
    ) -> None:
        target.append(event)
        if len(target) > MAX_EVENTS:
            del target[: len(target) - MAX_EVENTS]

    @staticmethod
    def _record_download(session: BrowserSession, download: Any) -> None:
        download_id = str(uuid4())
        download.cancel()
        session.downloads[download_id] = {
            "download_id": download_id,
            "suggested_filename": download.suggested_filename[:512],
            "status": "blocked",
            "saved": False,
        }

    def _close_on_worker(self) -> None:
        for session in list(self._sessions.values()):
            session.context.close()
            session.browser.close()
        self._sessions.clear()
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


def is_allowed_browser_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in LOOPBACK_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.port is not None
        and not parsed.fragment
    )


def is_allowed_websocket_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in {"ws", "wss"}
        and parsed.hostname in LOOPBACK_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.port is not None
        and not parsed.fragment
    )


def _canonical_uuid(value: str) -> UUID:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ToolArgumentsInvalid("identifier is not a UUID") from error
    if str(parsed) != value:
        raise ToolArgumentsInvalid("identifier is not canonical")
    return parsed


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _redacted_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{host}{port}{parsed.path[:2048]}"
