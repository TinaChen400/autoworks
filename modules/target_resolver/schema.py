from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


COORDINATE_KEYS = {
    "bbox_norm",
    "bbox_raw",
    "bbox_screen",
    "click_point_norm",
    "click_point_raw",
    "click_point_screen",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_resolved_plan(source_plan: dict[str, Any], actions: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    plan = dict(source_plan)
    plan["resolved_action_plan_id"] = f"resolved_action_plan_{uuid4().hex}"
    plan["source_action_plan_id"] = source_plan.get("action_plan_id", "")
    plan["actions"] = actions
    plan["warnings"] = list(source_plan.get("warnings", [])) + warnings
    plan["created_at"] = now_iso()
    return plan


def unresolved_issue(action: dict[str, Any], issue_type: str, message: str) -> dict[str, Any]:
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    return {
        "type": issue_type,
        "action_id": action.get("action_id", ""),
        "skill": action.get("skill", ""),
        "question_id": target.get("question_id", ""),
        "option_id": target.get("option_id", ""),
        "message": message,
    }

