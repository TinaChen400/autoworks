from __future__ import annotations

import argparse
from copy import deepcopy
from typing import Any

from . import resolved_action_store
from .coordinate_converter import norm_to_screen
from .option_matcher import find_control, find_option, option_text, parsed_page
from .schema import COORDINATE_KEYS, new_resolved_plan, now_iso, unresolved_issue
from .target_resolver_validator import validate_resolved_action_plan


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


def _resolve_from_parsed_geometry(
    option: dict[str, Any],
    runtime_context: dict[str, Any],
) -> dict[str, Any] | None:
    click_point_norm = _numeric_point(option.get("click_point_norm"))
    resolver_confidence = 0.85
    resolver_source = "parsed_option_geometry"
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
        parsed_geometry = (
            _resolve_from_parsed_geometry(parsed_option, runtime_context)
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


def run(source: str = "auto") -> tuple[dict[str, Any], dict[str, Any]]:
    action_plan, orchestrated_parse, layout_index, runtime_context = resolved_action_store.load_inputs()
    plan, report = resolve_action_plan(
        action_plan=action_plan,
        orchestrated_parse=orchestrated_parse,
        layout_index=layout_index,
        runtime_context=runtime_context,
        source=source,
    )
    resolved_action_store.save_resolved_action_plan(plan)
    resolved_action_store.save_report(report)
    return plan, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Resolve logical click_option actions to coordinates.")
    parser.add_argument("--source", choices=["auto"], default="auto")
    args = parser.parse_args(argv)
    plan, report = run(args.source)
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
