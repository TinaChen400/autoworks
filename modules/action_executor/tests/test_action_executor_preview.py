from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.action_executor.preview_adapter import build_action_executor_preview, run_preview


def _write_json(path: Path, payload: dict, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding=encoding)


def _action(action_id: str = "a1", include_click_point: bool = True) -> dict:
    target = {
        "question_id": "q1",
        "option_id": "o1",
        "option_text": "Retail Central",
    }
    if include_click_point:
        target["click_point_screen"] = {"x": 160, "y": 270}
    return {
        "action_id": action_id,
        "skill": "click_option",
        "status": "success",
        "dry_run": True,
        "target": target,
        "params": {},
        "composite_skill": "select_single_choice_option",
        "atomic_steps": [
            {
                "action_id": action_id,
                "skill": "move_mouse",
                "status": "success",
                "dry_run": True,
                "target": target,
                "params": {},
            },
            {
                "action_id": action_id,
                "skill": "left_click",
                "status": "success",
                "dry_run": True,
                "target": target,
                "params": {},
            },
            {
                "action_id": action_id,
                "skill": "wait",
                "status": "success",
                "dry_run": True,
                "target": {},
                "params": {"duration_ms": 100},
            },
        ],
    }


def _gate(execution_allowed: bool = True) -> dict:
    return {
        "execution_gate_id": "execution_gate_1",
        "task_id": "task1",
        "session_id": "session_1",
        "source_resolved_action_plan_id": "resolved_action_plan_1",
        "execution_allowed": execution_allowed,
        "status": "allowed" if execution_allowed else "blocked",
        "block_reasons": []
        if execution_allowed
        else [{"code": "human_review_required", "message": "Needs review."}],
        "executable_actions": [],
    }


def _scheduler_run(status: str = "completed", actions: list[dict] | None = None) -> dict:
    return {
        "scheduler_run_id": "scheduler_run_1",
        "task_id": "task1",
        "session_id": "session_1",
        "source_execution_gate_id": "execution_gate_1",
        "source_resolved_action_plan_id": "resolved_action_plan_1",
        "status": status,
        "dry_run": True,
        "execution_allowed": True,
        "executed_actions": actions if actions is not None else [_action()],
        "skipped_actions": [],
        "failures": [],
    }


def _resolved_plan(actions: list[dict] | None = None) -> dict:
    return {
        "resolved_action_plan_id": "resolved_action_plan_1",
        "task_id": "task1",
        "session_id": "session_1",
        "status": "ready",
        "actions": actions if actions is not None else [_action()],
        "warnings": [],
    }


def test_blocked_gate_produces_blocked_preview() -> None:
    preview, report = build_action_executor_preview(
        _gate(False),
        _scheduler_run("blocked", []),
        _resolved_plan(),
    )

    assert report["validation_passed"] is True
    assert preview["status"] == "blocked"
    assert preview["real_execution"] is False
    assert preview["preview_records"] == []
    assert preview["block_reasons"][0]["code"] == "human_review_required"


def test_allowed_click_option_produces_preview_record() -> None:
    preview, report = build_action_executor_preview(
        _gate(True),
        _scheduler_run("completed", [_action()]),
        _resolved_plan(),
    )

    assert report["validation_passed"] is True
    assert preview["status"] == "completed"
    assert [record["record_type"] for record in preview["preview_records"]] == [
        "action",
        "atomic_step",
        "atomic_step",
    ]
    record = preview["preview_records"][0]
    assert record["action_id"] == "a1"
    assert record["skill"] == "click_option"
    assert record["option_id"] == "o1"
    assert record["option_text"] == "Retail Central"
    assert record["click_point_screen"] == {"x": 160, "y": 270}
    assert record["real_execution"] is False


def test_missing_click_point_screen_fails_safely() -> None:
    action = _action(include_click_point=False)

    preview, report = build_action_executor_preview(
        _gate(True),
        _scheduler_run("completed", [action]),
        _resolved_plan([action]),
    )

    assert report["validation_passed"] is True
    assert preview["status"] == "failed"
    assert preview["preview_records"] == []
    assert preview["failures"][0]["code"] == "missing_click_point_screen"


def test_scheduler_run_not_completed_blocks_preview() -> None:
    preview, report = build_action_executor_preview(
        _gate(True),
        _scheduler_run("partial", [_action()]),
        _resolved_plan(),
    )

    assert report["validation_passed"] is True
    assert preview["status"] == "blocked"
    assert preview["preview_records"] == []
    assert preview["block_reasons"][0]["code"] == "scheduler_run_not_completed"


def test_output_json_has_no_utf8_bom(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True), encoding="utf-8-sig")
    _write_json(runtime / "latest_scheduler_run.json", _scheduler_run())
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan())

    run_preview("auto", runtime)
    preview_path = runtime / "latest_action_executor_preview.json"
    report_path = runtime / "latest_action_executor_report.json"

    assert not preview_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not report_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(preview_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(report_path)],
        check=True,
        capture_output=True,
        text=True,
    )
