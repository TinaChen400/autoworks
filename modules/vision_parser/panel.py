from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from modules.vision_parser.doubao_client import VisionModelError
from modules.vision_parser.image_payload import prepare_model_input_image
from modules.vision_parser.parser import parse_latest_runtime_context
from modules.vision_parser.parse_store import (
    MODEL_INPUT_PATH,
    PARSED_PAGE_PATH,
    RAW_RESPONSE_PATH,
    VALIDATION_REPORT_PATH,
    load_runtime_context,
    write_json,
)
from modules.vision_parser.prompt import build_final_prompt
from modules.vision_parser.response_validator import ValidationError


class VisionParserPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Vision Parser")
        self.geometry("1200x820")
        self.minsize(900, 620)

        self.mode = tk.StringVar(value="fake")
        self.task_id = tk.StringVar(value="")
        self.screenshot_path = tk.StringVar(value="")
        self.model_input_region = tk.StringVar(value="")
        self.validation_status = tk.StringVar(value="Validation: not run")
        self.image_status = tk.StringVar(value="Image: not loaded")
        self.runtime_context: dict | None = None
        self.parsed_page: dict | None = None
        self.preview_image: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        controls = ttk.Frame(self, padding=8)
        controls.grid(row=0, column=0, sticky="ew")

        ttk.Button(controls, text="Load Runtime Context", command=self.load_context).grid(
            row=0,
            column=0,
            padx=4,
        )
        ttk.Label(controls, text="Mode").grid(row=0, column=1, sticky="w", padx=(12, 4))
        ttk.Combobox(
            controls,
            textvariable=self.mode,
            values=["fake", "doubao"],
            state="readonly",
            width=10,
        ).grid(row=0, column=2, sticky="w")
        ttk.Button(controls, text="Parse Screenshot", command=self.parse_screenshot).grid(
            row=0,
            column=3,
            padx=8,
        )
        ttk.Label(controls, textvariable=self.validation_status).grid(row=0, column=4, sticky="w")

        meta = ttk.Frame(self, padding=(8, 0, 8, 8))
        meta.grid(row=1, column=0, sticky="ew")
        meta.columnconfigure(1, weight=1)
        ttk.Label(meta, text="task_id").grid(row=0, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.task_id).grid(row=0, column=1, sticky="ew")
        ttk.Label(meta, text="screenshot path").grid(row=1, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.screenshot_path).grid(row=1, column=1, sticky="ew")
        ttk.Label(meta, text="model input region").grid(row=2, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.model_input_region).grid(row=2, column=1, sticky="ew")

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        self._build_preview_pane(panes)
        self._build_text_tabs(panes)

    def _build_preview_pane(self, panes: ttk.PanedWindow) -> None:
        frame = ttk.Frame(panes)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Model Input Overlay").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.image_status).grid(row=0, column=1, sticky="e", padx=8)
        header.columnconfigure(1, weight=1)

        self.preview_canvas = tk.Canvas(frame, background="#1f1f1f", highlightthickness=0)
        self.preview_canvas.grid(row=1, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda _event: self._draw_preview())
        panes.add(frame, weight=2)

    def _build_text_tabs(self, panes: ttk.PanedWindow) -> None:
        notebook = ttk.Notebook(panes)
        self.prompt_text = self._text_tab(notebook, "Prompt")
        self.raw_text = self._text_tab(notebook, "Raw Response")
        self.parsed_text = self._text_tab(notebook, "Parsed JSON")
        panes.add(notebook, weight=1)

    def _text_tab(self, notebook: ttk.Notebook, title: str) -> tk.Text:
        frame = ttk.Frame(notebook)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title).grid(row=0, column=0, sticky="w")
        text = tk.Text(frame, wrap="word", height=24)
        text.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        text.configure(yscrollcommand=scrollbar.set)
        notebook.add(frame, text=title)
        return text

    def load_context(self) -> None:
        try:
            self.runtime_context = load_runtime_context()
        except FileNotFoundError as exc:
            self.validation_status.set(str(exc))
            return
        self.task_id.set(str(self.runtime_context.get("task_id", "")))
        self.screenshot_path.set(str(self.runtime_context.get("screenshot_path", "")))
        self.model_input_region.set(json.dumps(self.runtime_context.get("model_input_region", {})))
        self._replace_text(self.prompt_text, build_final_prompt(self.runtime_context))
        self._prepare_and_load_preview_image()
        self.validation_status.set("Validation: context loaded")

    def parse_screenshot(self) -> None:
        try:
            parsed = parse_latest_runtime_context(mode=self.mode.get())
        except (FileNotFoundError, ValidationError, VisionModelError, ValueError) as exc:
            self.validation_status.set(f"Validation: failed - {exc}")
            self._load_output_files()
            return
        write_json(PARSED_PAGE_PATH, parsed)
        self.parsed_page = parsed
        self.validation_status.set("Validation: passed")
        self._load_output_files()
        self._load_preview_from_files()

    def _load_output_files(self) -> None:
        if RAW_RESPONSE_PATH.exists():
            self._replace_text(self.raw_text, RAW_RESPONSE_PATH.read_text(encoding="utf-8"))
        if PARSED_PAGE_PATH.exists():
            self._replace_text(self.parsed_text, PARSED_PAGE_PATH.read_text(encoding="utf-8-sig"))
            self.parsed_page = json.loads(PARSED_PAGE_PATH.read_text(encoding="utf-8-sig"))
        elif VALIDATION_REPORT_PATH.exists():
            self._replace_text(
                self.parsed_text,
                VALIDATION_REPORT_PATH.read_text(encoding="utf-8-sig"),
            )

    def _prepare_and_load_preview_image(self) -> None:
        if not self.runtime_context:
            return
        try:
            prepare_model_input_image(
                screenshot_path=self.runtime_context.get("screenshot_path", ""),
                model_input_region=self.runtime_context.get("model_input_region"),
                output_path=MODEL_INPUT_PATH,
            )
        except (FileNotFoundError, ValueError) as exc:
            self.image_status.set(f"Image: failed - {exc}")
            return
        self._load_preview_from_files()

    def _load_preview_from_files(self) -> None:
        if MODEL_INPUT_PATH.exists():
            self.preview_image = Image.open(MODEL_INPUT_PATH).convert("RGB")
            self.image_status.set(
                f"Image: {self.preview_image.width}x{self.preview_image.height}"
            )
        if PARSED_PAGE_PATH.exists():
            self.parsed_page = json.loads(PARSED_PAGE_PATH.read_text(encoding="utf-8-sig"))
        self._draw_preview()

    def _draw_preview(self) -> None:
        self.preview_canvas.delete("all")
        if self.preview_image is None:
            return

        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        image_width, image_height = self.preview_image.size
        scale = min(canvas_width / image_width, canvas_height / image_height)
        display_width = max(1, int(image_width * scale))
        display_height = max(1, int(image_height * scale))
        offset_x = (canvas_width - display_width) // 2
        offset_y = (canvas_height - display_height) // 2

        resized = self.preview_image.resize((display_width, display_height))
        self.preview_photo = ImageTk.PhotoImage(resized)
        self.preview_canvas.create_image(offset_x, offset_y, anchor=tk.NW, image=self.preview_photo)

        if self.parsed_page:
            self._draw_parsed_overlay(offset_x, offset_y, display_width, display_height)

    def _draw_parsed_overlay(
        self,
        offset_x: int,
        offset_y: int,
        display_width: int,
        display_height: int,
    ) -> None:
        for question in self.parsed_page.get("questions", []):
            question_id = str(question.get("question_id", "q"))
            self._draw_bbox(
                question.get("question_stem", {}).get("bbox_norm"),
                offset_x,
                offset_y,
                display_width,
                display_height,
                "#3b82f6",
                f"{question_id} stem",
            )
            for index, option in enumerate(question.get("answer_options", []), start=1):
                self._draw_bbox(
                    option.get("bbox_norm"),
                    offset_x,
                    offset_y,
                    display_width,
                    display_height,
                    "#22c55e",
                    f"{question_id} opt{index}",
                )
                self._draw_point(
                    option.get("click_point_norm"),
                    offset_x,
                    offset_y,
                    display_width,
                    display_height,
                    "#22c55e",
                )
            for index, field in enumerate(question.get("input_fields", []), start=1):
                self._draw_bbox(
                    field.get("bbox_norm"),
                    offset_x,
                    offset_y,
                    display_width,
                    display_height,
                    "#f97316",
                    f"{question_id} field{index}",
                )
                self._draw_point(
                    field.get("click_point_norm"),
                    offset_x,
                    offset_y,
                    display_width,
                    display_height,
                    "#f97316",
                )
            for index, media in enumerate(question.get("media", []), start=1):
                self._draw_bbox(
                    media.get("bbox_norm"),
                    offset_x,
                    offset_y,
                    display_width,
                    display_height,
                    "#a855f7",
                    f"{question_id} media{index}",
                )

        for index, button in enumerate(self.parsed_page.get("navigation_buttons", []), start=1):
            self._draw_bbox(
                button.get("bbox_norm"),
                offset_x,
                offset_y,
                display_width,
                display_height,
                "#ef4444",
                f"nav{index} {button.get('action', '')}",
            )
            self._draw_point(
                button.get("click_point_norm"),
                offset_x,
                offset_y,
                display_width,
                display_height,
                "#ef4444",
            )

    def _draw_bbox(
        self,
        bbox: dict | None,
        offset_x: int,
        offset_y: int,
        display_width: int,
        display_height: int,
        color: str,
        label: str,
    ) -> None:
        if not bbox:
            return
        x1 = offset_x + float(bbox.get("x", 0)) * display_width
        y1 = offset_y + float(bbox.get("y", 0)) * display_height
        x2 = x1 + float(bbox.get("width", 0)) * display_width
        y2 = y1 + float(bbox.get("height", 0)) * display_height
        if x2 <= x1 or y2 <= y1:
            return
        self.preview_canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2)
        text_id = self.preview_canvas.create_text(
            x1 + 4,
            max(offset_y + 10, y1 - 10),
            anchor=tk.W,
            fill="white",
            text=label,
        )
        bbox_text = self.preview_canvas.bbox(text_id)
        if bbox_text:
            bg_id = self.preview_canvas.create_rectangle(bbox_text, fill=color, outline=color)
            self.preview_canvas.tag_lower(bg_id, text_id)

    def _draw_point(
        self,
        point: dict | None,
        offset_x: int,
        offset_y: int,
        display_width: int,
        display_height: int,
        color: str,
    ) -> None:
        if not point:
            return
        x = offset_x + float(point.get("x", 0)) * display_width
        y = offset_y + float(point.get("y", 0)) * display_height
        radius = 4
        self.preview_canvas.create_oval(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            outline=color,
            fill=color,
        )
        self.preview_canvas.create_line(x - 8, y, x + 8, y, fill=color, width=2)
        self.preview_canvas.create_line(x, y - 8, x, y + 8, fill=color, width=2)

    @staticmethod
    def _replace_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)


def main() -> None:
    panel = VisionParserPanel()
    panel.mainloop()


if __name__ == "__main__":
    main()
