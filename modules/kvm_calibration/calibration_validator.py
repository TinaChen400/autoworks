from __future__ import annotations

from typing import Any

from .schema import calibration_issue


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


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _valid_frame(frame: Any) -> bool:
    if not isinstance(frame, dict):
        return False
    return all(_is_number(frame.get(key)) for key in ("x", "y", "width", "height")) and (
        frame["width"] > 0 and frame["height"] > 0
    )


def _valid_size(size: Any) -> bool:
    if not isinstance(size, dict):
        return False
    return all(_is_number(size.get(key)) for key in ("width", "height")) and (
        size["width"] > 0 and size["height"] > 0
    )


def validate_calibration(calibration: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    warnings = calibration.get("warnings")
    validated_points = calibration.get("validated_points")

    if not isinstance(warnings, list):
        issues.append(calibration_issue("invalid_warnings", "warnings must be a list."))
        warnings = []
    if not isinstance(validated_points, list):
        issues.append(
            calibration_issue("invalid_validated_points", "validated_points must be a list.")
        )
        validated_points = []

    if not _valid_frame(calibration.get("anchor_frame")):
        issues.append(
            calibration_issue("invalid_anchor_frame", "anchor_frame is missing or invalid.")
        )
    if not _valid_size(calibration.get("controlled_screen")):
        issues.append(
            calibration_issue(
                "invalid_controlled_screen",
                "controlled_screen is missing or invalid.",
            )
        )

    scale = calibration.get("scale")
    offset = calibration.get("offset")
    if (
        not isinstance(scale, dict)
        or not _is_number(scale.get("x"))
        or not _is_number(scale.get("y"))
    ):
        issues.append(calibration_issue("invalid_scale", "scale must include numeric x and y."))
    elif scale["x"] <= 0 or scale["y"] <= 0:
        issues.append(calibration_issue("invalid_scale", "scale x and y must be positive."))

    if (
        not isinstance(offset, dict)
        or not _is_number(offset.get("x"))
        or not _is_number(offset.get("y"))
    ):
        issues.append(calibration_issue("invalid_offset", "offset must include numeric x and y."))

    for point in validated_points:
        if not isinstance(point, dict):
            issues.append(
                calibration_issue(
                    "invalid_validated_point",
                    "Validated point must be an object.",
                )
            )
            continue
        if point.get("inside_viewport") is not True:
            issues.append(
                calibration_issue(
                    "point_outside_viewport",
                    "A preview click point is outside the calibrated KVM viewport.",
                    action_id=point.get("action_id", ""),
                    skill=point.get("skill", ""),
                    screen_point=point.get("screen_point", {}),
                )
            )

    if _contains_forbidden_field(calibration):
        issues.append(
            calibration_issue(
                "real_os_interaction_field_present",
                "Calibration output must not contain real OS interaction fields.",
            )
        )

    calibrated = calibration.get("calibrated") is True
    if calibrated and issues:
        issues.append(
            calibration_issue(
                "calibrated_true_with_validation_issues",
                "calibrated cannot be true while validation issues exist.",
            )
        )

    return {
        "validation_passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "calibrated": calibrated and not issues,
        "validated_point_count": len(validated_points),
    }
