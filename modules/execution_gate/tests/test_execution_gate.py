from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.execution_gate import gate_store
from modules.execution_gate.execution_gate import evaluate_execution_gate, run


def _write_json(path: Path, payload: dict, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding=encoding)


def _patch_paths(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    paths = {
        "RUNTIME_DIR": runtime,
        "RESOLVED_ACTION_PLAN_PATH": runtime / "latest_resolved_action_plan.json",
        "TARGET_RESOLVER_REPORT_PATH": runtime / "latest_target_resolver_report.json",
        "ACTION_PLAN_REPORT_PATH": runtime / "latest_action_plan_report.json",
        "ANSWER_ENGINE_REPORT_PATH": runtime / "latest_answer_engine_report.json",
        "SURVEY_SESSION_PATH": runtime / "latest_survey_session.json",
        "EXECUTION_GATE_PATH": runtime / "latest_execution_gate.json",
        "EXECUTION_GATE_REPORT_PATH": runtime / "latest_execution_gate_report.json",
    }
    for name, path in paths.items():
        monkeypatch.setattr(gate_store, name, path)


def _click_action(confidence: float = 0.8, include_click_point: bool = True) -> dict:
    target = {
        "question_id": "q1",
        "option_id": "o1",
        "option_text": "Retail Central",
        "control_element_id": "E1",
        "control_type": "radio_like",
        "click_point_norm": {"x": 0.25, "y": 0.5},
        "click_point_raw": {"x": 60, "y": 70},
        "resolver_confidence": confidence,
    }
    if include_click_point:
        target["click_point_screen"] = {"x": 160, "y": 270}
    return {
        "action_id": "a1",
        "skill": "click_option",
        "target": target,
        "params": {},
        "requires_review": False,
    }


def _resolved_plan(status: str = "ready", actions: list[dict] | None = None) -> dict:
    return {
        "action_plan_id": "action_plan_1",
        "resolved_action_plan_id": "resolved_action_plan_1",
        "task_id": "task1",
        "session_id": "session_1",
        "status": status,
        "actions": actions if actions is not None else [_click_action()],
        "warnings": [],
    }


def _target_report(validation_passed: bool = True) -> dict:
    return {
        "validation_passed": validation_passed,
        "issues": [],
        "warnings": [],
        "resolved_actions": 1,
    }


def _write_runtime_inputs(tmp_path: Path, plan: dict, target_report: dict) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(
        runtime / "latest_resolved_action_plan.json",
        plan,
        encoding="utf-8-sig",
    )
    _write_json(runtime / "latest_target_resolver_report.json", target_report)
    _write_json(runtime / "latest_action_plan_report.json", {"validation_passed": True})
    _write_json(runtime / "latest_answer_engine_report.json", {"validation_passed": True})
    _write_json(
        runtime / "latest_survey_session.json",
        {"session_id": "session_1", "task_id": "task1"},
    )


def test_human_review_required_blocks_execution() -> None:
    gate, report = evaluate_execution_gate(
        _resolved_plan(status="human_review_required"),
        _target_report(),
    )

    assert report["validation_passed"] is True
    assert gate["execution_allowed"] is False
    assert gate["status"] == "blocked"
    assert gate["executable_actions"] == []
    assert "human_review_required" in [reason["code"] for reason in gate["block_reasons"]]


def test_request_human_review_action_blocks_execution() -> None:
    action = {
        "action_id": "a1",
        "skill": "request_human_review",
        "target": {"question_id": "q1"},
        "params": {"reason": "Needs review."},
        "requires_review": True,
    }

    gate, _report = evaluate_execution_gate(_resolved_plan(actions=[action]), _target_report())

    assert gate["execution_allowed"] is False
    assert gate["executable_actions"] == []
    assert "request_human_review" in [reason["code"] for reason in gate["block_reasons"]]


def test_click_option_without_click_point_screen_blocks_execution() -> None:
    gate, _report = evaluate_execution_gate(
        _resolved_plan(actions=[_click_action(include_click_point=False)]),
        _target_report(),
    )

    assert gate["execution_allowed"] is False
    assert "missing_click_point_screen" in [reason["code"] for reason in gate["block_reasons"]]


def test_valid_resolved_click_option_allows_execution() -> None:
    action = _click_action(confidence=0.8)

    gate, report = evaluate_execution_gate(_resolved_plan(actions=[action]), _target_report())

    assert report["validation_passed"] is True
    assert gate["execution_allowed"] is True
    assert gate["status"] == "allowed"
    assert gate["block_reasons"] == []
    assert gate["executable_actions"] == [action]


def test_high_confidence_parsed_geometry_click_option_allows_execution() -> None:
    action = _click_action(confidence=0.85)
    action["target"]["resolver_source"] = "parsed_option_geometry"

    gate, report = evaluate_execution_gate(_resolved_plan(actions=[action]), _target_report())

    assert report["validation_passed"] is True
    assert gate["execution_allowed"] is True
    assert gate["executable_actions"] == [action]


def test_low_resolver_confidence_blocks_execution() -> None:
    gate, _report = evaluate_execution_gate(
        _resolved_plan(actions=[_click_action(confidence=0.49)]),
        _target_report(),
    )

    assert gate["execution_allowed"] is False
    assert "resolver_confidence_below_threshold" in [
        reason["code"] for reason in gate["block_reasons"]
    ]


def test_output_json_has_no_utf8_bom(tmp_path, monkeypatch) -> None:
    _patch_paths(monkeypatch, tmp_path)
    _write_runtime_inputs(tmp_path, _resolved_plan(), _target_report())

    run("auto")
    gate_path = tmp_path / "runtime_state" / "latest_execution_gate.json"
    report_path = tmp_path / "runtime_state" / "latest_execution_gate_report.json"

    assert not gate_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not report_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(gate_path)],
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


def test_invalid_resolver_report_blocks_execution_without_crashing() -> None:
    gate, report = evaluate_execution_gate(
        _resolved_plan(),
        _target_report(validation_passed=False),
    )

    assert report["validation_passed"] is True
    assert gate["execution_allowed"] is False
    assert gate["executable_actions"] == []
    assert "target_resolver_invalid" in [reason["code"] for reason in gate["block_reasons"]]
