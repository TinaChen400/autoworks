from __future__ import annotations

import argparse
from copy import deepcopy
from typing import Any

from . import resolved_action_store
from .coordinate_converter import norm_to_screen
from .option_matcher import find_control, find_option, option_text, parsed_page
from .schema import COORDINATE_KEYS, new_resolved_plan, now_iso, unresolved_issue
from .target_resolver_validator import validate_resolved_action_plan


RADIO_CHECKBOX_CONTROLS = {"radio", "checkbox"}
DEFAULT_RADIO_CONTROL_OFFSET_RATIO = 0.25
DEFAULT_RADIO_CONTROL_OFFSET_MIN_NORM = 0.018
DEFAULT_RADIO_CONTROL_OFFSET_MAX_NORM = 0.03


def _numeric_point(point: Any) -> dict[str, float] | None:
    if not isinstance(point, dict):
        return None
    try:
        x = float(point["x"])
        y = float(point["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
        return None
    return {"x": round(x, 6), "y": round(y, 6)}


def _numeric_bbox_center(bbox: Any) -> dict[str, float] | None:
    if not isinstance(bbox, dict):
        return None
    try:
        x = float(bbox["x"])
        y = float(bbox["y"])
        width = float(bbox["width"])
        height = float(bbox["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if width < 0.0 or height < 0.0:
        return None
    center = {"x": x + (width / 2.0), "y": y + (height / 2.0)}
    return _numeric_point(center)


def _numeric_bbox(bbox: Any) -> dict[str, float] | None:
    if not isinstance(bbox, dict):
        return None
    try:
        x = float(bbox["x"])
        y = float(bbox["y"])
        width = float(bbox["width"])
        height = float(bbox["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if width < 0.0 or height < 0.0:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _number(data: dict[str, Any], key: str) -> float | None:
    try:
        return float(data[key])
    except (KeyError, TypeError, ValueError):
        return None


def _inside_rect(point: dict[str, int], rect: dict[str, Any]) -> bool:
    x = _number(rect, "x")
    y = _number(rect, "y")
    width = _number(rect, "width")
    height = _number(rect, "height")
    if x is None or y is None or width is None or height is None:
        return False
    if width < 0 or height < 0:
        return False
    return x <= point["x"] <= x + width and y <= point["y"] <= y + height


def _inside_anchor_model_bounds(
    click_point_raw: dict[str, int],
    click_point_screen: dict[str, int],
    runtime_context: dict[str, Any],
) -> bool:
    model_region = runtime_context.get("model_input_region")
    anchor = runtime_context.get("anchor_frame")
    if not isinstance(model_region, dict) or not isinstance(anchor, dict):
        return False
    if not _inside_rect(click_point_raw, model_region):
        return False
    anchor_model_bounds = {
        "x": (_number(anchor, "x") or 0.0) + (_number(model_region, "x") or 0.0),
        "y": (_number(anchor, "y") or 0.0) + (_number(model_region, "y") or 0.0),
        "width": _number(model_region, "width"),
        "height": _number(model_region, "height"),
    }
    if not _inside_rect(click_point_screen, anchor_model_bounds):
        return False
    return _inside_rect(click_point_screen, anchor)


def _find_exact_parsed_option(
    orchestrated_parse: dict[str, Any],
    question_id: Any,
    option_id: Any,
) -> dict[str, Any] | None:
    page = parsed_page(orchestrated_parse)
    for question in page.get("questions", []) or []:
        if not isinstance(question, dict) or question.get("question_id") != question_id:
            continue
        for option in question.get("answer_options", []) or []:
            if isinstance(option, dict) and option.get("option_id") == option_id:
                return option
    return None


def _selection_control(option: dict[str, Any]) -> str:
    return str(
        option.get("selection_control")
        or option.get("control_type")
        or option.get("option_type")
        or "unknown"
    ).casefold()


def _is_radio_checkbox(option: dict[str, Any]) -> bool:
    return _selection_control(option) in RADIO_CHECKBOX_CONTROLS


def _points_match(first: dict[str, float] | None, second: dict[str, float] | None) -> bool:
    if first is None or second is None:
        return False
    return abs(first["x"] - second["x"]) <= 0.000001 and abs(first["y"] - second["y"]) <= 0.000001


def _radio_control_point_from_option(option: dict[str, Any]) -> tuple[dict[str, float] | None, str]:
    click_point = _numeric_point(option.get("control_click_point_norm"))
    if click_point is not None:
        return click_point, "parsed_control_click_point"
    bbox_center = _numeric_bbox_center(option.get("control_bbox_norm"))
    if bbox_center is not None:
        return bbox_center, "parsed_control_bbox_center"
    return None, ""


def _radio_left_biased_point(
    option: dict[str, Any],
    radio_control_offset_ratio: float = DEFAULT_RADIO_CONTROL_OFFSET_RATIO,
    radio_control_offset_min_norm: float = DEFAULT_RADIO_CONTROL_OFFSET_MIN_NORM,
    radio_control_offset_max_norm: float = DEFAULT_RADIO_CONTROL_OFFSET_MAX_NORM,
) -> dict[str, float] | None:
    bbox = _numeric_bbox(option.get("bbox_norm"))
    if bbox is None:
        return None
    ratio_offset = bbox["width"] * max(0.0, radio_control_offset_ratio)
    offset = min(max(ratio_offset, radio_control_offset_min_norm), radio_control_offset_max_norm)
    return _numeric_point(
        {
            "x": bbox["x"] + offset,
            "y": bbox["y"] + (bbox["height"] / 2.0),
        }
    )


def _metadata_for_adjusted_radio_point(
    option: dict[str, Any],
    original_click_point_norm: dict[str, float] | None,
    adjusted_click_point_norm: dict[str, float],
    source: str,
    reason: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "resolver_source": source,
        "adjusted_click_point_norm": adjusted_click_point_norm,
        "selection_control": _selection_control(option),
        "adjustment_reason": reason,
    }
    if original_click_point_norm is not None:
        metadata["original_click_point_norm"] = original_click_point_norm
    return metadata


def _resolve_from_parsed_geometry(
    option: dict[str, Any],
    runtime_context: dict[str, Any],
    associated_control: dict[str, Any] | None = None,
    radio_control_offset_ratio: float = DEFAULT_RADIO_CONTROL_OFFSET_RATIO,
    radio_control_offset_min_norm: float = DEFAULT_RADIO_CONTROL_OFFSET_MIN_NORM,
    radio_control_offset_max_norm: float = DEFAULT_RADIO_CONTROL_OFFSET_MAX_NORM,
) -> dict[str, Any] | None:
    click_point_norm = _numeric_point(option.get("click_point_norm"))
    resolver_confidence = 0.85
    resolver_source = "parsed_option_geometry"
    extra_metadata: dict[str, Any] = {}

    if _is_radio_checkbox(option):
        original_click_point_norm = click_point_norm
        bbox_center = _numeric_bbox_center(option.get("bbox_norm"))
        click_point_was_inferred = _points_match(click_point_norm, bbox_center)

        control_point, control_source = _radio_control_point_from_option(option)
        if control_point is not None:
            click_point_norm = control_point
            resolver_confidence = 0.9
            resolver_source = control_source
        elif (
            (click_point_was_inferred or click_point_norm is None)
            and associated_control is not None
            and associated_control.get("match_source") != "parsed_option_click_point"
        ):
            control_point = _numeric_point(associated_control.get("click_point_norm"))
            if control_point is not None:
                click_point_norm = control_point
                resolver_confidence = float(associated_control.get("resolver_confidence", 0.8) or 0.8)
                resolver_source = str(associated_control.get("match_source") or "associated_control_geometry")
        elif click_point_was_inferred:
            adjusted = _radio_left_biased_point(
                option,
                radio_control_offset_ratio,
                radio_control_offset_min_norm,
                radio_control_offset_max_norm,
            )
            if adjusted is not None:
                click_point_norm = adjusted
                resolver_confidence = 0.82
                resolver_source = "radio_control_left_bias"
                extra_metadata = _metadata_for_adjusted_radio_point(
                    option,
                    original_click_point_norm,
                    adjusted,
                    resolver_source,
                    "parsed click point was inferred from option bbox center",
                )

    if click_point_norm is None:
        click_point_norm = _numeric_bbox_center(option.get("bbox_norm"))
        resolver_confidence = 0.8
        resolver_source = "parsed_option_bbox_center"
    if click_point_norm is None:
        return None

    click_point_raw, click_point_screen = norm_to_screen(click_point_norm, runtime_context)
    if not _inside_anchor_model_bounds(click_point_raw, click_point_screen, runtime_context):
        return None

    return {
        "click_point_norm": click_point_norm,
        "click_point_raw": click_point_raw,
        "click_point_screen": click_point_screen,
        "resolver_confidence": resolver_confidence,
        "resolver_source": resolver_source,
        **extra_metadata,
    }


def _strip_coordinates(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_coordinates(child) for key, child in value.items() if key not in COORDINATE_KEYS}
    if isinstance(value, list):
        return [_strip_coordinates(child) for child in value]
    return value


def resolve_action_plan(
    action_plan: dict[str, Any],
    orchestrated_parse: dict[str, Any],
    layout_index: dict[str, Any],
    runtime_context: dict[str, Any],
    source: str = "auto",
    radio_control_offset_ratio: float = DEFAULT_RADIO_CONTROL_OFFSET_RATIO,
    radio_control_offset_min_norm: float = DEFAULT_RADIO_CONTROL_OFFSET_MIN_NORM,
    radio_control_offset_max_norm: float = DEFAULT_RADIO_CONTROL_OFFSET_MAX_NORM,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _ = source
    actions: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    for action in action_plan.get("actions", []):
        resolved = deepcopy(action)
        skill = resolved.get("skill", "")

        if skill == "request_human_review":
            actions.append(_strip_coordinates(resolved))
            continue

        if skill != "click_option":
            actions.append(resolved)
            continue

        target = resolved.get("target") if isinstance(resolved.get("target"), dict) else {}
        question_id_value = target.get("question_id", "")
        option_id_value = target.get("option_id", "")
        question_id = str(question_id_value)
        option_id = str(option_id_value)

        parsed_option = _find_exact_parsed_option(orchestrated_parse, question_id_value, option_id_value)
        associated_control = find_control(parsed_option, layout_index) if parsed_option is not None else None
        parsed_geometry = (
            _resolve_from_parsed_geometry(
                parsed_option,
                runtime_context,
                associated_control,
                radio_control_offset_ratio,
                radio_control_offset_min_norm,
                radio_control_offset_max_norm,
            )
            if parsed_option is not None
            else None
        )
        if parsed_geometry is not None:
            resolved["target"] = {
                "question_id": question_id,
                "option_id": option_id,
                "option_text": option_text(parsed_option),
                "control_element_id": "",
                "control_type": str(parsed_option.get("selection_control") or "unknown"),
                **parsed_geometry,
            }
            actions.append(resolved)
            continue

        option = find_option(orchestrated_parse, question_id, option_id)
        if option is None:
            issues.append(
                unresolved_issue(
                    resolved,
                    "option_not_found",
                    "click_option option_id was not found in latest_orchestrated_parse.json",
                )
            )
            actions.append(resolved)
            continue

        control = find_control(option, layout_index)
        if control is None or not isinstance(control.get("click_point_norm"), dict):
            issues.append(
                unresolved_issue(
                    resolved,
                    "control_not_found",
                    "click_option control target was not found in latest_layout_index.json",
                )
            )
            actions.append(resolved)
            continue

        click_point_norm = {
            "x": round(float(control["click_point_norm"].get("x", 0.0)), 6),
            "y": round(float(control["click_point_norm"].get("y", 0.0)), 6),
        }
        click_point_raw, click_point_screen = norm_to_screen(click_point_norm, runtime_context)

        resolved["target"] = {
            "question_id": question_id,
            "option_id": option_id,
            "option_text": option_text(option),
            "control_element_id": control.get("control_element_id", ""),
            "control_type": control.get("control_type", "unknown"),
            "click_point_norm": click_point_norm,
            "click_point_raw": click_point_raw,
            "click_point_screen": click_point_screen,
            "resolver_confidence": control.get("resolver_confidence", 0.0),
        }
        actions.append(resolved)

    plan = new_resolved_plan(action_plan, actions, warnings)
    report = validate_resolved_action_plan(plan, issues)
    report.update(
        {
            "source_action_plan_id": action_plan.get("action_plan_id", ""),
            "resolved_action_plan_path": str(resolved_action_store.RESOLVED_ACTION_PLAN_PATH),
            "created_at": now_iso(),
        }
    )
    if not report["validation_passed"]:
        plan["status"] = "invalid"
    return plan, report


def run(
    source: str = "auto",
    radio_control_offset_ratio: float = DEFAULT_RADIO_CONTROL_OFFSET_RATIO,
    radio_control_offset_min_norm: float = DEFAULT_RADIO_CONTROL_OFFSET_MIN_NORM,
    radio_control_offset_max_norm: float = DEFAULT_RADIO_CONTROL_OFFSET_MAX_NORM,
) -> tuple[dict[str, Any], dict[str, Any]]:
    action_plan, orchestrated_parse, layout_index, runtime_context = resolved_action_store.load_inputs()
    plan, report = resolve_action_plan(
        action_plan=action_plan,
        orchestrated_parse=orchestrated_parse,
        layout_index=layout_index,
        runtime_context=runtime_context,
        source=source,
        radio_control_offset_ratio=radio_control_offset_ratio,
        radio_control_offset_min_norm=radio_control_offset_min_norm,
        radio_control_offset_max_norm=radio_control_offset_max_norm,
    )
    resolved_action_store.save_resolved_action_plan(plan)
    resolved_action_store.save_report(report)
    return plan, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Resolve logical click_option actions to coordinates.")
    parser.add_argument("--source", choices=["auto"], default="auto")
    parser.add_argument("--radio-control-offset-ratio", type=float, default=DEFAULT_RADIO_CONTROL_OFFSET_RATIO)
    parser.add_argument("--radio-control-offset-min-norm", type=float, default=DEFAULT_RADIO_CONTROL_OFFSET_MIN_NORM)
    parser.add_argument("--radio-control-offset-max-norm", type=float, default=DEFAULT_RADIO_CONTROL_OFFSET_MAX_NORM)
    args = parser.parse_args(argv)
    plan, report = run(
        args.source,
        args.radio_control_offset_ratio,
        args.radio_control_offset_min_norm,
        args.radio_control_offset_max_norm,
    )
    print(
        "Saved runtime_state/latest_resolved_action_plan.json "
        f"(status={plan.get('status')}, actions={len(plan.get('actions', []))})."
    )
    print(
        "Saved runtime_state/latest_target_resolver_report.json "
        f"(validation_passed={report.get('validation_passed')})."
    )


if __name__ == "__main__":
    main()
