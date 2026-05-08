from __future__ import annotations

import ctypes
import time
from ctypes import wintypes


INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


class MouseKeyboardError(RuntimeError):
    """Raised when the Windows mouse API reports a failure."""


def _user32() -> ctypes.WinDLL:
    try:
        return ctypes.WinDLL("user32", use_last_error=True)
    except AttributeError as exc:
        raise MouseKeyboardError("Windows user32 API is unavailable.") from exc


def _set_process_dpi_aware(user32: ctypes.WinDLL) -> None:
    # Best effort only; cursor verification below catches coordinate mismatches.
    try:
        user32.SetProcessDPIAware()
    except AttributeError:
        return


def get_cursor_position() -> dict[str, int]:
    user32 = _user32()
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        error = ctypes.get_last_error()
        raise MouseKeyboardError(f"GetCursorPos failed with Windows error {error}.")
    return {"x": int(point.x), "y": int(point.y)}


def move_to(x: int, y: int) -> None:
    user32 = _user32()
    _set_process_dpi_aware(user32)
    if not user32.SetCursorPos(int(x), int(y)):
        error = ctypes.get_last_error()
        raise MouseKeyboardError(f"SetCursorPos failed with Windows error {error}.")


def left_click() -> None:
    user32 = _user32()
    inputs = (INPUT * 2)(
        INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None)),
        ),
        INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None)),
        ),
    )
    sent = user32.SendInput(len(inputs), ctypes.byref(inputs), ctypes.sizeof(INPUT))
    if sent != len(inputs):
        error = ctypes.get_last_error()
        raise MouseKeyboardError(f"SendInput failed with Windows error {error}; sent {sent} events.")


def click_screen_point(x: int, y: int, pause_ms: int = 120) -> dict[str, int]:
    move_to(x, y)
    if pause_ms > 0:
        time.sleep(pause_ms / 1000.0)
    actual_position = get_cursor_position()
    if actual_position != {"x": int(x), "y": int(y)}:
        raise MouseKeyboardError(
            "Cursor landed at "
            f"({actual_position['x']}, {actual_position['y']}) instead of ({int(x)}, {int(y)})."
        )
    left_click()
    return actual_position
