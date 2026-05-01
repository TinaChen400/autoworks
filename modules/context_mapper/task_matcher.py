from __future__ import annotations

from typing import Any


def match_task_by_summary(
    summary: str,
    known_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": "placeholder",
        "summary": summary,
        "known_task_count": len(known_tasks or []),
        "calls_model": False,
        "matches": [],
    }


def suggest_existing_task_or_family(summary: str) -> dict[str, Any]:
    return {
        "status": "placeholder",
        "summary": summary,
        "calls_model": False,
        "suggested_task_id": None,
        "suggested_family": None,
    }
