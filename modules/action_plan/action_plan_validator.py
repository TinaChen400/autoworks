from __future__ import annotations


COORDINATE_KEYS = {
    "x",
    "y",
    "left",
    "top",
    "right",
    "bottom",
    "width",
    "height",
    "bbox",
    "bbox_norm",
    "click_point",
    "click_point_norm",
    "coordinates",
    "coordinate",
}

VALID_SKILLS = {
    "request_human_review",
    "click_option",
    "click_navigation",
    "type_text",
    "select_dropdown",
}

VALID_STATUSES = {"human_review_required", "ready", "invalid", "no_action"}


def _find_coordinate_keys(value: object, path: str = "$") -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in COORDINATE_KEYS:
                matches.append(child_path)
            matches.extend(_find_coordinate_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(_find_coordinate_keys(child, f"{path}[{index}]"))
    return matches


def validate_action_plan(plan: dict) -> dict:
    issues = []
    warnings = []

    status = plan.get("status")
    if status not in VALID_STATUSES:
        issues.append({"type": "invalid_status", "status": status})

    actions = plan.get("actions", [])
    if not isinstance(actions, list):
        issues.append({"type": "missing_actions"})
    elif not actions and status != "no_action":
        issues.append({"type": "missing_actions"})
    else:
        for item in actions:
            skill = item.get("skill")
            if skill not in VALID_SKILLS:
                issues.append({"type": "invalid_skill", "skill": skill})
            target = item.get("target", {})
            unexpected = sorted(
                set(target)
                - {"question_id", "option_id", "option_text", "button_id", "action", "text"}
            )
            if unexpected:
                issues.append(
                    {
                        "type": "unexpected_target_fields",
                        "action_id": item.get("action_id", ""),
                        "fields": unexpected,
                    }
                )

    coordinate_paths = _find_coordinate_keys(plan)
    if coordinate_paths:
        issues.append({"type": "coordinate_fields_present", "paths": coordinate_paths})

    return {
        "validation_passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "action_count": len(actions) if isinstance(actions, list) else 0,
    }

