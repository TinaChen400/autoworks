from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.action_plan import action_plan_builder, action_plan_store


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _patch_paths(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    monkeypatch.setattr(action_plan_store, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(action_plan_store, "SESSION_PATH", runtime / "latest_survey_session.json")
    monkeypatch.setattr(action_plan_store, "DECISION_PATH", runtime / "latest_answer_decision.json")
    monkeypatch.setattr(
        action_plan_store,
        "ANSWER_REPORT_PATH",
        runtime / "latest_answer_engine_report.json",
    )
    monkeypatch.setattr(action_plan_store, "ACTION_PLAN_PATH", runtime / "latest_action_plan.json")
    monkeypatch.setattr(
        action_plan_store,
        "ACTION_PLAN_REPORT_PATH",
        runtime / "latest_action_plan_report.json",
    )


def _session(question_type: str = "multiple_choice") -> dict:
    return {
        "session_id": "session_1",
        "task_id": "task1",
        "pages": [
            {
                "page_index": 1,
                "source_parse_path": "runtime_state/latest_orchestrated_parse.json",
                "page_type": "questionnaire",
                "questions": [
                    {
                        "question_id": "q1",
                        "question_type": question_type,
                        "answer_options": [
                            {
                                "option_id": "o1",
                                "text": "Retail Central",
                                "click_point_norm": {"x": 0.1, "y": 0.2},
                                "bbox_norm": {"x": 0, "y": 0, "width": 1, "height": 1},
                            },
                            {
                                "option_id": "o2",
                                "text": "Amazon Seller",
                                "click_point_norm": {"x": 0.2, "y": 0.3},
                                "bbox_norm": {"x": 0, "y": 0, "width": 1, "height": 1},
                            },
                        ],
                    }
                ],
                "answer_decisions": [],
                "status": "decision_pending",
            }
        ],
        "current_page_index": 1,
    }


def _session_without_options(question_type: str = "multiple_choice") -> dict:
    session = _session(question_type)
    session["pages"][0]["questions"][0].pop("answer_options")
    return session


def _source_parse() -> dict:
    return {"parsed_page": {"task_id": "task1", "questions": [_session()["pages"][0]["questions"][0]]}}


def _decision(requires_human_review: bool, option_ids: list[str]) -> dict:
    return {
        "decision_id": "decision_1",
        "task_id": "task1",
        "source_parse": "runtime_state/latest_orchestrated_parse.json",
        "session_id": "session_1",
        "question_decisions": [
            {
                "question_id": "q1",
                "question_type": "multiple_choice",
                "recommended_option_ids": option_ids,
                "recommended_text_answer": "",
                "confidence": 0.9,
                "requires_human_review": requires_human_review,
                "human_review_reason": "Needs profile evidence.",
                "click_targets": [
                    {
                        "option_id": "o1",
                        "click_point_norm": {"x": 0.1, "y": 0.2},
                        "bbox_norm": {"x": 0, "y": 0, "width": 1, "height": 1},
                    }
                ],
                "warnings": [],
            }
        ],
        "overall_confidence": 0.9,
        "requires_human_review": requires_human_review,
        "warnings": [],
    }


def test_human_review_required_generates_review_action_only(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "runtime_state" / "latest_survey_session.json", _session())
    _write_json(tmp_path / "runtime_state" / "latest_answer_decision.json", _decision(True, []))
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_engine_report.json",
        {"validation_passed": True, "issues": [], "warnings": [], "requires_human_review": True},
    )

    plan, report = action_plan_builder.build_action_plan("auto")

    assert report["validation_passed"] is True
    assert plan["status"] == "human_review_required"
    assert [item["skill"] for item in plan["actions"]] == ["request_human_review"]
    assert not any(item["skill"] == "click_option" for item in plan["actions"])
    assert plan["actions"][0]["params"]["available_options"] == [
        {"option_id": "o1", "option_text": "Retail Central"},
        {"option_id": "o2", "option_text": "Amazon Seller"},
    ]


def test_multiple_choice_recommendations_generate_click_option_actions(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "runtime_state" / "latest_survey_session.json", _session())
    _write_json(tmp_path / "runtime_state" / "latest_answer_decision.json", _decision(False, ["o1", "o2"]))
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_engine_report.json",
        {"validation_passed": True, "issues": [], "warnings": [], "requires_human_review": False},
    )

    plan, _report = action_plan_builder.build_action_plan("auto")

    assert plan["status"] == "ready"
    assert [item["skill"] for item in plan["actions"]] == ["click_option", "click_option"]
    assert [item["target"]["option_id"] for item in plan["actions"]] == ["o1", "o2"]
    assert plan["actions"][0]["target"]["option_text"] == "Retail Central"


def test_coordinates_are_never_written_to_latest_action_plan(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "runtime_state" / "latest_survey_session.json", _session())
    _write_json(tmp_path / "runtime_state" / "latest_answer_decision.json", _decision(False, ["o1"]))
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_engine_report.json",
        {"validation_passed": True, "issues": [], "warnings": [], "requires_human_review": False},
    )

    action_plan_builder.build_action_plan("auto")
    plan_text = (tmp_path / "runtime_state" / "latest_action_plan.json").read_text(encoding="utf-8")

    assert "click_point_norm" not in plan_text
    assert "bbox_norm" not in plan_text
    assert '"x"' not in plan_text
    assert '"y"' not in plan_text


def test_action_plan_path_is_written_into_session_linked_artifacts(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "runtime_state" / "latest_survey_session.json", _session())
    _write_json(tmp_path / "runtime_state" / "latest_answer_decision.json", _decision(False, ["o1"]))
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_engine_report.json",
        {"validation_passed": True, "issues": [], "warnings": [], "requires_human_review": False},
    )

    action_plan_builder.build_action_plan("auto")
    session = _read_json(tmp_path / "runtime_state" / "latest_survey_session.json")

    assert session["pages"][0]["linked_artifacts"]["action_plan"] == "runtime_state/latest_action_plan.json"


def test_review_action_available_options_are_loaded_from_source_parse(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "runtime_state" / "latest_survey_session.json", _session_without_options())
    _write_json(tmp_path / "runtime_state" / "latest_orchestrated_parse.json", _source_parse())
    _write_json(tmp_path / "runtime_state" / "latest_answer_decision.json", _decision(True, []))
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_engine_report.json",
        {"validation_passed": True, "issues": [], "warnings": [], "requires_human_review": True},
    )

    plan, _report = action_plan_builder.build_action_plan("auto")

    assert plan["actions"][0]["skill"] == "request_human_review"
    assert plan["actions"][0]["params"]["available_options"] == [
        {"option_id": "o1", "option_text": "Retail Central"},
        {"option_id": "o2", "option_text": "Amazon Seller"},
    ]


def test_generated_action_plan_and_session_parse_with_json_tool(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "runtime_state" / "latest_survey_session.json", _session())
    _write_json(tmp_path / "runtime_state" / "latest_answer_decision.json", _decision(False, ["o1"]))
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_engine_report.json",
        {"validation_passed": True, "issues": [], "warnings": [], "requires_human_review": False},
    )

    action_plan_builder.build_action_plan("auto")
    action_plan_path = tmp_path / "runtime_state" / "latest_action_plan.json"
    session_path = tmp_path / "runtime_state" / "latest_survey_session.json"

    assert not action_plan_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not session_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(action_plan_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(session_path)],
        check=True,
        capture_output=True,
        text=True,
    )
