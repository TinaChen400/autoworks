from __future__ import annotations

import os
from dataclasses import dataclass

import pywintypes
import win32gui
import win32process

from modules.window_capture.window_controller import WindowPlacement, get_window_placement


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    process_id: int
    box: WindowPlacement


def _is_visible_top_level_window(hwnd: int) -> bool:
    if not win32gui.IsWindowVisible(hwnd):
        return False

    title = win32gui.GetWindowText(hwnd).strip()
    if not title:
        return False

    if win32gui.IsIconic(hwnd):
        return False

    return True


def list_visible_windows(
    *,
    exclude_foreground: bool = False,
    exclude_process_ids: set[int] | None = None,
) -> list[WindowInfo]:
    """Return visible top-level windows as explicit hwnd/title pairs."""
    foreground_hwnd = win32gui.GetForegroundWindow() if exclude_foreground else None
    excluded_pids = exclude_process_ids or {os.getpid()}
    windows: list[WindowInfo] = []

    def collect(hwnd: int, _: object) -> bool:
        if exclude_foreground and hwnd == foreground_hwnd:
            return True
        if _is_visible_top_level_window(hwnd):
            try:
                _, process_id = win32process.GetWindowThreadProcessId(hwnd)
                if process_id in excluded_pids:
                    return True
                windows.append(
                    WindowInfo(
                        hwnd=hwnd,
                        title=win32gui.GetWindowText(hwnd).strip(),
                        class_name=win32gui.GetClassName(hwnd),
                        process_id=process_id,
                        box=get_window_placement(hwnd),
                    )
                )
            except pywintypes.error:
                return True
        return True

    win32gui.EnumWindows(collect, None)
    windows.sort(key=lambda item: item.title.casefold())
    return windows
