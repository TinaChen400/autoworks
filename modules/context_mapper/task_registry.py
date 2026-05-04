from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modules.window_capture.capture import PROJECT_ROOT

TASK_CONTEXT_ROOT = PROJECT_ROOT / "task_contexts"
REGISTRY_PATH = TASK_CONTEXT_ROOT / "registry.json"


def load_registry(registry_path: Path = REGISTRY_PATH) -> dict[str, Any]:
    if not registry_path.exists():
        raise FileNotFoundError(f"Task registry not found: {registry_path}")
    data = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    if "tasks" not in data or not isinstance(data["tasks"], dict):
        raise ValueError("Task registry must contain a tasks object")
    return data


def list_task_ids(registry_path: Path = REGISTRY_PATH) -> list[str]:
    return sorted(load_registry(registry_path)["tasks"].keys())


def get_task_entry(task_id: str, registry_path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = load_registry(registry_path)
    tasks = registry["tasks"]
    if task_id not in tasks:
        raise ValueError(f"Unknown task_id: {task_id}")
    entry = tasks[task_id]
    if "path" not in entry:
        raise ValueError(f"Registry entry for {task_id} must include path")
    return entry


def resolve_context_path(relative_path: str, root: Path = TASK_CONTEXT_ROOT) -> Path:
    path = root / relative_path
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_root not in resolved_path.parents and resolved_path != resolved_root:
        raise ValueError(f"Context path escapes task_contexts: {relative_path}")
    return resolved_path
