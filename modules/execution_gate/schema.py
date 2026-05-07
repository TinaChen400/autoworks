from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


RESOLVER_CONFIDENCE_THRESHOLD = 0.5
VALID_GATE_STATUSES = {"allowed", "blocked"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def block_reason(code: str, message: str, action_id: str = "") -> dict[str, Any]:
    reason: dict[str, Any] = {"code": code, "message": message}
    if action_id:
        reason["action_id"] = action_id
    return reason


def new_execution_gate(
    resolved_action_plan: dict[str, Any],
    execution_allowed: bool,
    block_reasons: list[dict[str, Any]],
    executable_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "execution_gate_id": f"execution_gate_{uuid4().hex}",
        "task_id": resolved_action_plan.get("task_id", ""),
        "session_id": resolved_action_plan.get("session_id", ""),
        "source_resolved_action_plan_id": resolved_action_plan.get("resolved_action_plan_id", ""),
        "execution_allowed": bool(execution_allowed),
        "status": "allowed" if execution_allowed else "blocked",
        "block_reasons": block_reasons,
        "executable_actions": executable_actions,
        "created_at": utc_now_iso(),
    }

