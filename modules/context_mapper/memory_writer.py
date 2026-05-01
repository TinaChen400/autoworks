from __future__ import annotations

from typing import Any


def save_task_context(task_context: dict[str, Any]) -> None:
    raise NotImplementedError(
        "Task context persistence will be implemented after review gates exist."
    )


def save_task_context_draft(task_context: dict[str, Any]) -> None:
    raise NotImplementedError("Draft task context persistence is a future workflow placeholder.")


def create_task_context_from_model_output_placeholder(
    model_output: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "placeholder",
        "source": "model_output",
        "calls_model": False,
        "draft": model_output,
    }
