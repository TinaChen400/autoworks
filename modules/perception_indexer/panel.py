from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

from modules.perception_indexer.image_loader import get_model_input_region, load_runtime_context, load_screenshot
from modules.perception_indexer.index_store import ANNOTATED_OVERVIEW_PATH, LAYOUT_INDEX_PATH
from modules.perception_indexer.indexer import build_layout_index


class PerceptionIndexerPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Perception Indexer")
        self.geometry("1200x820")
        self.minsize(900, 620)
        self.ocr_backend = tk.StringVar(value="disabled")
        self.screenshot_path = tk.StringVar(value="")
        self.model_input_region = tk.StringVar(value="")
        self.annotated_overview_path = tk.StringVar(value="")
        self.counts = tk.StringVar(value="regions=0 elements=0 text_blocks=0 warnings=0")
        self.selected_region = tk.StringVar(value="")
        self.selected_region_crop = tk.StringVar(value="")
        self.status = tk.StringVar(value="Not loaded")
        self.layout_index: dict | None = None
        self.preview_image: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        controls = ttk.Frame(self, padding=8)
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Button(controls, text="Load Runtime Context", command=self.load_context).grid(row=0, column=0, padx=4)
        ttk.Label(controls, text="OCR").grid(row=0, column=1, padx=(16, 4))
        ttk.Combobox(
            controls,
            textvariable=self.ocr_backend,
            values=["disabled", "tesseract", "rapidocr"],
            state="readonly",
            width=12,
        ).grid(row=0, column=2)
        ttk.Button(controls, text="Run Indexer", command=self.run_indexer).grid(row=0, column=3, padx=8)
        ttk.Label(controls, textvariable=self.status).grid(row=0, column=4, sticky="w", padx=8)

        meta = ttk.Frame(self, padding=(8, 0, 8, 6))
        meta.grid(row=1, column=0, sticky="ew")
        meta.columnconfigure(1, weight=1)
        for row, (label, value) in enumerate(
            (
                ("screenshot path", self.screenshot_path),
                ("model input region", self.model_input_region),
                ("annotated overview", self.annotated_overview_path),
                ("counts", self.counts),
                ("selected card crop", self.selected_region_crop),
            )
        ):
            ttk.Label(meta, text=label).grid(row=row, column=0, sticky="w")
            ttk.Label(meta, textvariable=value).grid(row=row, column=1, sticky="ew")

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.grid(row=3, column=0, sticky="nsew", padx=8, pady=6)
        self.preview_canvas = tk.Canvas(panes, background="#1f1f1f", highlightthickness=0)
        self.preview_canvas.bind("<Configure>", lambda _event: self._draw_preview())
        panes.add(self.preview_canvas, weight=2)

        notebook = ttk.Notebook(panes)
        self.hints_text = self._text_tab(notebook, "Layout Hints")
        self.children_text = self._text_tab(notebook, "Selected Region")
        self.regions_text = self._text_tab(notebook, "Regions")
        self.elements_text = self._text_tab(notebook, "Elements")
        panes.add(notebook, weight=1)

        selector = ttk.Frame(self, padding=(8, 0, 8, 4))
        selector.grid(row=2, column=0, sticky="ew")
        ttk.Label(selector, text="Region").grid(row=0, column=0, sticky="w")
        self.region_combo = ttk.Combobox(
            selector,
            textvariable=self.selected_region,
            values=[],
            state="readonly",
            width=48,
        )
        self.region_combo.grid(row=0, column=1, sticky="w", padx=6)
        self.region_combo.bind("<<ComboboxSelected>>", lambda _event: self._show_selected_region())

    def _text_tab(self, notebook: ttk.Notebook, title: str) -> tk.Text:
        frame = ttk.Frame(notebook)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text = tk.Text(frame, wrap="word")
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scrollbar.set)
        notebook.add(frame, text=title)
        return text

    def load_context(self) -> None:
        try:
            runtime_context = load_runtime_context()
            image, path = load_screenshot(runtime_context)
        except FileNotFoundError as exc:
            self.status.set(str(exc))
            return
        region = get_model_input_region(runtime_context, image)
        self.screenshot_path.set(str(path))
        self.model_input_region.set(json.dumps(region.to_dict()))
        self.status.set("Runtime context loaded")
        self._load_existing_index()

    def run_indexer(self) -> None:
        try:
            self.layout_index = build_layout_index(ocr_backend=self.ocr_backend.get())
        except FileNotFoundError as exc:
            self.status.set(str(exc))
            return
        self.status.set("Indexer complete")
        self._show_index()

    def _load_existing_index(self) -> None:
        if LAYOUT_INDEX_PATH.exists():
            self.layout_index = json.loads(LAYOUT_INDEX_PATH.read_text(encoding="utf-8"))
            self._show_index()

    def _show_index(self) -> None:
        if not self.layout_index:
            return
        self.annotated_overview_path.set(str(self.layout_index.get("annotated_overview", "")))
        self.counts.set(
            "regions={regions} cards={cards} elements={elements} text_blocks={texts} warnings={warnings}".format(
                regions=len(self.layout_index.get("regions", [])),
                cards=len(self.layout_index.get("layout_hints", {}).get("card_region_ids", [])),
                elements=len(self.layout_index.get("elements", [])),
                texts=len(self.layout_index.get("text_blocks", [])),
                warnings=len(self.layout_index.get("warnings", [])),
            )
        )
        self._replace_text(self.hints_text, json.dumps(self.layout_index.get("layout_hints", {}), indent=2))
        self._replace_text(self.regions_text, json.dumps(self.layout_index.get("regions", []), indent=2))
        self._replace_text(self.elements_text, json.dumps(self.layout_index.get("elements", []), indent=2))
        region_values = [
            f"{region.get('region_id')} {region.get('region_type_hint')}"
            for region in self.layout_index.get("regions", [])
        ]
        self.region_combo.configure(values=region_values)
        if region_values and not self.selected_region.get():
            self.selected_region.set(region_values[0])
            self._show_selected_region()
        overview = Path(str(self.layout_index.get("annotated_overview", ANNOTATED_OVERVIEW_PATH)))
        if overview.exists():
            self.preview_image = Image.open(overview).convert("RGB")
            self._draw_preview()

    def _show_selected_region(self) -> None:
        if not self.layout_index:
            return
        region_id = self.selected_region.get().split(" ", 1)[0]
        regions = self.layout_index.get("regions", [])
        elements = self.layout_index.get("elements", [])
        texts = self.layout_index.get("text_blocks", [])
        region = next((item for item in regions if item.get("region_id") == region_id), None)
        if not region:
            return
        child_regions = [
            item for item in regions if item.get("metadata", {}).get("parent_region_id") == region_id
        ]
        child_elements = [
            item for item in elements if item.get("region_id") == region_id
        ]
        child_texts = [
            item for item in texts if item.get("associated_region_id") == region_id
        ]
        self.selected_region_crop.set(str(region.get("annotated_crop_path") or region.get("crop_path") or ""))
        self._replace_text(
            self.children_text,
            json.dumps(
                {
                    "region": region,
                    "child_regions": child_regions,
                    "elements": child_elements,
                    "text_blocks": child_texts,
                },
                indent=2,
            ),
        )

    def _draw_preview(self) -> None:
        self.preview_canvas.delete("all")
        if self.preview_image is None:
            return
        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        scale = min(canvas_width / self.preview_image.width, canvas_height / self.preview_image.height)
        width = max(1, int(self.preview_image.width * scale))
        height = max(1, int(self.preview_image.height * scale))
        offset_x = (canvas_width - width) // 2
        offset_y = (canvas_height - height) // 2
        self.preview_photo = ImageTk.PhotoImage(self.preview_image.resize((width, height)))
        self.preview_canvas.create_image(offset_x, offset_y, anchor=tk.NW, image=self.preview_photo)

    @staticmethod
    def _replace_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)


def main() -> None:
    panel = PerceptionIndexerPanel()
    panel.mainloop()


if __name__ == "__main__":
    main()
