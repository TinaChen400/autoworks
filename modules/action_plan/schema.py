from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_action_plan(
    task_id: str,
    session_id: str,
    source_decision_id: str,
    source_session_id: str,
    status: str,
    actions: list[dict],
    warnings: list[str] | None = None,
) -> dict:
    return {
        "action_plan_id": f"action_plan_{uuid4().hex}",
        "task_id": task_id,
        "session_id": session_id,
        "source_decision_id": source_decision_id,
        "source_session_id": source_session_id,
        "status": status,
        "actions": actions,
        "warnings": warnings or [],
        "created_at": utc_now_iso(),
    }


def action(
    action_id: str,
    skill: str,
    target: dict,
    params: dict | None = None,
    requires_review: bool = False,
) -> dict:
    return {
        "action_id": action_id,
        "skill": skill,
        "target": target,
        "params": params or {},
        "requires_review": bool(requires_review),
    }

