from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


VALID_PREVIEW_STATUSES = {"blocked", "completed", "failed"}
MOUSE_PREVIEW_SKILLS = {"move_mouse", "left_click", "double_click"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_action_executor_preview(
    execution_gate: dict[str, Any],
    scheduler_run: dict[str, Any],
    resolved_action_plan: dict[str, Any],
    status: str,
    preview_records: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    block_reasons: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "action_executor_preview_id": f"action_executor_preview_{uuid4().hex}",
        "task_id": execution_gate.get("task_id") or scheduler_run.get("task_id") or "",
        "session_id": execution_gate.get("session_id") or scheduler_run.get("session_id") or "",
        "source_execution_gate_id": execution_gate.get("execution_gate_id", ""),
        "source_scheduler_run_id": scheduler_run.get("scheduler_run_id", ""),
        "source_resolved_action_plan_id": resolved_action_plan.get(
            "resolved_action_plan_id",
            execution_gate.get("source_resolved_action_plan_id", ""),
        ),
        "status": status,
        "preview_mode": True,
        "real_execution": False,
        "preview_records": preview_records,
        "failures": failures,
        "block_reasons": block_reasons,
        "created_at": utc_now_iso(),
    }


def executor_failure(
    code: str,
    message: str,
    action_id: str = "",
    skill: str = "",
) -> dict[str, Any]:
    failure: dict[str, Any] = {"code": code, "message": message}
    if action_id:
        failure["action_id"] = action_id
    if skill:
        failure["skill"] = skill
    return failure
