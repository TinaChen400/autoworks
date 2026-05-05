from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import preview_store
from .schema import (
    MOUSE_PREVIEW_SKILLS,
    VALID_PREVIEW_STATUSES,
    executor_failure,
    new_action_executor_preview,
    utc_now_iso,
)


def _target(action: dict[str, Any]) -> dict[str, Any]:
    target = action.get("target")
    return target if isinstance(target, dict) else {}


def _click_point_screen(action: dict[str, Any]) -> dict[str, Any] | None:
    click_point = _target(action).get("click_point_screen")
    if not isinstance(click_point, dict):
        return None
    if "x" not in click_point or "y" not in click_point:
        return None
    return {"x": click_point["x"], "y": click_point["y"]}


def _click_option_record(
    action: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    click_point = _click_point_screen(action)
    action_id = str(action.get("action_id") or "")
    skill = str(action.get("skill") or "")
    if click_point is None:
        return None, executor_failure(
            "missing_click_point_screen",
            "click_option preview requires click_point_screen.",
            action_id,
            skill,
        )

    target = _target(action)
    return {
        "record_type": "action",
        "action_id": action_id,
        "skill": skill,
        "option_id": target.get("option_id", ""),
        "option_text": target.get("option_text", ""),
        "click_point_screen": click_point,
        "real_execution": False,
    }, None


def _atomic_step_record(
    source_action: dict[str, Any],
    step: dict[str, Any],
    step_index: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    skill = str(step.get("skill") or "")
    if skill not in MOUSE_PREVIEW_SKILLS:
        return None, None

    click_point = _click_point_screen(step)
    action_id = str(step.get("action_id") or source_action.get("action_id") or "")
    if click_point is None:
        return None, executor_failure(
            "missing_atomic_click_point_screen",
            f"{skill} preview requires click_point_screen.",
            action_id,
            skill,
        )

    source_target = _target(source_action)
    return {
        "record_type": "atomic_step",
        "action_id": action_id,
        "skill": skill,
        "option_id": source_target.get("option_id", ""),
        "option_text": source_target.get("option_text", ""),
        "step_index": step_index,
        "click_point_screen": click_point,
        "real_execution": False,
    }, None


def _scheduler_block_reason(scheduler_run: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": "scheduler_run_not_completed",
        "message": "Action executor preview requires a completed scheduler dry run.",
        "scheduler_status": scheduler_run.get("status", ""),
    }


def validate_action_executor_preview(preview: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    status = preview.get("status")
    records = preview.get("preview_records")
    failures = preview.get("failures")

    if status not in VALID_PREVIEW_STATUSES:
        issues.append({"type": "invalid_status", "status": status})
    if preview.get("preview_mode") is not True:
        issues.append({"type": "preview_mode_required"})
    if preview.get("real_execution") is not False:
        issues.append({"type": "real_execution_must_be_false"})
    if not isinstance(records, list):
        issues.append({"type": "invalid_preview_records"})
        records = []
    if not isinstance(failures, list):
        issues.append({"type": "invalid_failures"})
        failures = []

    for record in records:
        if not isinstance(record, dict):
            issues.append({"type": "invalid_preview_record"})
            continue
        if record.get("real_execution") is not False:
            issues.append({"type": "preview_record_real_execution_not_false"})
        if not isinstance(record.get("click_point_screen"), dict):
            issues.append(
                {
                    "type": "preview_record_missing_click_point_screen",
                    "action_id": record.get("action_id", ""),
                }
            )

    if status == "completed" and failures:
        issues.append({"type": "completed_preview_has_failures"})
    if status == "failed" and not failures:
        issues.append({"type": "failed_preview_missing_failures"})

    return {
        "validation_passed": not issues,
        "issues": issues,
        "warnings": [],
        "status": status,
        "preview_record_count": len(records),
        "failure_count": len(failures),
        "real_execution": preview.get("real_execution") is True,
    }


def build_action_executor_preview(
    execution_gate: dict[str, Any],
    scheduler_run: dict[str, Any],
    resolved_action_plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if execution_gate.get("execution_allowed") is not True:
        block_reasons = execution_gate.get("block_reasons")
        preview = new_action_executor_preview(
            execution_gate,
            scheduler_run,
            resolved_action_plan,
            "blocked",
            [],
            [],
            deepcopy(block_reasons if isinstance(block_reasons, list) else []),
        )
        return preview, _report(preview)

    if scheduler_run.get("status") != "completed":
        preview = new_action_executor_preview(
            execution_gate,
            scheduler_run,
            resolved_action_plan,
            "blocked",
            [],
            [],
            [_scheduler_block_reason(scheduler_run)],
        )
        return preview, _report(preview)

    preview_records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    executed_actions = scheduler_run.get("executed_actions")
    if not isinstance(executed_actions, list):
        executed_actions = []

    for action in executed_actions:
        if not isinstance(action, dict):
            failures.append(
                executor_failure("invalid_action", "Executed action must be an object.")
            )
            continue
        if action.get("skill") != "click_option":
            continue

        record, failure = _click_option_record(action)
        if record is not None:
            preview_records.append(record)
        if failure is not None:
            failures.append(failure)

        atomic_steps = action.get("atomic_steps")
        if not isinstance(atomic_steps, list):
            continue
        for step_index, step in enumerate(atomic_steps):
            if not isinstance(step, dict):
                continue
            step_record, step_failure = _atomic_step_record(action, step, step_index)
            if step_record is not None:
                preview_records.append(step_record)
            if step_failure is not None:
                failures.append(step_failure)

    status = "failed" if failures else "completed"
    preview = new_action_executor_preview(
        execution_gate,
        scheduler_run,
        resolved_action_plan,
        status,
        preview_records,
        failures,
        [],
    )
    return preview, _report(preview)


def _report(preview: dict[str, Any]) -> dict[str, Any]:
    report = validate_action_executor_preview(preview)
    report.update(
        {
            "source_execution_gate_id": preview.get("source_execution_gate_id", ""),
            "source_scheduler_run_id": preview.get("source_scheduler_run_id", ""),
            "action_executor_preview_path": str(preview_store.ACTION_EXECUTOR_PREVIEW_PATH),
            "created_at": utc_now_iso(),
        }
    )
    return report


def run_preview(
    source: str = "auto",
    runtime_dir: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _ = source
    if runtime_dir is None:
        execution_gate, scheduler_run, resolved_action_plan = preview_store.load_inputs()
        preview_path = preview_store.ACTION_EXECUTOR_PREVIEW_PATH
        report_path = preview_store.ACTION_EXECUTOR_REPORT_PATH
    else:
        runtime = Path(runtime_dir)
        execution_gate = preview_store.load_json(runtime / "latest_execution_gate.json")
        scheduler_run = preview_store.load_json(runtime / "latest_scheduler_run.json")
        resolved_action_plan = preview_store.load_json(runtime / "latest_resolved_action_plan.json")
        preview_path, report_path = preview_store.paths_for_runtime(runtime)

    preview, report = build_action_executor_preview(
        execution_gate,
        scheduler_run,
        resolved_action_plan,
    )
    report["action_executor_preview_path"] = str(preview_path)
    preview_store.save_preview(preview, preview_path)
    preview_store.save_report(report, report_path)
    return preview, report


def run_preview_from_payloads(
    execution_gate: dict[str, Any],
    scheduler_run: dict[str, Any],
    resolved_action_plan: dict[str, Any],
    runtime_dir: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    preview_path, report_path = preview_store.paths_for_runtime(runtime_dir)
    preview, report = build_action_executor_preview(
        execution_gate,
        scheduler_run,
        resolved_action_plan,
    )
    report["action_executor_preview_path"] = str(preview_path)
    preview_store.save_preview(preview, preview_path)
    preview_store.save_report(report, report_path)
    return preview, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate preview-only action executor output.")
    parser.add_argument("--source", choices=["auto"], default="auto")
    args = parser.parse_args(argv)
    preview, report = run_preview(args.source)
    print(
        "Saved runtime_state/latest_action_executor_preview.json "
        f"(status={preview.get('status')}, "
        f"records={len(preview.get('preview_records', []))})."
    )
    print(
        "Saved runtime_state/latest_action_executor_report.json "
        f"(validation_passed={report.get('validation_passed')})."
    )


if __name__ == "__main__":
    main()
