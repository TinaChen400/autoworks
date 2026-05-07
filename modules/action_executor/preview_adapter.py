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


def _click_point_raw(action: dict[str, Any]) -> dict[str, Any] | None:
    click_point = _target(action).get("click_point_raw")
    if not isinstance(click_point, dict):
        return None
    if "x" not in click_point or "y" not in click_point:
        return None
    return {"x": click_point["x"], "y": click_point["y"]}


def _click_point_from_record(record: dict[str, Any]) -> tuple[int, int] | None:
    click_point = record.get("click_point_raw")
    if not isinstance(click_point, dict):
        return None
    try:
        return int(round(float(click_point["x"]))), int(round(float(click_point["y"])))
    except (KeyError, TypeError, ValueError):
        return None


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
        "question_id": target.get("question_id", ""),
        "option_id": target.get("option_id", ""),
        "option_text": target.get("option_text", ""),
        "click_point_screen": click_point,
        "click_point_raw": _click_point_raw(action),
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
        "question_id": source_target.get("question_id", ""),
        "option_id": source_target.get("option_id", ""),
        "option_text": source_target.get("option_text", ""),
        "step_index": step_index,
        "click_point_screen": click_point,
        "click_point_raw": _click_point_raw(step) or _click_point_raw(source_action),
        "real_execution": False,
    }, None


def _scheduler_block_reason(scheduler_run: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": "scheduler_run_not_completed",
        "message": "Action executor preview requires a completed scheduler dry run.",
        "scheduler_status": scheduler_run.get("status", ""),
    }


def _no_preview_reason() -> dict[str, Any]:
    return {
        "code": "no_executable_actions",
        "message": "No executable actions are available for preview.",
    }


def _action_summary(action: dict[str, Any]) -> dict[str, Any]:
    target = _target(action)
    return {
        "action_id": str(action.get("action_id") or ""),
        "skill": str(action.get("skill") or ""),
        "question_id": target.get("question_id", ""),
        "option_id": target.get("option_id", ""),
        "option_text": target.get("option_text", ""),
        "click_point_screen": _click_point_screen(action),
        "click_point_raw": _click_point_raw(action),
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
    scheduler_run: dict[str, Any] | None,
    resolved_action_plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    scheduler_run_used = scheduler_run is not None
    scheduler_payload = scheduler_run or {}
    source = "scheduler_run" if scheduler_run_used else "resolved_action_plan"

    if execution_gate.get("execution_allowed") is not True:
        block_reasons = execution_gate.get("block_reasons")
        preview = new_action_executor_preview(
            execution_gate,
            scheduler_payload,
            resolved_action_plan,
            "blocked",
            [],
            [],
            deepcopy(block_reasons if isinstance(block_reasons, list) else []),
        )
        _add_source_metadata(preview, source, scheduler_run_used, [])
        return preview, _report(preview)

    if scheduler_run_used and scheduler_payload.get("status") != "completed":
        preview = new_action_executor_preview(
            execution_gate,
            scheduler_payload,
            resolved_action_plan,
            "blocked",
            [],
            [],
            [_scheduler_block_reason(scheduler_payload)],
        )
        _add_source_metadata(preview, source, scheduler_run_used, [])
        return preview, _report(preview)

    preview_records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if scheduler_run_used:
        source_actions = scheduler_payload.get("executed_actions")
    else:
        source_actions = resolved_action_plan.get("actions")
    if not isinstance(source_actions, list):
        source_actions = []

    executable_actions = [
        action
        for action in source_actions
        if isinstance(action, dict) and action.get("skill") == "click_option"
    ]
    if not executable_actions:
        preview = new_action_executor_preview(
            execution_gate,
            scheduler_payload,
            resolved_action_plan,
            "blocked",
            [],
            [],
            [_no_preview_reason()],
        )
        _add_source_metadata(preview, source, scheduler_run_used, [])
        preview["no_preview_reason"] = "No executable actions are available for preview."
        return preview, _report(preview)

    for action in executable_actions:
        if not isinstance(action, dict):
            failures.append(
                executor_failure("invalid_action", "Executed action must be an object.")
            )
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
        scheduler_payload,
        resolved_action_plan,
        status,
        preview_records,
        failures,
        [],
    )
    _add_source_metadata(
        preview,
        source,
        scheduler_run_used,
        [_action_summary(action) for action in executable_actions],
    )
    return preview, _report(preview)


def _add_source_metadata(
    preview: dict[str, Any],
    source: str,
    scheduler_run_used: bool,
    actions: list[dict[str, Any]],
) -> None:
    preview["source"] = source
    preview["scheduler_run_used"] = scheduler_run_used
    preview["action_count"] = len(actions)
    preview["actions"] = actions
    preview["capture_path"] = str(preview_store.CAPTURE_PATH)


