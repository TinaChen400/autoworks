from __future__ import annotations

import argparse
from copy import deepcopy
from typing import Any

from . import gate_store
from .gate_validator import validate_execution_gate
from .schema import RESOLVER_CONFIDENCE_THRESHOLD, block_reason, new_execution_gate, utc_now_iso


def _click_point_screen_present(action: dict[str, Any]) -> bool:
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    click_point = target.get("click_point_screen")
    return isinstance(click_point, dict) and "x" in click_point and "y" in click_point


def _drag_points_present(action: dict[str, Any]) -> bool:
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    start = target.get("start_point_screen") or target.get("start_point")
    end = target.get("end_point_screen") or target.get("end_point")
    return (
        isinstance(start, dict)
        and "x" in start
        and "y" in start
        and isinstance(end, dict)
        and "x" in end
        and "y" in end
    )


def _resolver_confidence(action: dict[str, Any]) -> float:
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    try:
        return float(target.get("resolver_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def evaluate_execution_gate(
    resolved_action_plan: dict[str, Any],
    target_resolver_report: dict[str, Any],
    action_plan_report: dict[str, Any] | None = None,
    answer_engine_report: dict[str, Any] | None = None,
    survey_session: dict[str, Any] | None = None,
    source: str = "auto",
    resolver_confidence_threshold: float = RESOLVER_CONFIDENCE_THRESHOLD,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _ = (action_plan_report, answer_engine_report, survey_session, source)
    block_reasons: list[dict[str, Any]] = []
    actions = resolved_action_plan.get("actions", [])
    if not isinstance(actions, list):
        actions = []
        block_reasons.append(
            block_reason("invalid_actions", "Resolved action plan actions must be a list.")
        )

    if resolved_action_plan.get("status") == "human_review_required":
        block_reasons.append(
            block_reason(
                "human_review_required",
                "Action plan requires human review before execution.",
            )
        )

    if target_resolver_report.get("validation_passed") is not True:
        block_reasons.append(
            block_reason("target_resolver_invalid", "Target resolver validation did not pass.")
        )

    for action in actions:
        if not isinstance(action, dict):
            block_reasons.append(
                block_reason("invalid_action", "Resolved action must be an object.")
            )
            continue

        action_id = str(action.get("action_id", ""))
        skill = action.get("skill")
        if skill == "request_human_review":
            block_reasons.append(
                block_reason(
                    "request_human_review",
                    "Resolved action plan contains an action that requests human review.",
                    action_id,
                )
            )
            continue

        if skill in {"click_option", "click_navigation", "type_text"}:
            if not _click_point_screen_present(action):
                block_reasons.append(
                    block_reason(
                        "missing_click_point_screen",
                        f"{skill} action is missing click_point_screen.",
                        action_id,
                    )
                )
            confidence = _resolver_confidence(action)
            if confidence < resolver_confidence_threshold:
                block_reasons.append(
                    block_reason(
                        "resolver_confidence_below_threshold",
                        f"{skill} resolver_confidence is below the execution threshold.",
                        action_id,
                    )
                    | {
                        "resolver_confidence": confidence,
                        "threshold": resolver_confidence_threshold,
                    }
                )
        elif skill == "drag":
            if not _drag_points_present(action):
                block_reasons.append(
                    block_reason(
                        "missing_drag_points",
                        "drag action is missing start_point_screen or end_point_screen.",
                        action_id,
                    )
                )
        elif skill == "scroll":
            params = action.get("params") if isinstance(action.get("params"), dict) else {}
            direction = str(params.get("direction") or "down")
            if direction not in {"up", "down"}:
                block_reasons.append(
                    block_reason(
                        "invalid_scroll_direction",
                        "scroll direction must be up or down.",
                        action_id,
                    )
                )
        else:
            block_reasons.append(
                block_reason(
                    "unsupported_skill",
                    f"{skill} is not supported for real execution.",
                    action_id,
                )
            )

    execution_allowed = not block_reasons
    executable_actions = deepcopy(actions) if execution_allowed else []
    gate = new_execution_gate(
        resolved_action_plan=resolved_action_plan,
        execution_allowed=execution_allowed,
        block_reasons=block_reasons,
        executable_actions=executable_actions,
    )
    report = validate_execution_gate(gate)
    report.update(
        {
            "source_resolved_action_plan_id": resolved_action_plan.get(
                "resolved_action_plan_id",
                "",
            ),
            "execution_gate_path": str(gate_store.EXECUTION_GATE_PATH),
            "created_at": utc_now_iso(),
        }
    )
    return gate, report


def run(source: str = "auto") -> tuple[dict[str, Any], dict[str, Any]]:
    (
        resolved_action_plan,
        target_report,
        action_report,
        answer_report,
        survey_session,
    ) = gate_store.load_inputs()
    gate, report = evaluate_execution_gate(
        resolved_action_plan=resolved_action_plan,
        target_resolver_report=target_report,
        action_plan_report=action_report,
        answer_engine_report=answer_report,
        survey_session=survey_session,
        source=source,
    )
    gate_store.save_execution_gate(gate)
    gate_store.save_report(report)
    return gate, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Gate a resolved action plan before execution.")
    parser.add_argument("--source", choices=["auto"], default="auto")
    args = parser.parse_args(argv)
    gate, report = run(args.source)
    print(
        "Saved runtime_state/latest_execution_gate.json "
        f"(status={gate.get('status')}, execution_allowed={gate.get('execution_allowed')})."
    )
    print(
        "Saved runtime_state/latest_execution_gate_report.json "
        f"(validation_passed={report.get('validation_passed')})."
    )


if __name__ == "__main__":
    main()
