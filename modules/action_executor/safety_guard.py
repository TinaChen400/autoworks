from __future__ import annotations

from copy import deepcopy
from typing import Any


SUPPORTED_REAL_EXECUTION_SKILLS = {"click_option", "click_navigation", "type_text"}


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


def _numeric_candidate(candidate: Any) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    click_point = candidate.get("click_point_screen")
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
        normalized = deepcopy(candidate)
        normalized["click_point_screen"] = {
            "x": int(round(float(x))),
            "y": int(round(float(y))),
        }
        return normalized
    except (TypeError, ValueError):
        return None


def click_candidates(
    action: dict[str, Any],
    primary_x: int,
    primary_y: int,
) -> list[dict[str, Any]]:
    target = _target(action)
    primary: dict[str, Any] = {
        "source": str(target.get("resolver_source") or "click_point_screen"),
        "click_point_screen": {"x": primary_x, "y": primary_y},
        "is_primary": True,
    }
    if isinstance(target.get("click_point_raw"), dict):
        primary["click_point_raw"] = deepcopy(target["click_point_raw"])
    if isinstance(target.get("click_point_norm"), dict):
        primary["click_point_norm"] = deepcopy(target["click_point_norm"])
    candidates: list[dict[str, Any]] = [primary]
    seen = {(primary_x, primary_y)}
    for candidate in target.get("click_candidates", []) or []:
        normalized = _numeric_candidate(candidate)
        if normalized is None:
            continue
        point = normalized["click_point_screen"]
        key = (point["x"], point["y"])
        if key in seen:
            continue
        seen.add(key)
        candidates.append(normalized)
    return candidates


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
        "button_id": target.get("button_id", ""),
        "navigation_action": target.get("action", ""),
        "navigation_text": target.get("text", ""),
        "text": str((action.get("params") or {}).get("text") or ""),
        "click_point_screen": {"x": x, "y": y},
        "click_candidates": click_candidates(action, x, y),
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
                _error(
                    "unsupported_skill",
                    "Only click_option, click_navigation, and type_text can be executed.",
                    action_id,
                    skill,
                )
            )
            continue
        if skill == "type_text" and not str((action.get("params") or {}).get("text") or ""):
            errors.append(
                _error("missing_text", "type_text action requires params.text.", action_id, skill)
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
                    f"{skill} action requires numeric target.click_point_screen x/y.",
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
