from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_LOCAL_REAL_CLICK_CONFIG: dict[str, Any] = {
    "enabled": False,
    "target_environment": "local_html_only",
    "require_execution_safety_allowed": True,
    "require_kvm_calibrated": True,
    "require_single_real_action_group": True,
    "allowed_logical_skills": ["click_option"],
    "blocked_logical_skills": ["submit", "click_next", "type_text", "press_key", "double_click"],
    "countdown_seconds": 5,
    "abort_file": "runtime_state/STOP_REAL_CLICK",
    "write_preflight_preview": True,
    "max_clicks": 1,
}


def merged_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_LOCAL_REAL_CLICK_CONFIG)
    merged.update(config)
    return merged


def issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update({key: value for key, value in details.items() if value not in ("", None)})
    return payload


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def numeric_click_point(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    x = value.get("x")
    y = value.get("y")
    if not is_number(x) or not is_number(y):
        return None
    return {"x": int(round(x)), "y": int(round(y))}


def first_real_action_group(execution_safety_guard: dict[str, Any]) -> dict[str, Any] | None:
    groups = execution_safety_guard.get("real_action_groups")
    if not isinstance(groups, list) or len(groups) != 1 or not isinstance(groups[0], dict):
        return None
    return groups[0]


def validate_preflight(
    config: dict[str, Any],
    execution_safety_guard: dict[str, Any],
    kvm_calibration: dict[str, Any],
    action_executor_preview: dict[str, Any],
    confirm_local_html_test: bool,
    runtime_dir: str | Path,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    config = merged_config(config)
    issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    if confirm_local_html_test is not True:
        issues.append(
            issue(
                "local_html_confirmation_required",
                "--confirm-local-html-test is required.",
            )
        )
    if config.get("enabled") is not True:
        issues.append(issue("local_real_click_disabled", "local_real_click_test.enabled is false."))
    if config.get("target_environment") != "local_html_only":
        issues.append(
            issue(
                "target_environment_not_local_html_only",
                'target_environment must be "local_html_only".',
                target_environment=config.get("target_environment"),
            )
        )
    if action_executor_preview.get("status") != "completed":
        issues.append(
            issue(
                "action_executor_preview_not_completed",
                'latest_action_executor_preview.status must be "completed".',
            )
        )

    if config.get("require_execution_safety_allowed") is True:
        if execution_safety_guard.get("real_execution_allowed") is not True:
            issues.append(
                issue(
                    "execution_safety_not_allowed",
                    "latest_execution_safety_guard.real_execution_allowed is not true.",
                )
            )
        if execution_safety_guard.get("status") != "allowed":
            issues.append(
                issue(
                    "execution_safety_status_not_allowed",
                    'latest_execution_safety_guard.status must be "allowed".',
                )
            )
        if execution_safety_guard.get("real_action_group_count") != 1:
            issues.append(
                issue(
                    "real_action_group_count_not_one",
                    "latest_execution_safety_guard.real_action_group_count must equal 1.",
                    real_action_group_count=execution_safety_guard.get("real_action_group_count"),
                )
            )

    if (
        config.get("require_kvm_calibrated") is True
        and kvm_calibration.get("calibrated") is not True
    ):
        issues.append(issue("kvm_not_calibrated", "latest_kvm_calibration.calibrated is not true."))

    max_clicks = config.get("max_clicks")
    if not isinstance(max_clicks, int) or isinstance(max_clicks, bool) or max_clicks != 1:
        issues.append(issue("max_clicks_not_one", "max_clicks must be exactly 1 for this MVP."))

    countdown_seconds = config.get("countdown_seconds")
    if (
        not isinstance(countdown_seconds, int)
        or isinstance(countdown_seconds, bool)
        or countdown_seconds < 0
    ):
        issues.append(
            issue(
                "invalid_countdown_seconds",
                "countdown_seconds must be a non-negative integer.",
            )
        )
        countdown_seconds = 0

    group = first_real_action_group(execution_safety_guard)
    if config.get("require_single_real_action_group") is True and group is None:
        issues.append(
            issue(
                "single_real_action_group_required",
                "Exactly one real action group is required.",
            )
        )
        return None, issues, warnings
    if group is None:
        return None, issues, warnings

    logical_skill = str(group.get("logical_skill") or "")
    allowed_skills = {
        item for item in config.get("allowed_logical_skills", []) if isinstance(item, str)
    }
    blocked_skills = {
        item for item in config.get("blocked_logical_skills", []) if isinstance(item, str)
    }

    if logical_skill not in allowed_skills:
        issues.append(
            issue(
                "logical_skill_not_allowed",
                "Real action group logical_skill is not allowed.",
                logical_skill=logical_skill,
            )
        )
    if logical_skill in blocked_skills:
        issues.append(
            issue(
                "logical_skill_blocked",
                "Real action group logical_skill is blocked.",
                logical_skill=logical_skill,
            )
        )

    atomic_steps = group.get("atomic_steps")
    if not isinstance(atomic_steps, list):
        atomic_steps = []
    atomic_step_set = {step for step in atomic_steps if isinstance(step, str)}
    blocked_atomic_steps = sorted(atomic_step_set & blocked_skills)
    if blocked_atomic_steps:
        issues.append(
            issue(
                "blocked_atomic_step",
                "Real action group contains a blocked atomic step.",
                blocked_atomic_steps=blocked_atomic_steps,
            )
        )
    if not {"move_mouse", "left_click"} <= atomic_step_set:
        issues.append(
            issue(
                "required_atomic_steps_missing",
                "Real action group must contain move_mouse and left_click.",
            )
        )

    click_point = numeric_click_point(group.get("click_point_screen"))
    if click_point is None:
        issues.append(
            issue(
                "missing_or_invalid_click_point_screen",
                "Real action group click_point_screen must contain numeric x and y.",
            )
        )

    abort_path = Path(config.get("abort_file", DEFAULT_LOCAL_REAL_CLICK_CONFIG["abort_file"]))
    if not abort_path.is_absolute():
        abort_path = Path(runtime_dir).parent / abort_path
    if abort_path.exists():
        issues.append(
            issue(
                "abort_file_present",
                "Abort file exists before execution.",
                abort_file=str(abort_path),
            )
        )

    if issues or click_point is None:
        return None, issues, warnings

    return {
        "task_id": (
            execution_safety_guard.get("task_id") or action_executor_preview.get("task_id") or ""
        ),
        "session_id": (
            execution_safety_guard.get("session_id")
            or action_executor_preview.get("session_id")
            or ""
        ),
        "action_id": str(group.get("action_id") or ""),
        "logical_skill": logical_skill,
        "option_id": str(group.get("option_id") or ""),
        "option_text": str(group.get("option_text") or ""),
        "click_point_screen": click_point,
        "countdown_seconds": countdown_seconds,
        "abort_file": str(abort_path),
    }, issues, warnings
