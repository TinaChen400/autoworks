from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import safety_store
from .safety_validator import validate_execution_safety_guard
from .schema import (
    DEFAULT_EXECUTION_SAFETY_CONFIG,
    MVP_BLOCKED_REAL_SKILLS,
    block_reason,
    new_execution_safety_guard,
    utc_now_iso,
)


def _merged_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_EXECUTION_SAFETY_CONFIG)
    merged.update(config)
    return merged


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _preview_records(action_executor_preview: dict[str, Any]) -> list[dict[str, Any]]:
    records = action_executor_preview.get("preview_records")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _real_candidate_actions(action_executor_preview: dict[str, Any]) -> list[dict[str, Any]]:
    records = _preview_records(action_executor_preview)
    atomic_records = [record for record in records if record.get("record_type") == "atomic_step"]
    source_records = atomic_records if atomic_records else records
    candidates: list[dict[str, Any]] = []
    for index, record in enumerate(source_records):
        skill = str(record.get("skill") or "")
        candidates.append(
            {
                "candidate_id": f"real_candidate_{index + 1}",
                "source": "action_executor_preview",
                "record_type": record.get("record_type", ""),
                "action_id": record.get("action_id", ""),
                "skill": skill,
                "click_point_screen": deepcopy(record.get("click_point_screen", {})),
                "real_execution": False,
            }
        )
    return candidates


def _action_skills(value: Any) -> list[tuple[str, str]]:
    skills: list[tuple[str, str]] = []
    if isinstance(value, dict):
        skill = value.get("skill")
        action_id = str(value.get("action_id") or "")
        if isinstance(skill, str):
            skills.append((skill, action_id))
        for child in value.values():
            skills.extend(_action_skills(child))
    elif isinstance(value, list):
        for item in value:
            skills.extend(_action_skills(item))
    return skills


def _safety_checks(
    config: dict[str, Any],
    execution_gate: dict[str, Any],
    scheduler_run: dict[str, Any],
    action_executor_preview: dict[str, Any],
    kvm_calibration: dict[str, Any],
    kvm_calibration_report: dict[str, Any],
) -> dict[str, bool]:
    return {
        "execution_gate_allowed": execution_gate.get("execution_allowed") is True,
        "scheduler_completed": scheduler_run.get("status") == "completed",
        "action_executor_preview_completed": action_executor_preview.get("status") == "completed",
        "action_executor_preview_real_execution_false": (
            action_executor_preview.get("real_execution") is False
        ),
        "kvm_calibrated": kvm_calibration.get("calibrated") is True,
        "kvm_calibration_report_valid": kvm_calibration_report.get("validation_passed") is True,
        "manual_start_confirmed": config.get("manual_start_confirmed") is True,
        "test_environment_confirmed": config.get("test_environment_confirmed") is True,
    }


