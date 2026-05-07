from __future__ import annotations

import ctypes
import time


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class MouseKeyboardError(RuntimeError):
    """Raised when the Windows mouse API reports a failure."""


def _user32() -> ctypes.WinDLL:
    try:
        return ctypes.WinDLL("user32", use_last_error=True)
    except AttributeError as exc:
        raise MouseKeyboardError("Windows user32 API is unavailable.") from exc


def move_to(x: int, y: int) -> None:
    user32 = _user32()
    if not user32.SetCursorPos(int(x), int(y)):
        error = ctypes.get_last_error()
        raise MouseKeyboardError(f"SetCursorPos failed with Windows error {error}.")


def left_click() -> None:
    user32 = _user32()
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def click_screen_point(x: int, y: int, pause_ms: int = 120) -> None:
    move_to(x, y)
    if pause_ms > 0:
        time.sleep(pause_ms / 1000.0)
    left_click()
