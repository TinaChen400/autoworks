from __future__ import annotations

import ctypes
import time
from ctypes import wintypes


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_BACK = 0x08


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


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


def mouse_down() -> None:
    user32 = _user32()
    event = INPUT(
        type=INPUT_MOUSE,
        union=INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None)),
    )
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
    if sent != 1:
        error = ctypes.get_last_error()
        raise MouseKeyboardError(
            f"SendInput mouse_down failed with Windows error {error}; sent {sent} events."
        )


def mouse_up() -> None:
    user32 = _user32()
    event = INPUT(
        type=INPUT_MOUSE,
        union=INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None)),
    )
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
    if sent != 1:
        error = ctypes.get_last_error()
        raise MouseKeyboardError(
            f"SendInput mouse_up failed with Windows error {error}; sent {sent} events."
        )


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


def scroll_wheel(delta: int) -> None:
    user32 = _user32()
    mouse_data = ctypes.c_ulong(int(delta) & 0xFFFFFFFF).value
    event = INPUT(
        type=INPUT_MOUSE,
        union=INPUT_UNION(mi=MOUSEINPUT(0, 0, mouse_data, MOUSEEVENTF_WHEEL, 0, None)),
    )
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
    if sent != 1:
        error = ctypes.get_last_error()
        raise MouseKeyboardError(
            f"SendInput scroll failed with Windows error {error}; sent {sent} events."
        )


def _send_unicode_char(char: str) -> None:
    user32 = _user32()
    codepoint = ord(char)
    if codepoint > 0xFFFF:
        raise MouseKeyboardError("Only BMP Unicode characters are supported by SendInput.")
    inputs = (INPUT * 2)(
        INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(
                ki=KEYBDINPUT(0, codepoint, KEYEVENTF_UNICODE, 0, None)
            ),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(
                ki=KEYBDINPUT(0, codepoint, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)
            ),
        ),
    )
    sent = user32.SendInput(len(inputs), ctypes.byref(inputs), ctypes.sizeof(INPUT))
    if sent != len(inputs):
        error = ctypes.get_last_error()
        raise MouseKeyboardError(f"SendInput text failed with Windows error {error}; sent {sent} events.")


def type_text(text: str, pause_ms: int = 0) -> None:
    for char in str(text):
        _send_unicode_char(char)
        if pause_ms > 0:
            time.sleep(pause_ms / 1000.0)


def press_backspace() -> None:
    user32 = _user32()
    inputs = (INPUT * 2)(
        INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(VK_BACK, 0, 0, 0, None)),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(VK_BACK, 0, KEYEVENTF_KEYUP, 0, None)),
        ),
    )
    sent = user32.SendInput(len(inputs), ctypes.byref(inputs), ctypes.sizeof(INPUT))
    if sent != len(inputs):
        error = ctypes.get_last_error()
        raise MouseKeyboardError(
            f"SendInput backspace failed with Windows error {error}; sent {sent} events."
        )