def _draw_click_preview_image(
    preview: dict[str, Any],
    capture_path: str | Path,
    click_preview_path: str | Path,
) -> tuple[bool, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    source = Path(capture_path)
    destination = Path(click_preview_path)
    if not source.exists():
        warnings.append({"type": "missing_capture", "message": "latest_capture.png missing"})
        return False, warnings

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        warnings.append(
            {
                "type": "click_preview_unavailable",
                "message": f"Pillow is not available: {exc}",
            }
        )
        return False, warnings

    try:
        image = Image.open(source).convert("RGB")
    except Exception as exc:
        warnings.append(
            {
                "type": "invalid_capture",
                "message": f"Unable to load latest_capture.png: {exc}",
            }
        )
        return False, warnings

    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    width, height = image.size
    marker_color = (255, 32, 32)
    text_fill = (255, 255, 255)
    text_background = (20, 20, 20)

    for record in preview.get("preview_records", []):
        if not isinstance(record, dict) or record.get("record_type") != "action":
            continue
        point = _click_point_from_record(record)
        if point is None:
            warnings.append(
                {
                    "type": "missing_click_point_raw",
                    "message": "Preview record is missing click_point_raw; marker was skipped.",
                    "action_id": record.get("action_id", ""),
                }
            )
            continue
        x, y = point
        if x < 0 or y < 0 or x >= width or y >= height:
            warnings.append(
                {
                    "type": "click_point_raw_out_of_bounds",
                    "message": "click_point_raw is outside latest_capture.png bounds; marker was skipped.",
                    "action_id": record.get("action_id", ""),
                    "click_point_raw": {"x": x, "y": y},
                }
            )
            continue

        radius = 10
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=marker_color, width=3)
        draw.line((x - radius - 5, y, x + radius + 5, y), fill=marker_color, width=2)
        draw.line((x, y - radius - 5, x, y + radius + 5), fill=marker_color, width=2)

        label = " ".join(
            str(value)
            for value in (
                record.get("action_id", ""),
                record.get("question_id", ""),
                record.get("option_id", ""),
                record.get("option_text", ""),
            )
            if value
        )
        if label:
            text_x = min(max(x + 14, 0), max(width - 1, 0))
            text_y = min(max(y - 14, 0), max(height - 1, 0))
            bbox = draw.textbbox((text_x, text_y), label, font=font)
            if bbox[2] >= width:
                shift = bbox[2] - width + 4
                text_x = max(0, text_x - shift)
                bbox = draw.textbbox((text_x, text_y), label, font=font)
            if bbox[3] >= height:
                shift = bbox[3] - height + 4
                text_y = max(0, text_y - shift)
                bbox = draw.textbbox((text_x, text_y), label, font=font)
            draw.rectangle(
                (bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2),
                fill=text_background,
            )
            draw.text((text_x, text_y), label, fill=text_fill, font=font)

    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
    return True, warnings


def _write_outputs(
    preview: dict[str, Any],
    report: dict[str, Any],
    preview_path: str | Path,
    report_path: str | Path,
    capture_path: str | Path,
    click_preview_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    generated, image_warnings = _draw_click_preview_image(
        preview,
        capture_path,
        click_preview_path,
    )
    preview["capture_path"] = str(capture_path)
    preview["click_preview_image_path"] = str(click_preview_path)
    preview["click_preview_image_generated"] = generated
    report["click_preview_image_path"] = str(click_preview_path)
    report["click_preview_image_generated"] = generated
    report["warnings"] = list(report.get("warnings", [])) + image_warnings
    preview_store.save_preview(preview, preview_path)
    preview_store.save_report(report, report_path)
    return preview, report


def _report(preview: dict[str, Any]) -> dict[str, Any]:
    report = validate_action_executor_preview(preview)
    report.update(
        {
            "ok": bool(report.get("validation_passed")) and preview.get("status") == "completed",
            "preview_allowed": preview.get("status") == "completed",
            "source": preview.get("source", ""),
            "scheduler_run_used": bool(preview.get("scheduler_run_used")),
            "action_count": preview.get("action_count", 0),
            "block_reasons": list(preview.get("block_reasons", [])),
            "no_preview_reason": preview.get("no_preview_reason", ""),
            "source_execution_gate_id": preview.get("source_execution_gate_id", ""),
            "source_scheduler_run_id": preview.get("source_scheduler_run_id", ""),
            "action_executor_preview_path": str(preview_store.ACTION_EXECUTOR_PREVIEW_PATH),
            "click_preview_image_path": str(preview_store.CLICK_PREVIEW_PATH),
            "click_preview_image_generated": False,
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
        capture_path = preview_store.CAPTURE_PATH
        click_preview_path = preview_store.CLICK_PREVIEW_PATH
    else:
        runtime = Path(runtime_dir)
        execution_gate = preview_store.load_json(runtime / "latest_execution_gate.json")
        scheduler_run = preview_store.load_optional_json(runtime / "latest_scheduler_run.json")
        resolved_action_plan = preview_store.load_json(runtime / "latest_resolved_action_plan.json")
        preview_path, report_path, capture_path, click_preview_path = preview_store.paths_for_runtime(runtime)

    preview, report = build_action_executor_preview(
        execution_gate,
        scheduler_run,
        resolved_action_plan,
    )
    report["action_executor_preview_path"] = str(preview_path)
    return _write_outputs(preview, report, preview_path, report_path, capture_path, click_preview_path)


def run_preview_from_payloads(
    execution_gate: dict[str, Any],
    scheduler_run: dict[str, Any] | None,
    resolved_action_plan: dict[str, Any],
    runtime_dir: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    preview_path, report_path, capture_path, click_preview_path = preview_store.paths_for_runtime(runtime_dir)
    preview, report = build_action_executor_preview(
        execution_gate,
        scheduler_run,
        resolved_action_plan,
    )
    report["action_executor_preview_path"] = str(preview_path)
    return _write_outputs(preview, report, preview_path, report_path, capture_path, click_preview_path)


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
