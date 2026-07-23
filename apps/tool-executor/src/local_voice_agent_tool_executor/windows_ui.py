"""Bounded Microsoft UI Automation adapter with fresh-state action guards."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from threading import Lock
from typing import Any, Mapping
from uuid import UUID, uuid4

from .errors import ToolArgumentsInvalid, ToolNotSupported, UiAutomationError


UI_READ_TOOLS = frozenset(
    {
        "ui_capture_screen",
        "ui_get_accessibility_tree",
        "ui_list_windows",
    }
)
UI_MUTATION_TOOLS = frozenset(
    {
        "ui_click_element",
        "ui_focus_window",
        "ui_press_key",
        "ui_type_text",
    }
)
UI_TOOLS = UI_READ_TOOLS | UI_MUTATION_TOOLS
SAFE_ACTION_EXECUTABLES = frozenset({"notepad.exe"})
BLOCKED_ACTION_NAMES = re.compile(
    r"\b(send|submit|buy|purchase|pay|delete|remove|publish|upload)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class WindowObservation:
    wrapper: Any
    executable: str | None
    fingerprint: str
    tree_fingerprint: str | None = None
    tree_depth: int = 0
    tree_nodes: int = 0
    elements: dict[str, Any] = field(default_factory=dict)


class WindowsUiAutomation:
    def __init__(self, *, artifact_root: Path) -> None:
        if not artifact_root.is_absolute():
            raise ValueError("UI artifact root must be absolute")
        artifact_root.mkdir(parents=True, exist_ok=True)
        self._artifact_root = artifact_root
        self._pool = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="lva-windows-uia",
        )
        self._submit_lock = Lock()
        self._desktop: Any | None = None
        self._windows: dict[str, WindowObservation] = {}

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, object]:
        if tool_name not in UI_TOOLS:
            raise ToolNotSupported(tool_name)
        with self._submit_lock:
            future = self._pool.submit(
                self._execute_on_worker,
                tool_name,
                dict(arguments),
            )
        return future.result(timeout=35)

    def close(self) -> None:
        with self._submit_lock:
            self._pool.shutdown(wait=True, cancel_futures=True)

    def _execute_on_worker(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, object]:
        arguments.pop("idempotency_key", None)
        try:
            return getattr(self, f"_{tool_name}")(**arguments)
        except (ToolArgumentsInvalid, ToolNotSupported):
            raise
        except Exception as error:
            raise UiAutomationError("Windows UI Automation failed") from error

    def _ensure_desktop(self) -> Any:
        if self._desktop is None:
            from pywinauto import Desktop

            self._desktop = Desktop(backend="uia")
        return self._desktop

    def _ui_list_windows(
        self,
        *,
        process_id: int | None = None,
        title_contains: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        desktop = self._ensure_desktop()
        observations: list[dict[str, object]] = []
        self._windows.clear()
        title_filter = (title_contains or "").casefold()
        for wrapper in desktop.windows(visible_only=True):
            try:
                pid = int(wrapper.process_id())
                title = str(wrapper.window_text())[:2048]
                if process_id is not None and pid != process_id:
                    continue
                if title_filter and title_filter not in title.casefold():
                    continue
                executable = _process_executable(pid)
                fingerprint = _window_fingerprint(wrapper, pid, title)
                window_ref = f"window:{uuid4()}"
                self._windows[window_ref] = WindowObservation(
                    wrapper=wrapper,
                    executable=executable,
                    fingerprint=fingerprint,
                )
                rectangle = wrapper.rectangle()
                observations.append(
                    {
                        "window_ref": window_ref,
                        "window_state_fingerprint": fingerprint,
                        "process_id": pid,
                        "process_name": (
                            Path(executable).name if executable else None
                        ),
                        "title": title,
                        "control_type": wrapper.element_info.control_type,
                        "rectangle": _rectangle(rectangle),
                        "enabled": bool(wrapper.is_enabled()),
                    }
                )
                if len(observations) >= limit:
                    break
            except Exception:
                continue
        return {
            "windows": observations,
            "count": len(observations),
            "truncated": len(observations) >= limit,
        }

    def _ui_get_accessibility_tree(
        self,
        *,
        window_ref: str,
        max_depth: int = 8,
        max_nodes: int = 1_000,
    ) -> dict[str, object]:
        observation = self._window(window_ref)
        records, wrappers, truncated = _snapshot_tree(
            observation.wrapper,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
        elements: dict[str, Any] = {}
        output: list[dict[str, object]] = []
        for record, wrapper in zip(records, wrappers, strict=True):
            element_ref = f"element:{uuid4()}"
            elements[element_ref] = wrapper
            output.append({"element_ref": element_ref, **record})
        fingerprint = _digest(records)
        observation.tree_fingerprint = fingerprint
        observation.tree_depth = max_depth
        observation.tree_nodes = max_nodes
        observation.elements = elements
        return {
            "window_ref": window_ref,
            "ui_state_fingerprint": fingerprint,
            "nodes": output,
            "node_count": len(output),
            "truncated": truncated,
        }

    def _ui_focus_window(
        self,
        *,
        window_ref: str,
        window_state_fingerprint: str,
    ) -> dict[str, object]:
        observation = self._action_window(window_ref)
        current = _window_fingerprint(
            observation.wrapper,
            int(observation.wrapper.process_id()),
            str(observation.wrapper.window_text())[:2048],
        )
        if (
            observation.fingerprint != window_state_fingerprint
            or current != window_state_fingerprint
        ):
            raise ToolArgumentsInvalid("window observation is stale")
        observation.wrapper.set_focus()
        return {"window_ref": window_ref, "focused": True}

    def _ui_click_element(
        self,
        *,
        window_ref: str,
        element_ref: str,
        ui_state_fingerprint: str,
        external_side_effect: bool,
    ) -> dict[str, object]:
        if external_side_effect:
            raise ToolArgumentsInvalid("external UI side effects are unavailable")
        _, element = self._fresh_element(
            window_ref,
            element_ref,
            ui_state_fingerprint,
        )
        name = str(element.window_text())[:512]
        if BLOCKED_ACTION_NAMES.search(name):
            raise ToolArgumentsInvalid("potentially external UI action is blocked")
        try:
            element.invoke()
        except Exception:
            element.click_input()
        return {"element_ref": element_ref, "clicked": True}

    def _ui_type_text(
        self,
        *,
        window_ref: str,
        element_ref: str,
        ui_state_fingerprint: str,
        text: str,
        submit: bool,
    ) -> dict[str, object]:
        if submit:
            raise ToolArgumentsInvalid("UI submit typing is unavailable")
        _, element = self._fresh_element(
            window_ref,
            element_ref,
            ui_state_fingerprint,
        )
        control_type = str(element.element_info.control_type)
        if control_type not in {"Edit", "Document"}:
            raise ToolArgumentsInvalid("UI element is not a text editor")
        element.set_focus()
        try:
            element.set_edit_text(text)
        except Exception:
            element.type_keys(text, with_spaces=True, set_foreground=False)
        return {"typed_characters": len(text), "submitted": False}

    def _ui_press_key(
        self,
        *,
        window_ref: str,
        ui_state_fingerprint: str,
        key: str,
        modifiers: list[str],
    ) -> dict[str, object]:
        observation = self._action_window(window_ref)
        if observation.tree_fingerprint != ui_state_fingerprint:
            raise ToolArgumentsInvalid("UI state fingerprint is stale")
        self._verify_tree_fresh(observation, ui_state_fingerprint)
        mapping = {
            "ARROW_UP": "{UP}",
            "ARROW_DOWN": "{DOWN}",
            "ARROW_LEFT": "{LEFT}",
            "ARROW_RIGHT": "{RIGHT}",
            "ESCAPE": "{ESC}",
            "TAB": "{TAB}",
            "HOME": "{HOME}",
            "END": "{END}",
            "PAGE_UP": "{PGUP}",
            "PAGE_DOWN": "{PGDN}",
        }
        prefixes = {"ALT": "%", "CTRL": "^", "SHIFT": "+"}
        chord = "".join(prefixes[value] for value in modifiers) + mapping[key]
        observation.wrapper.set_focus()
        observation.wrapper.type_keys(chord, set_foreground=False)
        return {"key": key, "modifiers": modifiers, "sent": True}

    def _ui_capture_screen(
        self,
        *,
        window_ref: str | None = None,
        include_cursor: bool = False,
    ) -> dict[str, object]:
        from PIL import Image, ImageGrab

        if include_cursor:
            raise ToolArgumentsInvalid("cursor capture is not implemented")
        if window_ref is None:
            image = ImageGrab.grab(all_screens=True)
            scope = "virtual_desktop"
        else:
            image = self._window(window_ref).wrapper.capture_as_image()
            scope = "window"
        stream = BytesIO()
        image.save(stream, format="PNG")
        content = stream.getvalue()
        artifact_id = uuid4()
        path = self._artifact_root / f"{artifact_id}.png"
        with path.open("xb") as handle:
            handle.write(content)
        with Image.open(BytesIO(content)) as parsed:
            width, height = parsed.size
        return {
            "artifact_id": str(artifact_id),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "width": width,
            "height": height,
            "scope": scope,
            "cursor_included": False,
        }

    def _window(self, window_ref: str) -> WindowObservation:
        if not window_ref.startswith("window:"):
            raise ToolArgumentsInvalid("window reference is invalid")
        try:
            UUID(window_ref.removeprefix("window:"))
            return self._windows[window_ref]
        except (ValueError, KeyError) as error:
            raise ToolArgumentsInvalid("window reference is stale") from error

    def _action_window(self, window_ref: str) -> WindowObservation:
        observation = self._window(window_ref)
        executable = (
            Path(observation.executable).name.casefold()
            if observation.executable
            else ""
        )
        if executable not in SAFE_ACTION_EXECUTABLES:
            raise ToolArgumentsInvalid(
                "window process is not registered for UI actions"
            )
        return observation

    def _fresh_element(
        self,
        window_ref: str,
        element_ref: str,
        fingerprint: str,
    ) -> tuple[WindowObservation, Any]:
        observation = self._action_window(window_ref)
        if observation.tree_fingerprint != fingerprint:
            raise ToolArgumentsInvalid("UI state fingerprint is stale")
        self._verify_tree_fresh(observation, fingerprint)
        try:
            return observation, observation.elements[element_ref]
        except KeyError as error:
            raise ToolArgumentsInvalid("UI element reference is stale") from error

    @staticmethod
    def _verify_tree_fresh(
        observation: WindowObservation,
        fingerprint: str,
    ) -> None:
        records, _, _ = _snapshot_tree(
            observation.wrapper,
            max_depth=observation.tree_depth,
            max_nodes=observation.tree_nodes,
        )
        if _digest(records) != fingerprint:
            raise ToolArgumentsInvalid("UI tree changed after observation")


def _snapshot_tree(
    root: Any,
    *,
    max_depth: int,
    max_nodes: int,
) -> tuple[list[dict[str, object]], list[Any], bool]:
    records: list[dict[str, object]] = []
    wrappers: list[Any] = []
    pending: list[tuple[Any, int, int | None]] = [(root, 0, None)]
    truncated = False
    while pending and len(records) < max_nodes:
        wrapper, depth, parent_index = pending.pop()
        try:
            rectangle = wrapper.rectangle()
            record = {
                "index": len(records),
                "parent_index": parent_index,
                "depth": depth,
                "name": str(wrapper.window_text())[:512],
                "control_type": str(wrapper.element_info.control_type)[:128],
                "automation_id": str(
                    wrapper.element_info.automation_id or ""
                )[:512],
                "enabled": bool(wrapper.is_enabled()),
                "visible": bool(wrapper.is_visible()),
                "rectangle": _rectangle(rectangle),
            }
            records.append(record)
            wrappers.append(wrapper)
            current_index = len(records) - 1
            if depth < max_depth:
                children = list(wrapper.children())
                for child in reversed(children[:500]):
                    pending.append((child, depth + 1, current_index))
                if len(children) > 500:
                    truncated = True
        except Exception:
            continue
    if pending:
        truncated = True
    return records, wrappers, truncated


def _window_fingerprint(wrapper: Any, pid: int, title: str) -> str:
    return _digest(
        {
            "process_id": pid,
            "title": title,
            "handle": int(wrapper.handle),
            "rectangle": _rectangle(wrapper.rectangle()),
        }
    )


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rectangle(rectangle: Any) -> dict[str, int]:
    return {
        "left": int(rectangle.left),
        "top": int(rectangle.top),
        "right": int(rectangle.right),
        "bottom": int(rectangle.bottom),
        "width": int(rectangle.width()),
        "height": int(rectangle.height()),
    }


def _process_executable(process_id: int) -> str | None:
    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        process_id,
    )
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        success = kernel32.QueryFullProcessImageNameW(
            handle,
            0,
            buffer,
            ctypes.byref(size),
        )
        return buffer.value if success else None
    finally:
        kernel32.CloseHandle(handle)
