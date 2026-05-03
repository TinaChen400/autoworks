from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from modules.parse_orchestrator.input_loader import (
    load_config,
    load_layout_index,
    load_runtime_context,
)
from modules.parse_orchestrator.orchestrator import run_orchestrated_parse
from modules.parse_orchestrator.parse_plan_store import (
    ORCHESTRATED_PARSE_PATH,
    PARSE_METRICS_PATH,
    PARSE_PLAN_PATH,
    load_if_exists,
    save_parse_plan,
)
from modules.parse_orchestrator.strategy_selector import select_strategy


class ParseOrchestratorPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Parse Orchestrator")
        self.geometry("980x760")
        self.mode_var = tk.StringVar(value="fake")
        self.parser_var = tk.StringVar(value="auto")
        self._build()
        self.refresh_status()

    def _build(self) -> None:
        controls = ttk.Frame(self, padding=8)
        controls.pack(fill=tk.X)
        ttk.Label(controls, text="Mode").pack(side=tk.LEFT)
        ttk.Combobox(
            controls,
            textvariable=self.mode_var,
            values=["fake", "doubao"],
            width=10,
            state="readonly",
        ).pack(side=tk.LEFT, padx=6)
        ttk.Label(controls, text="Parser").pack(side=tk.LEFT)
        ttk.Combobox(
            controls,
            textvariable=self.parser_var,
            values=[
                "auto",
                "form",
                "survey",
                "image_task",
                "drag_drop",
                "matrix",
                "modal",
                "general",
            ],
            width=14,
            state="readonly",
        ).pack(side=tk.LEFT, padx=6)
        ttk.Button(controls, text="Generate Parse Plan", command=self.generate_plan).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(controls, text="Run Orchestrated Parse", command=self.run_parse).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(controls, text="Refresh", command=self.refresh_status).pack(side=tk.LEFT, padx=6)

        self.status = tk.Text(self, height=14, wrap=tk.WORD)
        self.status.pack(fill=tk.X, padx=8, pady=4)
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.plan_text = self._tab(notebook, "Plan")
        self.metrics_text = self._tab(notebook, "Metrics")
        self.parse_text = self._tab(notebook, "Orchestrated")

    def _tab(self, notebook: ttk.Notebook, label: str) -> tk.Text:
        frame = ttk.Frame(notebook)
        text = tk.Text(frame, wrap=tk.NONE)
        text.pack(fill=tk.BOTH, expand=True)
        notebook.add(frame, text=label)
        return text

    def refresh_status(self) -> None:
        self.status.delete("1.0", tk.END)
        try:
            runtime_context = load_runtime_context()
            layout_index = load_layout_index()
            hints = dict(layout_index.get("layout_hints") or {})
            config = load_config()
            plan, _ = select_strategy(
                runtime_context,
                layout_index,
                config,
                mode=self.mode_var.get(),
                parser_type=self.parser_var.get(),
            )
            lines = [
                f"Runtime context: loaded task_id={runtime_context.get('task_id', '')}",
                "Layout index: loaded",
                f"Detector scores: {hints.get('detector_scores', {})}",
                f"Possible page types: {hints.get('possible_page_types', [])}",
                "Recommended regions: "
                f"{hints.get('recommended_regions_for_detail_parse', [])}",
                f"Selected strategy preview: {plan.selected_strategy}",
                f"Warnings: {plan.crop_safety_summary.get('unsafe_region_ids', [])}",
            ]
        except Exception as exc:  # noqa: BLE001 - panel should display status instead of crashing.
            lines = [str(exc)]
        self.status.insert(tk.END, "\n".join(lines))
        self._load_previews()

    def _set_json(self, widget: tk.Text, data: dict[str, Any]) -> None:
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, json.dumps(data, indent=2, ensure_ascii=False))

    def _load_previews(self) -> None:
        self._set_json(self.plan_text, load_if_exists(PARSE_PLAN_PATH))
        self._set_json(self.metrics_text, load_if_exists(PARSE_METRICS_PATH))
        self._set_json(self.parse_text, load_if_exists(ORCHESTRATED_PARSE_PATH))

    def generate_plan(self) -> None:
        try:
            plan, _ = select_strategy(
                load_runtime_context(),
                load_layout_index(),
                load_config(),
                mode=self.mode_var.get(),
                parser_type=self.parser_var.get(),
            )
            save_parse_plan(plan.to_dict())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Parse Orchestrator", str(exc))
        self.refresh_status()

    def run_parse(self) -> None:
        try:
            run_orchestrated_parse(mode=self.mode_var.get(), parser_type=self.parser_var.get())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Parse Orchestrator", str(exc))
        self.refresh_status()


def main() -> None:
    ParseOrchestratorPanel().mainloop()


if __name__ == "__main__":
    main()
