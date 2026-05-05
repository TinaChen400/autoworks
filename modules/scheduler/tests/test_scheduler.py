from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.scheduler import scheduler_store
from modules.scheduler.scheduler import run, run_scheduler


def _write_json(path: Path, payload: dict, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding=encoding)


def _patch_paths(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    monkeypatch.setattr(scheduler_store, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(
        scheduler_store,
        "EXECUTION_GATE_PATH",
        runtime / "latest_execution_gate.json",
    )
    monkeypatch.setattr(
        scheduler_store,
        "RESOLVED_ACTION_PLAN_PATH",
        runtime / "latest_resolved_action_plan.json",
    )
    monkeypatch.setattr(
        scheduler_store,
        "SCHEDULER_RUN_PATH",
        runtime / "latest_scheduler_run.json",
    )
    monkeypatch.setattr(
        scheduler_store,
        "SCHEDULER_REPORT_PATH",
        runtime / "latest_scheduler_report.json",
    )


def _action(action_id: str = "a1", skill: str = "click_option") -> dict:
    return {
        "action_id": action_id,
        "skill": skill,
        "target": {
            "question_id": "q1",
            "option_id": "o1",
            "click_point_screen": {"x": 100, "y": 200},
        },
        "params": {},
        "requires_review": False,
    }


def _gate(execution_allowed: bool = True, actions: list[dict] | None = None) -> dict:
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
        "executable_actions": actions if execution_allowed else [],
        "created_at": "2026-05-05T09:00:00+00:00",
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


def test_blocked_execution_gate_prevents_execution() -> None:
    action = _action()

    scheduler_run, report = run_scheduler(_gate(False), _resolved_plan([action]))

    assert report["validation_passed"] is True
    assert scheduler_run["status"] == "blocked"
    assert scheduler_run["execution_allowed"] is False
    assert scheduler_run["executed_actions"] == []
    assert scheduler_run["skipped_actions"][0]["action_id"] == "a1"


def test_valid_executable_click_option_runs_dry_run_click_skill() -> None:
    action = _action("a1", "click_option")

    scheduler_run, report = run_scheduler(_gate(True, [action]), _resolved_plan([action]))

    assert report["validation_passed"] is True
    assert scheduler_run["status"] == "completed"
    assert scheduler_run["executed_actions"][0]["action_id"] == "a1"
    assert scheduler_run["executed_actions"][0]["skill"] == "click_option"
    assert scheduler_run["executed_actions"][0]["dry_run"] is True
    assert (
        scheduler_run["executed_actions"][0]["composite_skill"]
        == "select_single_choice_option"
    )
    atomic_steps = scheduler_run["executed_actions"][0]["atomic_steps"]
    assert [step["skill"] for step in atomic_steps] == [
        "move_mouse",
        "left_click",
        "wait",
        "verify_option_selected",
    ]


def test_unknown_skill_produces_failure_without_crashing() -> None:
    action = _action("a1", "missing_skill")

    scheduler_run, report = run_scheduler(_gate(True, [action]), _resolved_plan([action]))

    assert report["validation_passed"] is True
    assert scheduler_run["status"] == "failed"
    assert scheduler_run["failures"][0]["code"] == "unknown_skill"
    assert scheduler_run["failures"][0]["action_id"] == "a1"


def test_actions_execute_in_order() -> None:
    actions = [
        _action("a1", "click_option"),
        _action("a2", "type_text"),
        _action("a3", "click_next"),
    ]
    actions[1]["params"] = {"text": "hello"}

    scheduler_run, _report = run_scheduler(_gate(True, actions), _resolved_plan(actions))

    assert [result["action_id"] for result in scheduler_run["executed_actions"]] == [
        "a1",
        "a2",
        "a3",
    ]


def test_dry_run_output_contains_no_real_os_interaction_fields() -> None:
    action = _action()

    scheduler_run, report = run_scheduler(_gate(True, [action]), _resolved_plan([action]))
    payload = json.dumps(scheduler_run)

    assert report["validation_passed"] is True
    assert "mouse_moved" not in payload
    assert "keyboard_used" not in payload
    assert "winapi" not in payload.lower()
    assert "window_handle" not in payload
    assert "hwnd" not in payload


def test_output_json_has_no_utf8_bom(tmp_path, monkeypatch) -> None:
    _patch_paths(monkeypatch, tmp_path)
    runtime = tmp_path / "runtime_state"
    action = _action()
    _write_json(
        runtime / "latest_execution_gate.json",
        _gate(True, [action]),
        encoding="utf-8-sig",
    )
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan([action]))

    run("auto")
    scheduler_run_path = runtime / "latest_scheduler_run.json"
    report_path = runtime / "latest_scheduler_report.json"

    assert not scheduler_run_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not report_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(scheduler_run_path)],
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
