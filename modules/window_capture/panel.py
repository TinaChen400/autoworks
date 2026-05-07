from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modules.window_capture.capture import (
    ALLOWED_SCALES,
    PROJECT_ROOT,
    capture_anchor_frame,
    ensure_anchor_profile,
    resolve_anchor_frame,
    save_anchor_profile,
)
from modules.window_capture.overlay import AnchorOverlay
from modules.window_capture.target_profile import (
    describe_profile_match,
    find_matching_window,
    load_target_profile,
    save_target_profile,
)
from modules.window_capture.window_controller import (
    WindowPlacement,
    get_window_placement,
    get_window_process_id,
    is_valid_window,
    placement_to_anchor_origin,
    restore_if_moved_or_resized,
    snap_to_anchor,
)
from modules.window_capture.window_locator import WindowInfo, list_visible_windows


LOCK_INTERVAL_MS = 500


class WindowCapturePanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Autoworks Window Capture")
        self.geometry("1120x560")
        self.resizable(False, False)

        self.anchor = ensure_anchor_profile()
        self.windows: list[WindowInfo] = []
        self.selected_hwnd: int | None = None
        self.locked_hwnd: int | None = None
        self.locked_target: WindowPlacement | None = None
        self.lock_after_id: str | None = None
        self.overlay: AnchorOverlay | None = None
        self.target_profile = load_target_profile()

        self.selected_var = tk.StringVar(value="Selected target: none")
        self.scale_var = tk.StringVar(value=self._format_scale(self.anchor["scale"]))
        self.status_var = tk.StringVar(value=self._anchor_text())

        self._build_ui()
        self.refresh_windows()
        self.overlay = AnchorOverlay(self, self.anchor, locked=False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        top = ttk.Frame(root)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.columnconfigure(0, weight=1)

        ttk.Label(top, text="Visible windows").grid(row=0, column=0, sticky="w")
        ttk.Label(top, text="Scale").grid(row=0, column=1, padx=(8, 4), sticky="e")
        self.scale_box = ttk.Combobox(
            top,
            textvariable=self.scale_var,
            values=[self._format_scale(scale) for scale in ALLOWED_SCALES],
            state="readonly",
            width=6,
        )
        self.scale_box.grid(row=0, column=2, sticky="e")
        self.scale_box.bind("<<ComboboxSelected>>", self._on_scale_selected)
        ttk.Button(top, text="Refresh", command=self.refresh_windows).grid(
            row=0, column=3, padx=(8, 0)
        )

        columns = ("hwnd", "title", "class_name", "process_id", "box")
        self.window_list = ttk.Treeview(root, columns=columns, show="headings", selectmode="browse")
        self.window_list.heading("hwnd", text="hwnd")
        self.window_list.heading("title", text="title")
        self.window_list.heading("class_name", text="class_name")
        self.window_list.heading("process_id", text="process_id")
        self.window_list.heading("box", text="x,y,width,height")
        self.window_list.column("hwnd", width=90, stretch=False)
        self.window_list.column("title", width=220, stretch=True)
        self.window_list.column("class_name", width=160, stretch=True)
        self.window_list.column("process_id", width=90, stretch=False)
        self.window_list.column("box", width=150, stretch=False)
        self.window_list.grid(row=1, column=0, sticky="nsew")
        self.window_list.bind("<<TreeviewSelect>>", self._on_window_selected)

        selected = ttk.Label(root, textvariable=self.selected_var, anchor="w", justify=tk.LEFT)
        selected.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        actions = ttk.Frame(root)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 8))
        for column in range(5):
            actions.columnconfigure(column, weight=1)

        ttk.Button(actions, text="Snap", command=self.snap_selected).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(actions, text="Lock", command=self.lock_selected).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Button(actions, text="Unlock", command=self.unlock_selected).grid(
            row=0, column=2, sticky="ew", padx=6
        )
        ttk.Button(actions, text="Capture", command=self.capture_anchor).grid(
            row=0, column=3, sticky="ew", padx=(6, 0)
        )
        ttk.Button(
            actions,
            text="Use Current Window Position as Anchor Origin",
            command=self.use_current_window_as_anchor,
        ).grid(row=1, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        ttk.Button(
            actions,
            text="Select Saved Target",
            command=self.select_saved_target,
        ).grid(row=2, column=0, columnspan=5, sticky="ew", pady=(8, 0))

        ttk.Label(root, textvariable=self.status_var, anchor="w").grid(row=4, column=0, sticky="ew")

    def _anchor_text(self) -> str:
        frame = resolve_anchor_frame(self.anchor)
        return (
            "AnchorFrame "
            f"x={frame['x']}, y={frame['y']}, width={frame['width']}, height={frame['height']} "
            f"| base={self.anchor['base_width']}x{self.anchor['base_height']} "
            f"| scale={self._format_scale(self.anchor['scale'])}"
        )

    def _format_scale(self, scale: float) -> str:
        return f"{scale:g}"

    def refresh_windows(self) -> None:
        previous_selected_hwnd = self.selected_hwnd
        self._load_window_rows()

        if previous_selected_hwnd is not None and self._window_by_hwnd(previous_selected_hwnd):
            self.selected_hwnd = previous_selected_hwnd
            self.window_list.selection_set(str(previous_selected_hwnd))
            self._update_selected_info()
            self.status_var.set(f"{self._anchor_text()} | Refreshed windows.")
        elif self.select_saved_target(show_message=False, rescan=False):
            self.status_var.set(f"{self._anchor_text()} | Selected saved target.")
        else:
            self.selected_hwnd = None
            self.selected_var.set("Selected target: none")
            self.status_var.set(f"{self._anchor_text()} | Select one visible window.")

    def _load_window_rows(self) -> None:
        self.windows = list_visible_windows(
            exclude_foreground=False,
            exclude_process_ids={os.getpid()},
        )
        children = self.window_list.get_children()
        if children:
            self.window_list.delete(*children)
        for window in self.windows:
            self.window_list.insert(
                "",
                tk.END,
                iid=str(window.hwnd),
                values=(
                    window.hwnd,
                    window.title,
                    window.class_name,
                    window.process_id,
                    self._box_text(window.box),
                ),
            )

    def _on_window_selected(self, _event: tk.Event) -> None:
        selection = self.window_list.selection()
        if not selection:
            self.selected_hwnd = None
            self.selected_var.set("Selected target: none")
            return

        selected = self._window_by_hwnd(int(selection[0]))
        if selected is None:
            self.selected_hwnd = None
            self.selected_var.set("Selected target: none")
            return

        self.selected_hwnd = selected.hwnd
        self.selected_var.set(
            "Selected target: "
            f"hwnd={selected.hwnd} | title={selected.title} | class={selected.class_name} | "
            f"box={self._box_text(get_window_placement(selected.hwnd))}"
        )
        self.status_var.set(f"Selected hwnd={selected.hwnd}.")

    def _window_by_hwnd(self, hwnd: int) -> WindowInfo | None:
        for window in self.windows:
            if window.hwnd == hwnd:
                return window
        return None

    def _box_text(self, placement: WindowPlacement) -> str:
        return f"{placement.left},{placement.top},{placement.width},{placement.height}"

    def _require_selected_hwnd(self) -> int | None:
        if self.selected_hwnd is None:
            messagebox.showwarning("No target selected", "Select one target window first.")
            return None
        if not is_valid_window(self.selected_hwnd):
            messagebox.showerror("Target unavailable", "The selected window no longer exists.")
            self.selected_hwnd = None
            self.unlock_selected()
            return None
        if get_window_process_id(self.selected_hwnd) == os.getpid():
            messagebox.showerror("Invalid target", "The panel and overlay cannot be locked.")
            self.selected_hwnd = None
            self.unlock_selected()
            self.refresh_windows()
            return None
        return self.selected_hwnd

    def snap_selected(self) -> None:
        hwnd = self._require_selected_hwnd()
        if hwnd is None:
            return

        target = snap_to_anchor(hwnd, self.anchor)
        self._update_overlay()
        self.status_var.set(
            f"Snapped hwnd={hwnd} to {target.width}x{target.height} "
            f"at {target.left},{target.top}."
        )

    def lock_selected(self) -> None:
        hwnd = self._require_selected_hwnd()
        if hwnd is None:
            return

        self.locked_hwnd = hwnd
        self.locked_target = snap_to_anchor(hwnd, self.anchor)
        self._schedule_lock_check()
        self._update_overlay()
        self.status_var.set(f"Locked hwnd={hwnd} to AnchorFrame.")

    def _schedule_lock_check(self) -> None:
        if self.lock_after_id is not None:
            self.after_cancel(self.lock_after_id)
        self.lock_after_id = self.after(LOCK_INTERVAL_MS, self._lock_check)

    def _lock_check(self) -> None:
        self.lock_after_id = None
        if self.locked_hwnd is None or self.locked_target is None:
            return

        if not is_valid_window(self.locked_hwnd):
            self.status_var.set("Locked target closed. Lock released.")
            self.unlock_selected()
            return

        restored = restore_if_moved_or_resized(self.locked_hwnd, self.locked_target)
        if restored:
            self.status_var.set(f"Restored hwnd={self.locked_hwnd} to AnchorFrame.")

        self._update_overlay()
        self._schedule_lock_check()

    def unlock_selected(self) -> None:
        if self.lock_after_id is not None:
            self.after_cancel(self.lock_after_id)
            self.lock_after_id = None
        self.locked_hwnd = None
        self.locked_target = None
        self._update_overlay()
        self.status_var.set("Unlocked.")

    def capture_anchor(self) -> None:
        output_path = PROJECT_ROOT / "runtime_state" / "latest_capture.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        capture_anchor_frame(self.anchor, output_path=output_path)
        self.status_var.set("Captured AnchorFrame to runtime_state/latest_capture.png")

    def use_current_window_as_anchor(self) -> None:
        hwnd = self._require_selected_hwnd()
        if hwnd is None:
            return

        selected = self._window_by_hwnd(hwnd)
        if selected is not None:
            self.target_profile = save_target_profile(selected)

        placement = get_window_placement(hwnd)
        self.anchor = save_anchor_profile(placement_to_anchor_origin(placement, self.anchor))
        if self.locked_hwnd == hwnd:
            self.locked_target = snap_to_anchor(hwnd, self.anchor)
        self._update_selected_info()
        self._update_overlay()
        self.status_var.set(
            f"Saved current hwnd={hwnd} x/y as Anchor origin: {self._anchor_text()}."
        )

    def _on_scale_selected(self, _event: tk.Event) -> None:
        self.anchor["scale"] = float(self.scale_var.get())
        self.anchor = save_anchor_profile(self.anchor)
        if self.locked_hwnd is not None:
            self.locked_target = snap_to_anchor(self.locked_hwnd, self.anchor)
        self._update_overlay()
        self.status_var.set(f"Saved scale {self.scale_var.get()}: {self._anchor_text()}.")

    def select_saved_target(self, *, show_message: bool = True, rescan: bool = True) -> bool:
        self.status_var.set("Searching saved target...")
        self.update_idletasks()

        if rescan:
            self._load_window_rows()

        self.target_profile = load_target_profile()
        matched = find_matching_window(self.windows, self.target_profile)
        if matched is None:
            reason = describe_profile_match(self.windows, self.target_profile)
            self.status_var.set(reason)
            if show_message:
                messagebox.showwarning("Saved target not selected", reason)
            return False

        self.selected_hwnd = matched.hwnd
        self.window_list.selection_set(str(matched.hwnd))
        self.window_list.see(str(matched.hwnd))
        self._update_selected_info()
        if show_message:
            self.status_var.set(f"Selected saved target hwnd={matched.hwnd}.")
            messagebox.showinfo(
                "Saved target selected",
                f"Selected hwnd={matched.hwnd}\n"
                f"title={matched.title}\n"
                f"class={matched.class_name}",
            )
        return True

    def _update_selected_info(self) -> None:
        if self.selected_hwnd is None or not is_valid_window(self.selected_hwnd):
            self.selected_var.set("Selected target: none")
            return

        selected = self._window_by_hwnd(self.selected_hwnd)
        title = selected.title if selected is not None else "<unknown>"
        class_name = selected.class_name if selected is not None else "<unknown>"
        self.selected_var.set(
            "Selected target: "
            f"hwnd={self.selected_hwnd} | title={title} | class={class_name} | "
            f"box={self._box_text(get_window_placement(self.selected_hwnd))}"
        )

    def _update_overlay(self) -> None:
        if self.overlay is not None:
            self.overlay.update(self.anchor, locked=self.locked_hwnd is not None)

    def _on_close(self) -> None:
        if self.lock_after_id is not None:
            self.after_cancel(self.lock_after_id)
            self.lock_after_id = None
        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None
        self.destroy()


def main() -> None:
    app = WindowCapturePanel()
    app.mainloop()


if __name__ == "__main__":
    main()
