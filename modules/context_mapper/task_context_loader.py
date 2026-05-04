from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from modules.context_mapper.question_type_rules import normalize_question_types
from modules.context_mapper.task_registry import (
    REGISTRY_PATH,
    TASK_CONTEXT_ROOT,
    get_task_entry,
    resolve_context_path,
)
from modules.context_mapper.template_merger import merge_contexts

FORBIDDEN_COORDINATE_KEYS = {
    "fixed_answer_coordinates",
    "answer_coordinates",
    "old_coordinates",
    "click_points",
}


def load_json_context(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Task context file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    _reject_fixed_answer_coordinates(data, path)
    return data


def load_effective_task_context(
    task_id: str,
    registry_path: Path = REGISTRY_PATH,
    root: Path = TASK_CONTEXT_ROOT,
) -> dict[str, Any]:
    entry = get_task_entry(task_id, registry_path)
    task_path = resolve_context_path(entry["path"], root)
    task_context = load_json_context(task_path)

    inherits = task_context.get("inherits", [])
    if not isinstance(inherits, list):
        raise ValueError(f"{task_path} inherits must be a list")

    inherited_contexts = []
    for inherited in inherits:
        inherited_path = resolve_context_path(str(inherited), root)
        inherited_contexts.append(load_json_context(inherited_path))

    effective = merge_contexts(*inherited_contexts, task_context)
    effective["task_id"] = task_id
    effective["inherits"] = inherits
    effective["inherited_templates"] = inherits
    effective["supported_question_types"] = normalize_question_types(
        effective.get("supported_question_types", [])
    )
    return effective


def summarize_context(context: dict[str, Any]) -> str:
    layout = context.get("layout_memory", {})
    visual_rules = context.get("visual_parsing_rules", [])
    answer_rules = context.get("answer_rules", [])
    lines = [
        f"selected task: {context.get('task_id', '')}",
        f"task family: {context.get('task_family', '')}",
        f"task type: {context.get('task_type', '')}",
        "inherited templates:",
        *[f"- {item}" for item in context.get("inherited_templates", [])],
        "effective supported question types:",
        ", ".join(context.get("supported_question_types", [])),
        "layout memory summary:",
        str(layout.get("summary", "No layout memory summary.")),
        "vision rules:",
        *[f"- {rule}" for rule in visual_rules],
        "answer rules:",
        *[f"- {rule}" for rule in answer_rules],
    ]
    return "\n".join(lines)


def _reject_fixed_answer_coordinates(value: Any, path: Path) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in FORBIDDEN_COORDINATE_KEYS:
                raise ValueError(f"Reusable task memory may not store {key}: {path}")
            _reject_fixed_answer_coordinates(nested, path)
    elif isinstance(value, list):
        for item in value:
            _reject_fixed_answer_coordinates(item, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load and summarize a task context.")
    parser.add_argument("--task", required=True, help="Task id, for example tts01")
    args = parser.parse_args()
    context = load_effective_task_context(args.task)
    print(summarize_context(context))


if __name__ == "__main__":
    main()
