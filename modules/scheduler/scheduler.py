from __future__ import annotations

import argparse
from copy import deepcopy
from typing import Any

from modules.skills.skill_registry import SkillRegistry, default_skill_registry

from . import scheduler_store
from .scheduler_validator import validate_scheduler_run
from .schema import new_scheduler_run, scheduler_failure, utc_now_iso


UNKNOWN_SKILL_POLICY = "stop"


def _blocked_skipped_actions(
    execution_gate: dict[str, Any],
    resolved_action_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    actions = resolved_action_plan.get("actions")
    if not isinstance(actions, list):
        return []
    block_reasons = execution_gate.get("block_reasons")
    return [
        {
            "action_id": action.get("action_id", "") if isinstance(action, dict) else "",
            "skill": action.get("skill", "") if isinstance(action, dict) else "",
            "reason": "execution_gate_blocked",
            "block_reasons": deepcopy(block_reasons if isinstance(block_reasons, list) else []),
        }
        for action in actions
    ]


def _remaining_skipped_actions(actions: list[dict[str, Any]], start_index: int) -> list[dict[str, Any]]:
    return [
        {
            "action_id": action.get("action_id", ""),
            "skill": action.get("skill", ""),
            "reason": "scheduler_stopped_after_failure",
        }
        for action in actions[start_index:]
    ]


def run_scheduler(
    execution_gate: dict[str, Any],
    resolved_action_plan: dict[str, Any],
    registry: SkillRegistry | None = None,
    unknown_skill_policy: str = UNKNOWN_SKILL_POLICY,
) -> tuple[dict[str, Any], dict[str, Any]]:
    skill_registry = registry or default_skill_registry()

    if execution_gate.get("execution_allowed") is not True:
        scheduler_run = new_scheduler_run(
            execution_gate=execution_gate,
            status="blocked",
            executed_actions=[],
            skipped_actions=_blocked_skipped_actions(execution_gate, resolved_action_plan),
            failures=[],
        )
        report = validate_scheduler_run(scheduler_run)
        report.update(
            {
                "source_execution_gate_id": execution_gate.get("execution_gate_id", ""),
                "scheduler_run_path": str(scheduler_store.SCHEDULER_RUN_PATH),
                "created_at": utc_now_iso(),
            }
        )
        return scheduler_run, report

    actions = execution_gate.get("executable_actions")
    if not isinstance(actions, list):
        actions = []

    executed_actions: list[dict[str, Any]] = []
    skipped_actions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            failures.append(
                scheduler_failure(
                    "invalid_action",
                    "Executable action must be an object.",
                )
            )
            skipped_actions.extend(_remaining_skipped_actions(actions, index + 1))
            break

        result = skill_registry.execute(action)
        if result.get("status") == "failed":
            failure = result.get("failure") if isinstance(result.get("failure"), dict) else {}
            failures.append(
                scheduler_failure(
                    str(failure.get("code") or "skill_failed"),
                    str(failure.get("message") or "Dry-run skill failed."),
                    str(action.get("action_id") or ""),
                    str(action.get("skill") or ""),
                )
            )
            if unknown_skill_policy == "mark_failed":
                executed_actions.append(result)
            else:
                skipped_actions.extend(_remaining_skipped_actions(actions, index + 1))
            break

        executed_actions.append(result)

    if failures and executed_actions:
        status = "partial"
    elif failures:
        status = "failed"
    else:
        status = "completed"

    scheduler_run = new_scheduler_run(
        execution_gate=execution_gate,
        status=status,
        executed_actions=executed_actions,
        skipped_actions=skipped_actions,
        failures=failures,
    )
    report = validate_scheduler_run(scheduler_run)
    report.update(
        {
            "source_execution_gate_id": execution_gate.get("execution_gate_id", ""),
            "scheduler_run_path": str(scheduler_store.SCHEDULER_RUN_PATH),
            "created_at": utc_now_iso(),
        }
    )
    return scheduler_run, report


def run(source: str = "auto") -> tuple[dict[str, Any], dict[str, Any]]:
    _ = source
    execution_gate, resolved_action_plan = scheduler_store.load_inputs()
    scheduler_run, report = run_scheduler(execution_gate, resolved_action_plan)
    scheduler_store.save_scheduler_run(scheduler_run)
    scheduler_store.save_report(report)
    return scheduler_run, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run dry-run scheduler for gated actions.")
    parser.add_argument("--source", choices=["auto"], default="auto")
    args = parser.parse_args(argv)
    scheduler_run, report = run(args.source)
    print(
        "Saved runtime_state/latest_scheduler_run.json "
        f"(status={scheduler_run.get('status')}, "
        f"executed={len(scheduler_run.get('executed_actions', []))})."
    )
    print(
        "Saved runtime_state/latest_scheduler_report.json "
        f"(validation_passed={report.get('validation_passed')})."
    )


if __name__ == "__main__":
    main()

