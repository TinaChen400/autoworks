from __future__ import annotations

from typing import Any

from .schema import VALID_SCHEDULER_STATUSES


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


def validate_scheduler_run(scheduler_run: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    status = scheduler_run.get("status")
    execution_allowed = scheduler_run.get("execution_allowed")
    dry_run = scheduler_run.get("dry_run")
    executed_actions = scheduler_run.get("executed_actions")
    skipped_actions = scheduler_run.get("skipped_actions")
    failures = scheduler_run.get("failures")

    if status not in VALID_SCHEDULER_STATUSES:
        issues.append({"type": "invalid_status", "status": status})
    if dry_run is not True:
        issues.append({"type": "dry_run_required"})
    if not isinstance(execution_allowed, bool):
        issues.append({"type": "invalid_execution_allowed"})
    if not isinstance(executed_actions, list):
        issues.append({"type": "invalid_executed_actions"})
        executed_actions = []
    if not isinstance(skipped_actions, list):
        issues.append({"type": "invalid_skipped_actions"})
        skipped_actions = []
    if not isinstance(failures, list):
        issues.append({"type": "invalid_failures"})
        failures = []

    if execution_allowed is False and executed_actions:
        issues.append({"type": "blocked_run_has_executed_actions"})
    if status == "blocked" and execution_allowed is True:
        issues.append({"type": "blocked_status_allowed"})
    if status == "completed" and failures:
        issues.append({"type": "completed_run_has_failures"})
    if status == "failed" and not failures:
        issues.append({"type": "failed_run_missing_failures"})
    if _contains_forbidden_field(scheduler_run):
        issues.append({"type": "real_os_interaction_field_present"})

    return {
        "validation_passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "status": status,
        "dry_run": dry_run is True,
        "execution_allowed": (
            bool(execution_allowed) if isinstance(execution_allowed, bool) else False
        ),
        "executed_action_count": len(executed_actions),
        "skipped_action_count": len(skipped_actions),
        "failure_count": len(failures),
    }

