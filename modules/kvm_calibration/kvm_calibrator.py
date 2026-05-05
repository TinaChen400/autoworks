from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import calibration_store
from .calibration_validator import validate_calibration
from .schema import calibration_issue, new_kvm_calibration, utc_now_iso


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _frame(source: Any, keys: tuple[str, ...]) -> dict[str, float] | None:
    if not isinstance(source, dict):
        return None
    values: dict[str, float] = {}
    for key in keys:
        number = _number(source.get(key))
        if number is None:
            return None
        values[key] = number
    if values.get("width", 1) <= 0 or values.get("height", 1) <= 0:
        return None
    return values


def _round_point(point: dict[str, float]) -> dict[str, int]:
    return {"x": int(round(point["x"])), "y": int(round(point["y"]))}


def _build_model(runtime_context: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    anchor_frame = _frame(runtime_context.get("anchor_frame"), ("x", "y", "width", "height"))
    image_size = _frame(runtime_context.get("image_size"), ("width", "height"))
    raw_screenshot = _frame(runtime_context.get("raw_screenshot"), ("x", "y", "width", "height"))
    model_input_region = _frame(
        runtime_context.get("model_input_region"),
        ("x", "y", "width", "height"),
    )

    if anchor_frame is None:
        issues.append(
            calibration_issue(
                "missing_anchor_frame",
                "runtime_context.anchor_frame is required for KVM calibration.",
            )
        )
    if image_size is None and raw_screenshot is None:
        issues.append(
            calibration_issue(
                "missing_controlled_screen_size",
                "runtime_context.image_size or raw_screenshot is required for KVM calibration.",
            )
        )
    if raw_screenshot is None:
        issues.append(
            calibration_issue(
                "missing_raw_screenshot",
                "runtime_context.raw_screenshot is required for calibration traceability.",
            )
        )
    if model_input_region is None:
        issues.append(
            calibration_issue(
                "missing_model_input_region",
                "runtime_context.model_input_region is required for calibration traceability.",
            )
        )
    if not isinstance(runtime_context.get("coordinate_policy"), dict):
        issues.append(
            calibration_issue(
                "missing_coordinate_policy",
                "runtime_context.coordinate_policy is required for calibration traceability.",
            )
        )

    controlled_screen = image_size or (
        {"width": raw_screenshot["width"], "height": raw_screenshot["height"]}
        if raw_screenshot is not None
        else None
    )
    if anchor_frame is None or controlled_screen is None:
        return {}, issues

    scale_x = anchor_frame["width"] / controlled_screen["width"]
    scale_y = anchor_frame["height"] / controlled_screen["height"]
    if scale_x <= 0 or scale_y <= 0:
        issues.append(
            calibration_issue("invalid_scale", "Calculated KVM scale must be positive.")
        )

    return {
        "anchor_frame": _round_point(anchor_frame)
        | {
            "width": int(round(anchor_frame["width"])),
            "height": int(round(anchor_frame["height"])),
        },
        "controlled_screen": {
            "width": int(round(controlled_screen["width"])),
            "height": int(round(controlled_screen["height"])),
        },
        "raw_screenshot": _round_point(raw_screenshot) | {
            "width": int(round(raw_screenshot["width"])),
            "height": int(round(raw_screenshot["height"])),
        }
        if raw_screenshot is not None
        else {},
        "model_input_region": _round_point(model_input_region) | {
            "width": int(round(model_input_region["width"])),
            "height": int(round(model_input_region["height"])),
        }
        if model_input_region is not None
        else {},
        "scale": {"x": scale_x, "y": scale_y},
        "offset": {"x": int(round(anchor_frame["x"])), "y": int(round(anchor_frame["y"]))},
    }, issues


def screen_to_kvm_viewport(point_screen: dict[str, Any], model: dict[str, Any]) -> dict[str, float]:
    scale = model["scale"]
    offset = model["offset"]
    return {
        "x": (_number(point_screen.get("x")) - offset["x"]) / scale["x"],
        "y": (_number(point_screen.get("y")) - offset["y"]) / scale["y"],
    }


def kvm_viewport_to_screen(point_viewport: dict[str, Any], model: dict[str, Any]) -> dict[str, int]:
    scale = model["scale"]
    offset = model["offset"]
    viewport_x = _number(point_viewport.get("x")) or 0.0
    viewport_y = _number(point_viewport.get("y")) or 0.0
    return {
        "x": int(round(offset["x"] + viewport_x * scale["x"])),
        "y": int(round(offset["y"] + viewport_y * scale["y"])),
    }


def _inside_viewport(point_viewport: dict[str, float], model: dict[str, Any]) -> bool:
    controlled = model["controlled_screen"]
    return (
        0 <= point_viewport["x"] <= controlled["width"]
        and 0 <= point_viewport["y"] <= controlled["height"]
    )


def _preview_records(action_executor_preview: dict[str, Any]) -> list[dict[str, Any]]:
    records = action_executor_preview.get("preview_records")
    return records if isinstance(records, list) else []


def _validated_preview_points(
    action_executor_preview: dict[str, Any],
    model: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    points: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for record in _preview_records(action_executor_preview):
        if not isinstance(record, dict):
            issues.append(
                calibration_issue(
                    "invalid_preview_record",
                    "Action executor preview records must be objects.",
                )
            )
            continue
        click_point = record.get("click_point_screen")
        if not isinstance(click_point, dict):
            issues.append(
                calibration_issue(
                    "missing_click_point_screen",
                    "Preview record is missing click_point_screen.",
                    action_id=record.get("action_id", ""),
                    skill=record.get("skill", ""),
                )
            )
            continue
        screen_x = _number(click_point.get("x"))
        screen_y = _number(click_point.get("y"))
        if screen_x is None or screen_y is None:
            issues.append(
                calibration_issue(
                    "invalid_click_point_screen",
                    "click_point_screen must contain numeric x and y.",
                    action_id=record.get("action_id", ""),
                    skill=record.get("skill", ""),
                )
            )
            continue

        screen_point = {"x": int(round(screen_x)), "y": int(round(screen_y))}
        viewport_point = screen_to_kvm_viewport(screen_point, model)
        roundtrip_point = kvm_viewport_to_screen(viewport_point, model)
        inside_viewport = _inside_viewport(viewport_point, model)
        if not inside_viewport:
            issues.append(
                calibration_issue(
                    "point_outside_viewport",
                    "Preview click point is outside the calibrated KVM viewport.",
                    action_id=record.get("action_id", ""),
                    skill=record.get("skill", ""),
                    screen_point=screen_point,
                )
            )

        points.append(
            {
                "source": "action_executor_preview",
                "record_type": record.get("record_type", ""),
                "action_id": record.get("action_id", ""),
                "skill": record.get("skill", ""),
                "screen_point": screen_point,
                "kvm_viewport_point": _round_point(viewport_point),
                "roundtrip_screen_point": roundtrip_point,
                "inside_viewport": inside_viewport,
            }
        )

    return points, issues


def build_kvm_calibration(
    runtime_context: dict[str, Any],
    resolved_action_plan: dict[str, Any],
    action_executor_preview: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    model, issues = _build_model(runtime_context)
    validated_points: list[dict[str, Any]] = []
    warnings: list[str] = []

    if model:
        validated_points, point_issues = _validated_preview_points(action_executor_preview, model)
        issues.extend(point_issues)

    if not _preview_records(action_executor_preview):
        warnings.append("No action executor preview click points were available to validate.")

    calibrated = bool(model) and not issues
    calibration = new_kvm_calibration(
        runtime_context,
        resolved_action_plan,
        action_executor_preview,
        calibrated,
        model,
        validated_points,
        warnings,
    )
    report = validate_calibration(calibration)
    report.update(
        {
            "issues": issues + report["issues"],
            "validation_passed": calibrated and not report["issues"],
            "source_resolved_action_plan_id": resolved_action_plan.get(
                "resolved_action_plan_id",
                "",
            ),
            "source_action_executor_preview_id": action_executor_preview.get(
                "action_executor_preview_id",
                "",
            ),
            "kvm_calibration_path": str(calibration_store.KVM_CALIBRATION_PATH),
            "created_at": utc_now_iso(),
        }
    )
    return calibration, report


def run_calibration(
    source: str = "auto",
    runtime_dir: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _ = source
    if runtime_dir is None:
        (
            runtime_context,
            resolved_action_plan,
            action_executor_preview,
        ) = calibration_store.load_inputs()
        calibration_path = calibration_store.KVM_CALIBRATION_PATH
        report_path = calibration_store.KVM_CALIBRATION_REPORT_PATH
    else:
        runtime = Path(runtime_dir)
        runtime_context = calibration_store.load_json(runtime / "latest_runtime_context.json")
        resolved_action_plan = calibration_store.load_json(
            runtime / "latest_resolved_action_plan.json"
        )
        action_executor_preview = calibration_store.load_json(
            runtime / "latest_action_executor_preview.json",
        )
        calibration_path, report_path = calibration_store.paths_for_runtime(runtime)

    calibration, report = build_kvm_calibration(
        runtime_context,
        resolved_action_plan,
        action_executor_preview,
    )
    report["kvm_calibration_path"] = str(calibration_path)
    calibration_store.save_calibration(calibration, calibration_path)
    calibration_store.save_report(report, report_path)
    return calibration, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate preview-only KVM coordinate calibration."
    )
    parser.add_argument("--source", choices=["auto"], default="auto")
    args = parser.parse_args(argv)
    calibration, report = run_calibration(args.source)
    print(
        "Saved runtime_state/latest_kvm_calibration.json "
        f"(calibrated={calibration.get('calibrated')}, "
        f"points={len(calibration.get('validated_points', []))})."
    )
    print(
        "Saved runtime_state/latest_kvm_calibration_report.json "
        f"(validation_passed={report.get('validation_passed')})."
    )


if __name__ == "__main__":
    main()
