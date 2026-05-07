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
        "REVIEWED_DECISION_PATH",
        runtime / "latest_reviewed_answer_decision.json",
    )
    monkeypatch.setattr(
        action_plan_store,
        "ANSWER_REPORT_PATH",
        runtime / "latest_answer_engine_report.json",
    )
    monkeypatch.setattr(
        action_plan_store,
        "HUMAN_REVIEW_REPORT_PATH",
        runtime / "latest_human_review_report.json",
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


def _two_question_session() -> dict:
    session = _session("single_choice")
    question = session["pages"][0]["questions"][0]
    question["question_id"] = "q1"
    question["answer_options"] = [
        {"option_id": "q1_a1", "text": "Yes"},
        {"option_id": "q1_a2", "text": "No"},
    ]
    second = json.loads(json.dumps(question))
    second["question_id"] = "q2"
    second["answer_options"] = [
        {"option_id": "q2_a1", "text": "Yes"},
        {"option_id": "q2_a2", "text": "No"},
    ]
    session["pages"][0]["questions"] = [question, second]
    return session


def _two_question_raw_decision() -> dict:
    return {
        "decision_id": "decision_raw",
        "task_id": "task1",
        "source_parse": "runtime_state/latest_orchestrated_parse.json",
        "session_id": "session_1",
        "question_decisions": [
            {
                "question_id": "q1",
                "question_type": "single_choice",
                "recommended_option_ids": [],
                "recommended_text_answer": "",
                "confidence": 0.0,
                "requires_human_review": True,
                "human_review_reason": "Single choice requires exactly one clear evidence-supported option.",
                "warnings": [],
            },
            {
                "question_id": "q2",
                "question_type": "single_choice",
                "recommended_option_ids": [],
                "recommended_text_answer": "",
                "confidence": 0.0,
                "requires_human_review": True,
                "human_review_reason": "Single choice requires exactly one clear evidence-supported option.",
                "warnings": [],
            },
        ],
        "overall_confidence": 0.0,
        "requires_human_review": True,
        "warnings": [],
    }


def _reviewed_decision(source_decision_id: str = "decision_raw") -> dict:
    decision = _two_question_raw_decision()
    decision["requires_human_review"] = False
    decision["overall_confidence"] = 1.0
    decision["source_decision_id"] = source_decision_id
    decision["approval_source"] = "manual_review"
    decision["question_decisions"][0].update(
        {
            "recommended_option_ids": ["q1_a2"],
            "confidence": 1.0,
            "requires_human_review": False,
            "human_review_reason": "",
            "approval_source": "manual_review",
        }
    )
    decision["question_decisions"][1].update(
        {
            "recommended_option_ids": ["q2_a2"],
            "confidence": 1.0,
            "requires_human_review": False,
            "human_review_reason": "",
            "approval_source": "manual_review",
        }
    )
    return decision


def _answer_report(requires_human_review: bool) -> dict:
    return {
        "validation_passed": True,
        "issues": [],
        "warnings": [],
        "requires_human_review": requires_human_review,
    }


def _human_review_report(requires_human_review: bool = False) -> dict:
    return {
        "validation_passed": True,
        "approved_question_ids": ["q1", "q2"],
        "unresolved_question_ids": [],
        "requires_human_review": requires_human_review,
        "issues": [],
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


def test_valid_reviewed_decision_is_preferred_over_raw_decision(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_survey_session.json", _two_question_session())
    _write_json(runtime / "latest_answer_decision.json", _two_question_raw_decision())
    _write_json(runtime / "latest_answer_engine_report.json", _answer_report(True))
    _write_json(runtime / "latest_reviewed_answer_decision.json", _reviewed_decision())
    _write_json(runtime / "latest_human_review_report.json", _human_review_report(False))

    plan, report = action_plan_builder.build_action_plan("auto")

    assert plan["human_review_applied"] is True
    assert plan["source_decision_type"] == "reviewed_answer_decision"
    assert plan["source_decision_path"] == "runtime_state/latest_reviewed_answer_decision.json"
    assert plan["source_raw_decision_id"] == "decision_raw"
    assert report["human_review_applied"] is True
    assert report["source_decision_type"] == "reviewed_answer_decision"


def test_reviewed_single_choice_no_answers_generate_executable_actions(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_survey_session.json", _two_question_session())
    _write_json(runtime / "latest_answer_decision.json", _two_question_raw_decision())
    _write_json(runtime / "latest_answer_engine_report.json", _answer_report(True))
    _write_json(runtime / "latest_reviewed_answer_decision.json", _reviewed_decision())
    _write_json(runtime / "latest_human_review_report.json", _human_review_report(False))

    plan, report = action_plan_builder.build_action_plan("auto")

    assert plan["status"] == "ready"
    assert [item["skill"] for item in plan["actions"]] == ["click_option", "click_option"]
    assert [item["target"]["option_id"] for item in plan["actions"]] == ["q1_a2", "q2_a2"]
    assert [item["target"]["option_text"] for item in plan["actions"]] == ["No", "No"]
    assert report["request_human_review_count"] == 0
    assert report["executable_action_count"] == 2


def test_answer_report_review_flag_does_not_override_valid_reviewed_decision(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_survey_session.json", _two_question_session())
    _write_json(runtime / "latest_answer_decision.json", _two_question_raw_decision())
    _write_json(runtime / "latest_answer_engine_report.json", _answer_report(True))
    _write_json(runtime / "latest_reviewed_answer_decision.json", _reviewed_decision())
    _write_json(runtime / "latest_human_review_report.json", _human_review_report(False))

    plan, report = action_plan_builder.build_action_plan("auto")

    assert plan["status"] == "ready"
    assert not any(item["skill"] == "request_human_review" for item in plan["actions"])
    assert report["decision_requires_human_review"] is False


def test_mismatched_reviewed_source_decision_id_is_ignored(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_survey_session.json", _two_question_session())
    _write_json(runtime / "latest_answer_decision.json", _two_question_raw_decision())
    _write_json(runtime / "latest_answer_engine_report.json", _answer_report(True))
    _write_json(runtime / "latest_reviewed_answer_decision.json", _reviewed_decision("other_decision"))
    _write_json(runtime / "latest_human_review_report.json", _human_review_report(False))

    plan, report = action_plan_builder.build_action_plan("auto")

    assert plan["human_review_applied"] is False
    assert plan["source_decision_type"] == "answer_decision"
    assert plan["status"] == "human_review_required"
    assert [item["skill"] for item in plan["actions"]] == ["request_human_review", "request_human_review"]
    assert report["human_review_applied"] is False


def test_missing_human_review_report_falls_back_to_raw_decision(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_survey_session.json", _two_question_session())
    _write_json(runtime / "latest_answer_decision.json", _two_question_raw_decision())
    _write_json(runtime / "latest_answer_engine_report.json", _answer_report(True))
    _write_json(runtime / "latest_reviewed_answer_decision.json", _reviewed_decision())

    plan, report = action_plan_builder.build_action_plan("auto")

    assert plan["human_review_applied"] is False
    assert plan["status"] == "human_review_required"
    assert report["source_decision_type"] == "answer_decision"


def test_raw_decision_requiring_review_still_generates_request_human_review(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_survey_session.json", _two_question_session())
    _write_json(runtime / "latest_answer_decision.json", _two_question_raw_decision())
    _write_json(runtime / "latest_answer_engine_report.json", _answer_report(True))

    plan, report = action_plan_builder.build_action_plan("auto")

    assert plan["status"] == "human_review_required"
    assert [item["skill"] for item in plan["actions"]] == ["request_human_review", "request_human_review"]
    assert report["request_human_review_count"] == 2
    assert report["executable_action_count"] == 0
