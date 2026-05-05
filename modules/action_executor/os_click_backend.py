from __future__ import annotations

import time


class OsClickBackend:
    """Small Windows mouse backend used only after real-click guards pass."""

    def click(self, x: int, y: int) -> None:
        import win32api
        import win32con

        win32api.SetCursorPos((x, y))
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
        time.sleep(0.02)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)
