from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from modules.context_mapper.capture_context import (
    DEFAULT_RUNTIME_CONTEXT_PATH,
    build_runtime_context,
)
from modules.context_mapper.coordinate_mapper import map_model_norm
from modules.context_mapper.prompt_builder import build_prompt_bundle
from modules.context_mapper.task_context_loader import load_effective_task_context
from modules.context_mapper.task_registry import list_task_ids


class ContextMapperPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Context Mapper")
        self.geometry("1100x760")
        self.minsize(820, 560)

        self.task_ids = list_task_ids()
        self.selected_task = tk.StringVar(value=self.task_ids[0] if self.task_ids else "")
        self.norm_x = tk.StringVar(value="0.5")
        self.norm_y = tk.StringVar(value="0.5")
        self.current_loaded_task = tk.StringVar(value="Current loaded task: none")
        self.runtime_status = tk.StringVar(value="Runtime context: not generated")
        self.output_status = tk.StringVar(value="")
        self.loaded_task_id: str | None = None
        self.runtime_context: dict | None = None
        self.effective_context: dict | None = None

        self._build_ui()
        if self.task_ids:
            self.output_status.set("Select a task, then click Load Task.")

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        top = ttk.Frame(self, padding=8)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Task").grid(row=0, column=0, sticky="w")
        picker = ttk.Combobox(
            top,
            textvariable=self.selected_task,
            values=self.task_ids,
            state="readonly",
        )
        picker.grid(row=0, column=1, sticky="ew", padx=8)
        picker.bind("<<ComboboxSelected>>", lambda _event: self.on_task_selected())
        self.task_picker = picker

        ttk.Button(top, text="Load Task", command=self.load_selected_task).grid(
            row=0,
            column=2,
            padx=4,
        )
        ttk.Button(top, text="Reload Task List", command=self.reload_task_list).grid(
            row=0,
            column=3,
            padx=4,
        )

        ttk.Button(
            top,
            text="Generate Runtime Context",
            command=self.generate_runtime_context,
        ).grid(row=0, column=4, padx=4)
        ttk.Button(top, text="Test Coordinate Mapping", command=self.test_coordinate_mapping).grid(
            row=0,
            column=5,
            padx=4,
        )

        meta = ttk.Frame(self, padding=(8, 0, 8, 8))
        meta.grid(row=1, column=0, sticky="ew")
        meta.columnconfigure(1, weight=1)
        meta.columnconfigure(3, weight=1)

        ttk.Label(meta, text="Task family").grid(row=0, column=0, sticky="w")
        self.family_value = ttk.Label(meta, text="")
        self.family_value.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(meta, text="Inherited templates").grid(row=0, column=2, sticky="w")
        self.inherits_value = ttk.Label(meta, text="", wraplength=520)
        self.inherits_value.grid(row=0, column=3, sticky="ew", padx=8)
        ttk.Label(meta, text="Supported question types").grid(row=1, column=0, sticky="w")
        self.question_types_value = ttk.Label(meta, text="", wraplength=900)
        self.question_types_value.grid(row=1, column=1, columnspan=3, sticky="ew", padx=8, pady=4)

        status = ttk.Frame(self, padding=(8, 0, 8, 8))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        status.columnconfigure(1, weight=1)
        ttk.Label(status, textvariable=self.current_loaded_task).grid(row=0, column=0, sticky="w")
        ttk.Label(status, textvariable=self.runtime_status).grid(row=0, column=1, sticky="w")

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.grid(row=3, column=0, sticky="nsew", padx=8, pady=4)

        self.vision_text = self._prompt_box(panes, "Vision Prompt Preview")
        self.answer_text = self._prompt_box(panes, "Answer Prompt Preview")

        bottom = ttk.Frame(self, padding=8)
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.columnconfigure(6, weight=1)
        ttk.Label(bottom, text="norm_x").grid(row=0, column=0, sticky="w")
        ttk.Entry(bottom, textvariable=self.norm_x, width=10).grid(row=0, column=1, padx=4)
        ttk.Label(bottom, text="norm_y").grid(row=0, column=2, sticky="w")
        ttk.Entry(bottom, textvariable=self.norm_y, width=10).grid(row=0, column=3, padx=4)
        ttk.Label(bottom, text="Output").grid(row=0, column=4, sticky="w", padx=(12, 4))
        self.output_value = ttk.Label(bottom, textvariable=self.output_status, wraplength=760)
        self.output_value.grid(row=0, column=5, columnspan=2, sticky="ew")

    def _prompt_box(self, panes: ttk.PanedWindow, title: str) -> tk.Text:
        frame = ttk.Frame(panes)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title).grid(row=0, column=0, sticky="w")
        text = tk.Text(frame, wrap="word", height=20)
        text.grid(row=1, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        text.configure(yscrollcommand=yscroll.set)
        panes.add(frame, weight=1)
        return text

    def load_selected_task(self) -> None:
        task_id = self.selected_task.get()
        if not task_id:
            self.output_status.set("No task selected.")
            return

        self.effective_context = load_effective_task_context(task_id)
        prompts = build_prompt_bundle(self.effective_context)
        self.loaded_task_id = task_id
        self.runtime_context = None
        self.current_loaded_task.set(f"Current loaded task: {task_id}")
        self.runtime_status.set("Runtime context: not generated")
        self.family_value.configure(text=str(self.effective_context.get("task_family", "")))
        self.inherits_value.configure(text=", ".join(self.effective_context.get("inherits", [])))
        self.question_types_value.configure(
            text=", ".join(self.effective_context.get("supported_question_types", []))
        )
        self._replace_text(self.vision_text, prompts["vision_prompt"])
        self._replace_text(self.answer_text, prompts["answer_prompt"])
        self.output_status.set(f"Loaded task: {task_id}")

    def on_task_selected(self) -> None:
        task_id = self.selected_task.get()
        self.output_status.set(f"Selected task: {task_id}. Click Load Task to load it.")

    def reload_task_list(self) -> None:
        self.task_ids = list_task_ids()
        self.task_picker.configure(values=self.task_ids)
        if self.selected_task.get() not in self.task_ids:
            self.selected_task.set(self.task_ids[0] if self.task_ids else "")
        self.output_status.set("Reloaded task list from task_contexts/registry.json")

    def generate_runtime_context(self) -> None:
        if self.loaded_task_id is None:
            self.output_status.set("No task loaded. Select a task, then click Load Task first.")
            return

        self.runtime_context = build_runtime_context(self.loaded_task_id)
        self.runtime_status.set("Runtime context: generated")
        anchor = self.runtime_context["anchor_frame"]
        model_region = self.runtime_context["model_input_region"]
        screenshot_path = self.runtime_context["screenshot_path"]
        self.output_status.set(
            "\n".join(
                [
                    f"Generated runtime context: {DEFAULT_RUNTIME_CONTEXT_PATH}",
                    f"screenshot path: {screenshot_path}",
                    f"AnchorFrame: {anchor}",
                    f"ModelInputRegion: {model_region}",
                ]
            )
        )

    def test_coordinate_mapping(self) -> None:
        if self.runtime_context is None:
            self.output_status.set(
                "Runtime context not generated. Click Generate Runtime Context first."
            )
            return

        mapped = map_model_norm(
            float(self.norm_x.get()),
            float(self.norm_y.get()),
            self.runtime_context,
        )
        norm = mapped["norm_coordinate"]
        image_px = mapped["image_pixel_coordinate"]
        screen_px = mapped["screen_pixel_coordinate"]
        self.output_status.set(
            "\n".join(
                [
                    f"norm coordinate: ({norm['x']}, {norm['y']})",
                    f"image pixel coordinate: ({image_px['x']}, {image_px['y']})",
                    f"screen pixel coordinate: ({screen_px['x']}, {screen_px['y']})",
                ]
            )
        )

    @staticmethod
    def _replace_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)


def main() -> None:
    panel = ContextMapperPanel()
    panel.mainloop()


if __name__ == "__main__":
    main()
