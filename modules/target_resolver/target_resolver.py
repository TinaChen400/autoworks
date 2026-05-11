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
VISUAL_CONTROL_HINTS = {"radio_like", "checkbox_like", "icon_like"}
DEFAULT_RADIO_CONTROL_OFFSET_RATIO = 0.25
DEFAULT_RADIO_CONTROL_OFFSET_MIN_NORM = 0.018
DEFAULT_RADIO_CONTROL_OFFSET_MAX_NORM = 0.03
DEFAULT_RADIO_CONTROL_VERTICAL_RATIO = 0.2


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


def _candidate_from_norm(
    source: str,
    click_point_norm: dict[str, float] | None,
    runtime_context: dict[str, Any],
    confidence: float,
    control_element_id: str = "",
    control_type: str = "unknown",
    is_primary: bool = False,
) -> dict[str, Any] | None:
    if click_point_norm is None:
        return None
    click_point_raw, click_point_screen = norm_to_screen(click_point_norm, runtime_context)
    if not _inside_anchor_model_bounds(click_point_raw, click_point_screen, runtime_context):
        return None
    candidate = {
        "source": source,
        "click_point_norm": click_point_norm,
        "click_point_raw": click_point_raw,
        "click_point_screen": click_point_screen,
        "confidence": round(max(0.0, min(1.0, float(confidence or 0.0))), 3),
    }
    if control_element_id:
        candidate["control_element_id"] = control_element_id
    if control_type:
        candidate["control_type"] = control_type
    if is_primary:
        candidate["is_primary"] = True
    return candidate


def _add_candidate(candidates: list[dict[str, Any]], candidate: dict[str, Any] | None) -> None:
    if candidate is None:
        return
    candidate_key = (
        (candidate.get("click_point_raw") or {}).get("x"),
        (candidate.get("click_point_raw") or {}).get("y"),
    )
    for existing in candidates:
        existing_key = (
            (existing.get("click_point_raw") or {}).get("x"),
            (existing.get("click_point_raw") or {}).get("y"),
        )
        if existing_key == candidate_key:
            return
    candidates.append(candidate)


def _promote_primary_candidate(
    candidates: list[dict[str, Any]],
    preferred_sources: set[str],
) -> dict[str, Any] | None:
    if not candidates:
        return None
    selected_index = 0
    for index, candidate in enumerate(candidates):
        if str(candidate.get("source") or "") in preferred_sources:
            selected_index = index
            break
    for candidate in candidates:
        candidate.pop("is_primary", None)
    primary = candidates[selected_index]
    primary["is_primary"] = True
    if selected_index:
        candidates.insert(0, candidates.pop(selected_index))
    return primary


