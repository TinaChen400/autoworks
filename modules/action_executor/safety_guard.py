from __future__ import annotations

from typing import Any


SUPPORTED_REAL_EXECUTION_SKILLS = {"click_option"}


def _error(code: str, message: str, action_id: str = "", skill: str = "") -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message}
    if action_id:
        item["action_id"] = action_id
    if skill:
        item["skill"] = skill
    return item


def _target(action: dict[str, Any]) -> dict[str, Any]:
    target = action.get("target")
    return target if isinstance(target, dict) else {}


def numeric_click_point_screen(action: dict[str, Any]) -> tuple[int, int] | None:
    click_point = _target(action).get("click_point_screen")
    if not isinstance(click_point, dict):
        return None
    try:
        x = click_point["x"]
        y = click_point["y"]
    except KeyError:
        return None
    if isinstance(x, bool) or isinstance(y, bool):
        return None
    try:
        return int(round(float(x))), int(round(float(y)))
    except (TypeError, ValueError):
        return None


def _is_unresolved(action: dict[str, Any]) -> bool:
    target = _target(action)
    unresolved_values = {"unresolved", "human_review_required", "needs_review"}
    return (
        action.get("unresolved") is True
        or str(action.get("status", "")).casefold() in unresolved_values
        or str(action.get("resolution_status", "")).casefold() in unresolved_values
        or str(target.get("resolution_status", "")).casefold() in unresolved_values
    )


def action_record(action: dict[str, Any], x: int, y: int, dry_run: bool) -> dict[str, Any]:
    target = _target(action)
    return {
        "action_id": str(action.get("action_id") or ""),
        "skill": str(action.get("skill") or ""),
        "question_id": target.get("question_id", ""),
        "option_id": target.get("option_id", ""),
        "option_text": target.get("option_text", ""),
        "click_point_screen": {"x": x, "y": y},
        "real_execution": not dry_run,
        "dry_run": dry_run,
        "status": "would_click" if dry_run else "pending",
    }


def validate_gate_for_real_execution(gate: dict[str, Any] | None, dry_run: bool) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    action_records: list[dict[str, Any]] = []

    if not isinstance(gate, dict) or not gate:
        errors.append(_error("gate_missing", "latest_execution_gate.json is missing or invalid."))
        return {
            "validation_passed": False,
            "action_records": [],
            "errors": errors,
            "warnings": warnings,
            "action_count": 0,
        }

    if gate.get("status") != "allowed" or gate.get("execution_allowed") is not True:
        errors.append(_error("gate_not_allowed", "Execution gate status is not allowed."))

    actions = gate.get("executable_actions")
    if not isinstance(actions, list):
        errors.append(
            _error(
                "invalid_executable_actions",
                "execution_gate.executable_actions must be a list.",
            )
        )
        actions = []

    for action in actions:
        if not isinstance(action, dict):
            errors.append(_error("invalid_action", "Executable action must be an object."))
            continue

        action_id = str(action.get("action_id") or "")
        skill = str(action.get("skill") or "")
        if skill not in SUPPORTED_REAL_EXECUTION_SKILLS:
            errors.append(
                _error("unsupported_skill", "Only click_option can be executed.", action_id, skill)
            )
            continue
        if action.get("requires_review") is not False:
            errors.append(
                _error(
                    "requires_review",
                    "Executable action must have requires_review set to false.",
                    action_id,
                    skill,
                )
            )
            continue
        if _is_unresolved(action):
            errors.append(
                _error("unresolved_action", "Unresolved actions cannot execute.", action_id, skill)
            )
            continue

        point = numeric_click_point_screen(action)
        if point is None:
            errors.append(
                _error(
                    "missing_click_point_screen",
                    "click_option action requires numeric target.click_point_screen x/y.",
                    action_id,
                    skill,
                )
            )
            continue

        x, y = point
        action_records.append(action_record(action, x, y, dry_run))

    return {
        "validation_passed": not errors,
        "action_records": action_records if not errors else [],
        "errors": errors,
        "warnings": warnings,
        "action_count": len(actions),
    }
