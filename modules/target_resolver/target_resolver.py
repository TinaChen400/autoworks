from __future__ import annotations

import argparse
from copy import deepcopy
from typing import Any

from . import resolved_action_store
from .coordinate_converter import norm_to_screen
from .option_matcher import find_control, find_option, option_text
from .schema import COORDINATE_KEYS, new_resolved_plan, now_iso, unresolved_issue
from .target_resolver_validator import validate_resolved_action_plan


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
        question_id = str(target.get("question_id", ""))
        option_id = str(target.get("option_id", ""))
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
