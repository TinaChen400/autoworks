from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


VALID_SCHEDULER_STATUSES = {"blocked", "completed", "failed", "partial"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_scheduler_run(
    execution_gate: dict[str, Any],
    status: str,
    executed_actions: list[dict[str, Any]],
    skipped_actions: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "scheduler_run_id": f"scheduler_run_{uuid4().hex}",
        "task_id": execution_gate.get("task_id", ""),
        "session_id": execution_gate.get("session_id", ""),
        "source_execution_gate_id": execution_gate.get("execution_gate_id", ""),
        "source_resolved_action_plan_id": execution_gate.get(
            "source_resolved_action_plan_id",
            "",
        ),
        "status": status,
        "dry_run": True,
        "execution_allowed": bool(execution_gate.get("execution_allowed")),
        "executed_actions": executed_actions,
        "skipped_actions": skipped_actions,
        "failures": failures,
        "created_at": utc_now_iso(),
    }


def scheduler_failure(
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