def evaluate_execution_safety_guard(
    config: dict[str, Any],
    execution_gate: dict[str, Any],
    scheduler_run: dict[str, Any],
    action_executor_preview: dict[str, Any],
    kvm_calibration: dict[str, Any],
    kvm_calibration_report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = _merged_config(config)
    block_reasons: list[dict[str, Any]] = []
    candidates = _real_candidate_actions(action_executor_preview)
    checks = _safety_checks(
        config,
        execution_gate,
        scheduler_run,
        action_executor_preview,
        kvm_calibration,
        kvm_calibration_report,
    )

    if config.get("allow_real_execution") is not True:
        block_reasons.append(
            block_reason("real_execution_disabled", "allow_real_execution is false.")
        )
    if config.get("execution_mode") != "kvm_real":
        block_reasons.append(
            block_reason(
                "execution_mode_not_kvm_real",
                'execution_mode must be "kvm_real" for real execution.',
                execution_mode=config.get("execution_mode"),
            )
        )
    if (
        config.get("require_execution_gate_allowed") is True
        and not checks["execution_gate_allowed"]
    ):
        block_reasons.append(
            block_reason(
                "execution_gate_not_allowed",
                "latest_execution_gate.execution_allowed is not true.",
            )
        )
    if config.get("require_scheduler_completed") is True and not checks["scheduler_completed"]:
        block_reasons.append(
            block_reason(
                "scheduler_not_completed",
                'latest_scheduler_run.status is not "completed".',
            )
        )
    if (
        config.get("require_action_executor_preview_completed") is True
        and not checks["action_executor_preview_completed"]
    ):
        block_reasons.append(
            block_reason(
                "action_executor_preview_not_completed",
                'latest_action_executor_preview.status is not "completed".',
            )
        )
    if not checks["action_executor_preview_real_execution_false"]:
        block_reasons.append(
            block_reason(
                "action_executor_preview_real_execution_not_false",
                "latest_action_executor_preview.real_execution must be false.",
            )
        )
    if config.get("require_kvm_calibrated") is True and not checks["kvm_calibrated"]:
        block_reasons.append(
            block_reason("kvm_not_calibrated", "latest_kvm_calibration.calibrated is not true.")
        )
    if (
        config.get("require_kvm_calibrated") is True
        and not checks["kvm_calibration_report_valid"]
    ):
        block_reasons.append(
            block_reason(
                "kvm_calibration_report_invalid",
                "latest_kvm_calibration_report.validation_passed is not true.",
            )
        )
    if config.get("require_manual_start") is True and not checks["manual_start_confirmed"]:
        block_reasons.append(
            block_reason(
                "manual_start_not_confirmed",
                "manual_start_confirmed must be explicitly true.",
            )
        )
    if config.get("safe_test_mode_only") is True and not checks["test_environment_confirmed"]:
        block_reasons.append(
            block_reason(
                "test_environment_not_confirmed",
                "test_environment_confirmed must be explicitly true.",
            )
        )

    max_actions = config.get("max_real_actions_per_run")
    if not isinstance(max_actions, int) or isinstance(max_actions, bool) or max_actions < 0:
        max_actions = 0
        block_reasons.append(
            block_reason(
                "invalid_max_real_actions_per_run",
                "max_real_actions_per_run must be a non-negative integer.",
            )
        )
    if len(candidates) > max_actions:
        block_reasons.append(
            block_reason(
                "too_many_real_candidate_actions",
                "Real candidate action count exceeds max_real_actions_per_run.",
                candidate_count=len(candidates),
                max_real_actions_per_run=max_actions,
            )
        )

    allowed_skills = set(_list_of_strings(config.get("allowed_real_skills")))
    blocked_skills = set(_list_of_strings(config.get("blocked_real_skills")))
    for candidate in candidates:
        skill = str(candidate.get("skill") or "")
        if skill not in allowed_skills:
            block_reasons.append(
                block_reason(
                    "real_skill_not_allowed",
                    "Real candidate skill is not in allowed_real_skills.",
                    action_id=str(candidate.get("action_id") or ""),
                    skill=skill,
                )
            )
        if skill in blocked_skills:
            block_reasons.append(
                block_reason(
                    "real_skill_blocked",
                    "Real candidate skill is in blocked_real_skills.",
                    action_id=str(candidate.get("action_id") or ""),
                    skill=skill,
                )
            )

    observed_skills = _action_skills(scheduler_run.get("executed_actions")) + [
        (str(candidate.get("skill") or ""), str(candidate.get("action_id") or ""))
        for candidate in candidates
    ]
    for skill, action_id in observed_skills:
        if skill in MVP_BLOCKED_REAL_SKILLS:
            block_reasons.append(
                block_reason(
                    "mvp_real_skill_blocked",
                    "This skill is blocked for real execution in the MVP.",
                    action_id=action_id,
                    skill=skill,
                )
            )

    real_execution_allowed = not block_reasons
    guard = new_execution_safety_guard(
        config,
        execution_gate,
        scheduler_run,
        action_executor_preview,
        kvm_calibration,
        kvm_calibration_report,
        real_execution_allowed,
        block_reasons,
        candidates,
        checks,
    )
    report = validate_execution_safety_guard(guard)
    report.update(
        {
            "execution_safety_guard_path": str(safety_store.EXECUTION_SAFETY_GUARD_PATH),
            "created_at": utc_now_iso(),
        }
    )
    return guard, report


def run(
    source: str = "auto",
    runtime_dir: str | Path | None = None,
    config_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _ = source
    (
        config,
        execution_gate,
        scheduler_run,
        action_executor_preview,
        kvm_calibration,
        kvm_calibration_report,
    ) = safety_store.load_inputs(runtime_dir, config_path)
    guard, report = evaluate_execution_safety_guard(
        config,
        execution_gate,
        scheduler_run,
        action_executor_preview,
        kvm_calibration,
        kvm_calibration_report,
    )
    if runtime_dir is None:
        guard_path = safety_store.EXECUTION_SAFETY_GUARD_PATH
        report_path = safety_store.EXECUTION_SAFETY_GUARD_REPORT_PATH
    else:
        guard_path, report_path = safety_store.paths_for_runtime(runtime_dir)
    report["execution_safety_guard_path"] = str(guard_path)
    safety_store.save_guard(guard, guard_path)
    safety_store.save_report(report, report_path)
    return guard, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate real execution safety eligibility.")
    parser.add_argument("--source", choices=["auto"], default="auto")
    args = parser.parse_args(argv)
    guard, report = run(args.source)
    print(
        "Saved runtime_state/latest_execution_safety_guard.json "
        f"(status={guard.get('status')}, "
        f"real_execution_allowed={guard.get('real_execution_allowed')})."
    )
    print(
        "Saved runtime_state/latest_execution_safety_guard_report.json "
        f"(validation_passed={report.get('validation_passed')})."
    )


if __name__ == "__main__":
    main()
