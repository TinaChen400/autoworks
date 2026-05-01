from __future__ import annotations

from typing import Any


def build_family_from_tasks(task_contexts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "placeholder",
        "task_count": len(task_contexts),
        "calls_model": False,
        "family": {},
    }


def extract_common_rules_placeholder(task_contexts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "placeholder",
        "task_count": len(task_contexts),
        "calls_model": False,
        "common_rules": [],
    }
