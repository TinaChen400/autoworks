from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.action_executor.preview_adapter import build_action_executor_preview, run_preview


def _write_json(path: Path, payload: dict, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding=encoding)


def _write_capture(path: Path, size: tuple[int, int] = (320, 320)) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path)


def _action(action_id: str = "a1", include_click_point: bool = True) -> dict:
    target = {
        "question_id": "q1",
        "option_id": "o1",
        "option_text": "Retail Central",
    }
    if include_click_point:
        target["click_point_screen"] = {"x": 160, "y": 270}
        target["click_point_raw"] = {"x": 60, "y": 70}
        target["click_candidates"] = [
            {
                "source": "primary",
                "click_point_screen": {"x": 160, "y": 270},
                "click_point_raw": {"x": 60, "y": 70},
                "is_primary": True,
            },
            {
                "source": "nearby_detected_control",
                "click_point_screen": {"x": 170, "y": 280},
                "click_point_raw": {"x": 70, "y": 80},
            },
        ]
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
    assert [candidate["source"] for candidate in record["click_candidates"]] == [
        "primary",
        "nearby_detected_control",
    ]
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


def test_preview_adapter_works_without_scheduler_run(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan([_action()]))
    _write_capture(runtime / "latest_capture.png")

    preview, report = run_preview("auto", runtime)

    assert preview["status"] == "completed"
    assert preview["source"] == "resolved_action_plan"
    assert preview["scheduler_run_used"] is False
    assert preview["action_count"] == 1
    assert report["ok"] is True
    assert report["preview_allowed"] is True
    assert (runtime / "latest_action_executor_preview.json").exists()
    assert (runtime / "latest_action_executor_report.json").exists()


def test_preview_adapter_uses_resolved_action_plan_fallback(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    first = _action("a1")
    second = _action("a2")
    second["target"]["question_id"] = "q2"
    second["target"]["option_id"] = "q2_a2"
    second["target"]["option_text"] = "No"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan([first, second]))
    _write_capture(runtime / "latest_capture.png")

    preview, _report = run_preview("auto", runtime)

    assert [item["action_id"] for item in preview["actions"]] == ["a1", "a2"]
    assert [item["option_id"] for item in preview["actions"]] == ["o1", "q2_a2"]
    assert preview["preview_records"][0]["click_point_raw"] == {"x": 60, "y": 70}


def test_preview_adapter_does_not_execute_real_actions_without_scheduler(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan([_action()]))
    _write_capture(runtime / "latest_capture.png")

    preview, report = run_preview("auto", runtime)

    assert preview["preview_mode"] is True
    assert preview["real_execution"] is False
    assert report["real_execution"] is False
    assert all(record["real_execution"] is False for record in preview["preview_records"])


def test_preview_adapter_writes_report_when_execution_gate_not_allowed(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(False))
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan([_action()]))
    _write_capture(runtime / "latest_capture.png")

    preview, report = run_preview("auto", runtime)

    assert preview["status"] == "blocked"
    assert report["ok"] is False
    assert report["preview_allowed"] is False
    assert report["block_reasons"][0]["code"] == "human_review_required"
    assert (runtime / "latest_action_executor_report.json").exists()


def test_preview_adapter_writes_no_preview_reason_without_executable_actions(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    non_click = _action()
    non_click["skill"] = "request_human_review"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan([non_click]))

    preview, report = run_preview("auto", runtime)

    assert preview["status"] == "blocked"
    assert preview["no_preview_reason"] == "No executable actions are available for preview."
    assert report["ok"] is False
    assert report["no_preview_reason"] == "No executable actions are available for preview."


def test_preview_adapter_generates_click_preview_image_when_capture_exists(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan([_action()]))
    _write_capture(runtime / "latest_capture.png")

    preview, report = run_preview("auto", runtime)

    assert preview["click_preview_image_generated"] is True
    assert report["click_preview_image_generated"] is True
    assert report["click_preview_image_path"] == str(runtime / "latest_click_preview.png")
    assert (runtime / "latest_click_preview.png").exists()


def test_preview_adapter_does_not_crash_when_capture_missing(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan([_action()]))

    preview, report = run_preview("auto", runtime)

    assert preview["status"] == "completed"
    assert preview["click_preview_image_generated"] is False
    assert report["click_preview_image_generated"] is False
    assert report["warnings"][0]["type"] == "missing_capture"
    assert (runtime / "latest_action_executor_preview.json").exists()
    assert (runtime / "latest_action_executor_report.json").exists()


def test_click_preview_markers_use_click_point_raw(tmp_path) -> None:
    from PIL import Image

    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan([_action()]))
    _write_capture(runtime / "latest_capture.png")

    run_preview("auto", runtime)
    image = Image.open(runtime / "latest_click_preview.png").convert("RGB")

    assert image.getpixel((60, 70)) == (255, 32, 32)
    assert image.getpixel((160, 270)) == (255, 255, 255)


def test_no_real_execution_occurs_during_image_preview(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan([_action()]))
    _write_capture(runtime / "latest_capture.png")

    preview, report = run_preview("auto", runtime)

    assert preview["real_execution"] is False
    assert report["real_execution"] is False
    assert all(record["real_execution"] is False for record in preview["preview_records"])
