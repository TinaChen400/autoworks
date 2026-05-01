from __future__ import annotations

import tkinter as tk

import win32con
import win32gui

from modules.window_capture.capture import AnchorFrame, AnchorProfile, resolve_anchor_frame


BLUE = "#1e88ff"
GREEN = "#22b14c"
BORDER_WIDTH = 6


class AnchorOverlay:
    """Always-on-top AnchorFrame border made from four thin windows.

    A single transparent layered window can render as an opaque black rectangle
    on some remote/VM display stacks. Four solid border bars avoid that failure
    mode and leave the target content unobscured.
    """

    def __init__(
        self,
        parent: tk.Tk,
        anchor: AnchorProfile | AnchorFrame,
        *,
        locked: bool = False,
    ) -> None:
        self.parent = parent
        self.parts = [self._create_part() for _ in range(4)]
        self.update(anchor, locked=locked)

    def _create_part(self) -> tk.Toplevel:
        window = tk.Toplevel(self.parent)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.configure(bg=BLUE)
        window.withdraw()
        self._make_passive(window)
        return window

    def _make_passive(self, window: tk.Toplevel) -> None:
        window.update_idletasks()
        hwnd = window.winfo_id()
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        style |= win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TRANSPARENT
        if hasattr(win32con, "WS_EX_NOACTIVATE"):
            style |= win32con.WS_EX_NOACTIVATE
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)

    def update(self, anchor: AnchorProfile | AnchorFrame, *, locked: bool) -> None:
        frame = resolve_anchor_frame(anchor)
        width = max(BORDER_WIDTH * 2, int(frame["width"]))
        height = max(BORDER_WIDTH * 2, int(frame["height"]))
        x = int(frame["x"])
        y = int(frame["y"])
        color = GREEN if locked else BLUE

        top, right, bottom, left = self.parts
        geometries = (
            (width, BORDER_WIDTH, x, y),
            (BORDER_WIDTH, height, x + width - BORDER_WIDTH, y),
            (width, BORDER_WIDTH, x, y + height - BORDER_WIDTH),
            (BORDER_WIDTH, height, x, y),
        )

        for part, (part_width, part_height, part_x, part_y) in zip(
            (top, right, bottom, left),
            geometries,
            strict=True,
        ):
            part.configure(bg=color)
            part.geometry(f"{part_width}x{part_height}+{part_x}+{part_y}")
            part.deiconify()
            part.lift()
            hwnd = part.winfo_id()
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOPMOST,
                part_x,
                part_y,
                part_width,
                part_height,
                win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
            )

    def destroy(self) -> None:
        for part in self.parts:
            if part.winfo_exists():
                part.destroy()