def _nearby_visual_control_candidates(
    option: dict[str, Any],
    layout_index: dict[str, Any],
    runtime_context: dict[str, Any],
    limit: int = 3,
) -> list[dict[str, Any]]:
    bbox = _numeric_bbox(option.get("bbox_norm"))
    if bbox is None:
        return []
    target_x = bbox["x"] + min(max(bbox["width"] * 0.3, 0.0), bbox["width"])
    target_y = bbox["y"] + (bbox["height"] * DEFAULT_RADIO_CONTROL_VERTICAL_RATIO)
    min_x = max(0.0, bbox["x"] - max(0.035, bbox["width"] * 0.6))
    max_x = min(1.0, bbox["x"] + bbox["width"] + max(0.02, bbox["width"] * 0.4))
    min_y = max(0.0, bbox["y"] - max(0.035, bbox["height"] * 0.75))
    max_y = min(1.0, bbox["y"] + bbox["height"] + max(0.02, bbox["height"] * 0.5))
    scored: list[tuple[float, dict[str, Any]]] = []
    for element in layout_index.get("elements", []) or []:
        if not isinstance(element, dict):
            continue
        hint = str(element.get("element_type_hint") or element.get("control_type") or "").casefold()
        if hint not in VISUAL_CONTROL_HINTS:
            continue
        point = _numeric_point(element.get("click_point_norm"))
        if point is None:
            continue
        if not (min_x <= point["x"] <= max_x and min_y <= point["y"] <= max_y):
            continue
        distance = abs(point["x"] - target_x) + abs(point["y"] - target_y)
        confidence = max(float(element.get("confidence", 0.0) or 0.0), 0.82)
        candidate = _candidate_from_norm(
            "nearby_detected_control",
            point,
            runtime_context,
            confidence,
            str(element.get("element_id", "")),
            hint or "unknown",
        )
        if candidate is not None:
            scored.append((distance, candidate))
    scored.sort(key=lambda item: (-float(item[1].get("confidence", 0.0)), item[0]))
    return [candidate for _distance, candidate in scored[:limit]]


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
    radio_control_vertical_ratio: float = DEFAULT_RADIO_CONTROL_VERTICAL_RATIO,
) -> dict[str, float] | None:
    bbox = _numeric_bbox(option.get("bbox_norm"))
    if bbox is None:
        return None
    ratio_offset = bbox["width"] * max(0.0, radio_control_offset_ratio)
    offset = min(max(ratio_offset, radio_control_offset_min_norm), radio_control_offset_max_norm)
    y_ratio = min(max(radio_control_vertical_ratio, 0.0), 1.0)
    return _numeric_point(
        {
            "x": bbox["x"] + offset,
            "y": bbox["y"] + (bbox["height"] * y_ratio),
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
    layout_index: dict[str, Any],
    associated_control: dict[str, Any] | None = None,
    radio_control_offset_ratio: float = DEFAULT_RADIO_CONTROL_OFFSET_RATIO,
    radio_control_offset_min_norm: float = DEFAULT_RADIO_CONTROL_OFFSET_MIN_NORM,
    radio_control_offset_max_norm: float = DEFAULT_RADIO_CONTROL_OFFSET_MAX_NORM,
    radio_control_vertical_ratio: float = DEFAULT_RADIO_CONTROL_VERTICAL_RATIO,
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
                extra_metadata = {
                    "control_element_id": str(associated_control.get("control_element_id", "")),
                    "control_type": str(associated_control.get("control_type", "unknown")),
                }
        elif click_point_was_inferred:
            adjusted = _radio_left_biased_point(
                option,
                radio_control_offset_ratio,
                radio_control_offset_min_norm,
                radio_control_offset_max_norm,
                radio_control_vertical_ratio,
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
    candidates: list[dict[str, Any]] = []
    _add_candidate(
        candidates,
        _candidate_from_norm(
            resolver_source,
            click_point_norm,
            runtime_context,
            resolver_confidence,
            str(extra_metadata.get("control_element_id", "")),
            str(extra_metadata.get("control_type", _selection_control(option))),
            is_primary=True,
        ),
    )
    if _is_radio_checkbox(option):
        for candidate in _nearby_visual_control_candidates(option, layout_index, runtime_context):
            _add_candidate(candidates, candidate)
        control_point, control_source = _radio_control_point_from_option(option)
        _add_candidate(
            candidates,
            _candidate_from_norm(
                control_source,
                control_point,
                runtime_context,
                0.9,
                control_type=_selection_control(option),
            ),
        )
        left_bias = _radio_left_biased_point(
            option,
            radio_control_offset_ratio,
            radio_control_offset_min_norm,
            radio_control_offset_max_norm,
            radio_control_vertical_ratio,
        )
        _add_candidate(
            candidates,
            _candidate_from_norm(
                "radio_control_left_bias",
                left_bias,
                runtime_context,
                0.82,
                control_type=_selection_control(option),
            ),
        )
    _add_candidate(
        candidates,
        _candidate_from_norm(
            "parsed_option_click_point",
            _numeric_point(option.get("click_point_norm")),
            runtime_context,
            0.65,
            control_type=_selection_control(option),
        ),
    )
    _add_candidate(
        candidates,
        _candidate_from_norm(
            "parsed_option_bbox_center",
            _numeric_bbox_center(option.get("bbox_norm")),
            runtime_context,
            0.55,
            control_type=_selection_control(option),
        ),
    )

    primary = _promote_primary_candidate(
        candidates,
        {"nearby_detected_control"} if _is_radio_checkbox(option) else {resolver_source},
    )
    if primary is not None:
        click_point_norm = primary["click_point_norm"]
        click_point_raw = primary["click_point_raw"]
        click_point_screen = primary["click_point_screen"]
        resolver_confidence = primary["confidence"]
        resolver_source = str(primary.get("source") or resolver_source)
        extra_metadata.pop("resolver_source", None)
        if primary.get("control_element_id"):
            extra_metadata["control_element_id"] = str(primary.get("control_element_id") or "")
        if primary.get("control_type"):
            extra_metadata["control_type"] = str(primary.get("control_type") or "")

    return {
        "click_point_norm": click_point_norm,
        "click_point_raw": click_point_raw,
        "click_point_screen": click_point_screen,
        "resolver_confidence": resolver_confidence,
        "resolver_source": resolver_source,
        "click_candidates": candidates,
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
    radio_control_vertical_ratio: float = DEFAULT_RADIO_CONTROL_VERTICAL_RATIO,
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
                layout_index,
                associated_control,
                radio_control_offset_ratio,
                radio_control_offset_min_norm,
                radio_control_offset_max_norm,
                radio_control_vertical_ratio,
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
        primary_candidate = _candidate_from_norm(
            str(control.get("match_source") or "associated_control_geometry"),
            click_point_norm,
            runtime_context,
            float(control.get("resolver_confidence", 0.0) or 0.0),
            str(control.get("control_element_id", "")),
            str(control.get("control_type", "unknown")),
            is_primary=True,
        )

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
            "resolver_source": str(control.get("match_source") or "associated_control_geometry"),
            "click_candidates": [primary_candidate] if primary_candidate is not None else [],
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
    radio_control_vertical_ratio: float = DEFAULT_RADIO_CONTROL_VERTICAL_RATIO,
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
        radio_control_vertical_ratio=radio_control_vertical_ratio,
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
    parser.add_argument("--radio-control-vertical-ratio", type=float, default=DEFAULT_RADIO_CONTROL_VERTICAL_RATIO)
    args = parser.parse_args(argv)
    plan, report = run(
        args.source,
        args.radio_control_offset_ratio,
        args.radio_control_offset_min_norm,
        args.radio_control_offset_max_norm,
        args.radio_control_vertical_ratio,
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
