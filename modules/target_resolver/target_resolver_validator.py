from __future__ import annotations

from typing import Any

from .schema import COORDINATE_KEYS


def _coordinate_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else key
            if key in COORDINATE_KEYS:
                paths.append(child_path)
            paths.extend(_coordinate_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_coordinate_paths(child, f"{prefix}[{index}]"))
    return paths


def validate_resolved_action_plan(plan: dict[str, Any], resolver_issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    issues = list(resolver_issues or [])
    actions = plan.get("actions", [])
    if not isinstance(actions, list):
        issues.append({"type": "invalid_actions", "message": "actions must be a list"})
        actions = []

    for action in actions:
        if not isinstance(action, dict):
            issues.append({"type": "invalid_action", "message": "action must be an object"})
            continue
        skill = action.get("skill")
        target = action.get("target") if isinstance(action.get("target"), dict) else {}
        paths = _coordinate_paths(action)
        if skill == "request_human_review" and paths:
            issues.append(
                {
                    "type": "human_review_coordinates_present",
                    "action_id": action.get("action_id", ""),
                    "paths": paths,
                }
            )
        if skill == "click_option":
            required = [
                "question_id",
                "option_id",
                "option_text",
                "control_element_id",
                "control_type",
                "click_point_norm",
                "click_point_raw",
                "click_point_screen",
                "resolver_confidence",
            ]
            missing = [key for key in required if key not in target]
            if missing:
                issues.append(
                    {
                        "type": "unresolved_click_option",
                        "action_id": action.get("action_id", ""),
                        "question_id": target.get("question_id", ""),
                        "option_id": target.get("option_id", ""),
                        "missing": missing,
                    }
                )

    return {
        "validation_passed": not issues,
        "issues": issues,
        "warnings": list(plan.get("warnings", [])),
        "resolved_actions": sum(
            1
            for action in actions
            if isinstance(action, dict)
            and action.get("skill") == "click_option"
            and not _coordinate_paths(action.get("target", {})) == []
            and "click_point_screen" in (action.get("target") or {})
        ),
    }

