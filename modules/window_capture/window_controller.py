from __future__ import annotations

import ctypes
from dataclasses import dataclass

import win32con
import win32gui
import win32process

from modules.window_capture.capture import AnchorFrame, AnchorProfile, resolve_anchor_frame


@dataclass(frozen=True)
class WindowPlacement:
    left: int
    top: int
    width: int
    height: int


def _set_process_dpi_aware() -> None:
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        return


def anchor_to_placement(anchor: AnchorProfile | AnchorFrame) -> WindowPlacement:
    frame = resolve_anchor_frame(anchor)
    return WindowPlacement(
        left=frame["x"],
        top=frame["y"],
        width=frame["width"],
        height=frame["height"],
    )


def is_valid_window(hwnd: int) -> bool:
    return bool(hwnd and win32gui.IsWindow(hwnd))


def get_window_process_id(hwnd: int) -> int:
    _, process_id = win32process.GetWindowThreadProcessId(hwnd)
    return process_id


def get_window_placement(hwnd: int) -> WindowPlacement:
    _set_process_dpi_aware()
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return WindowPlacement(left=left, top=top, width=right - left, height=bottom - top)


def placement_to_anchor_origin(
    placement: WindowPlacement,
    anchor: AnchorProfile,
) -> AnchorProfile:
    return {
        "x": placement.left,
        "y": placement.top,
        "base_width": anchor["base_width"],
        "base_height": anchor["base_height"],
        "scale": anchor["scale"],
    }


def move_resize_window(hwnd: int, placement: WindowPlacement) -> None:
    _set_process_dpi_aware()
    if not is_valid_window(hwnd):
        raise ValueError(f"Invalid hwnd: {hwnd}")

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    win32gui.MoveWindow(
        hwnd,
        placement.left,
        placement.top,
        placement.width,
        placement.height,
        True,
    )


def snap_to_anchor(hwnd: int, anchor: AnchorProfile | AnchorFrame) -> WindowPlacement:
    placement = anchor_to_placement(anchor)
    move_resize_window(hwnd, placement)
    return placement


def restore_if_moved_or_resized(hwnd: int, target: WindowPlacement) -> bool:
    """Restore the selected hwnd if its outer window rect changed."""
    if not is_valid_window(hwnd):
        return False

    current = get_window_placement(hwnd)
    if current == target:
        return False

    move_resize_window(hwnd, target)
    return True
