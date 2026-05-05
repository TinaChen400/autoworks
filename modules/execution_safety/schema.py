from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


VALID_EXECUTION_MODES = {"preview", "kvm_real"}
VALID_GUARD_STATUSES = {"allowed", "blocked"}
MVP_BLOCKED_REAL_SKILLS = {"submit", "click_next", "type_text", "press_key", "double_click"}

DEFAULT_EXECUTION_SAFETY_CONFIG: dict[str, Any] = {
    "execution_mode": "preview",
    "allow_real_execution": False,
    "require_execution_gate_allowed": True,
    "require_scheduler_completed": True,
    "require_action_executor_preview_completed": True,
    "require_kvm_calibrated": True,
    "require_manual_start": True,
    "max_real_actions_per_run": 1,
    "allowed_real_skills": [
        "move_mouse",
        "left_click",
    ],
    "blocked_real_skills": [
        "submit",
        "click_next",
        "press_key",
        "type_text",
        "double_click",
    ],
    "emergency_stop_enabled": True,
    "safe_test_mode_only": True,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def block_reason(code: str, message: str, **details: Any) -> dict[str, Any]:
    reason = {"code": code, "message": message}
    reason.update({key: value for key, value in details.items() if value not in ("", None)})
    return reason


def new_execution_safety_guard(
    config: dict[str, Any],
    execution_gate: dict[str, Any],
    scheduler_run: dict[str, Any],
    action_executor_preview: dict[str, Any],
    kvm_calibration: dict[str, Any],
    kvm_calibration_report: dict[str, Any],
    real_execution_allowed: bool,
    block_reasons: list[dict[str, Any]],
    real_candidate_actions: list[dict[str, Any]],
    safety_checks: dict[str, bool],
) -> dict[str, Any]:
    _ = kvm_calibration_report
    return {
        "execution_safety_guard_id": f"execution_safety_guard_{uuid4().hex}",
        "task_id": (
            execution_gate.get("task_id")
            or scheduler_run.get("task_id")
            or action_executor_preview.get("task_id")
            or kvm_calibration.get("task_id")
            or ""
        ),
        "session_id": (
            execution_gate.get("session_id")
            or scheduler_run.get("session_id")
            or action_executor_preview.get("session_id")
            or kvm_calibration.get("session_id")
            or ""
        ),
        "source_execution_gate_id": execution_gate.get("execution_gate_id", ""),
        "source_scheduler_run_id": scheduler_run.get("scheduler_run_id", ""),
        "source_action_executor_preview_id": action_executor_preview.get(
            "action_executor_preview_id",
            "",
        ),
        "source_kvm_calibration_id": kvm_calibration.get("kvm_calibration_id", ""),
        "real_execution_allowed": real_execution_allowed,
        "status": "allowed" if real_execution_allowed else "blocked",
        "execution_mode": config.get("execution_mode", "preview"),
        "block_reasons": block_reasons,
        "real_candidate_actions": real_candidate_actions,
        "safety_checks": safety_checks,
        "created_at": utc_now_iso(),
    }

