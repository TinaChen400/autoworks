from __future__ import annotations

from typing import Any

from .schema import VALID_EXECUTION_MODES, VALID_GUARD_STATUSES


FORBIDDEN_OS_INTERACTION_FIELDS = {
    "clicked",
    "typed",
    "mouse_moved",
    "keyboard_used",
    "winapi",
    "window_handle",
    "hwnd",
    "screen_click_executed",
    "os_interaction_performed",
}


def _contains_forbidden_field(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in FORBIDDEN_OS_INTERACTION_FIELDS or _contains_forbidden_field(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_field(item) for item in value)
    return False


def validate_execution_safety_guard(guard: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    status = guard.get("status")
    real_execution_allowed = guard.get("real_execution_allowed")
    block_reasons = guard.get("block_reasons")
    real_candidate_actions = guard.get("real_candidate_actions")
    real_action_groups = guard.get("real_action_groups")
    safety_checks = guard.get("safety_checks")

    if status not in VALID_GUARD_STATUSES:
        issues.append({"type": "invalid_status", "status": status})
    if guard.get("execution_mode") not in VALID_EXECUTION_MODES:
        issues.append(
            {
                "type": "invalid_execution_mode",
                "execution_mode": guard.get("execution_mode"),
            }
        )
    if not isinstance(real_execution_allowed, bool):
        issues.append({"type": "invalid_real_execution_allowed"})
    if not isinstance(block_reasons, list):
        issues.append({"type": "invalid_block_reasons"})
        block_reasons = []
    if not isinstance(real_candidate_actions, list):
        issues.append({"type": "invalid_real_candidate_actions"})
        real_candidate_actions = []
    if not isinstance(real_action_groups, list):
        issues.append({"type": "invalid_real_action_groups"})
        real_action_groups = []
    if guard.get("real_action_group_count") != len(real_action_groups):
        issues.append(
            {
                "type": "real_action_group_count_mismatch",
                "real_action_group_count": guard.get("real_action_group_count"),
                "actual_real_action_group_count": len(real_action_groups),
            }
        )
    if not isinstance(safety_checks, dict):
        issues.append({"type": "invalid_safety_checks"})
        safety_checks = {}

    if real_execution_allowed is True and status != "allowed":
        issues.append({"type": "allowed_status_mismatch"})
    if real_execution_allowed is False and status != "blocked":
        issues.append({"type": "blocked_status_mismatch"})
    if real_execution_allowed is True and block_reasons:
        issues.append({"type": "allowed_guard_has_block_reasons"})
    if real_execution_allowed is False and not block_reasons:
        issues.append({"type": "blocked_guard_missing_block_reason"})
    if _contains_forbidden_field(guard):
        issues.append({"type": "real_os_interaction_field_present"})

    return {
        "validation_passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "status": status,
        "real_execution_allowed": real_execution_allowed is True and not issues,
        "block_reason_count": len(block_reasons),
        "real_candidate_action_count": len(real_candidate_actions),
        "real_action_group_count": len(real_action_groups),
        "safety_checks": safety_checks,
    }
