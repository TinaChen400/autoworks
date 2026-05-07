from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.action_plan import action_plan_builder, action_plan_store
from modules.human_review import human_review_processor, review_store


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _patch_paths(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    monkeypatch.setattr(review_store, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(review_store, "DECISION_PATH", runtime / "latest_answer_decision.json")
    monkeypatch.setattr(review_store, "ORCHESTRATED_PARSE_PATH", runtime / "latest_orchestrated_parse.json")
    monkeypatch.setattr(review_store, "SESSION_PATH", runtime / "latest_survey_session.json")
    monkeypatch.setattr(review_store, "MANUAL_REVIEW_INPUT_PATH", runtime / "manual_review_input.json")
    monkeypatch.setattr(review_store, "REVIEWED_DECISION_PATH", runtime / "latest_reviewed_answer_decision.json")
    monkeypatch.setattr(review_store, "HUMAN_REVIEW_REPORT_PATH", runtime / "latest_human_review_report.json")

    monkeypatch.setattr(action_plan_store, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(action_plan_store, "SESSION_PATH", runtime / "latest_survey_session.json")
    monkeypatch.setattr(action_plan_store, "DECISION_PATH", runtime / "latest_answer_decision.json")
    monkeypatch.setattr(action_plan_store, "ANSWER_REPORT_PATH", runtime / "latest_answer_engine_report.json")
    monkeypatch.setattr(action_plan_store, "REVIEWED_DECISION_PATH", runtime / "latest_reviewed_answer_decision.json")
    monkeypatch.setattr(action_plan_store, "HUMAN_REVIEW_REPORT_PATH", runtime / "latest_human_review_report.json")
    monkeypatch.setattr(action_plan_store, "ACTION_PLAN_PATH", runtime / "latest_action_plan.json")
    monkeypatch.setattr(action_plan_store, "ACTION_PLAN_REPORT_PATH", runtime / "latest_action_plan_report.json")


def _question() -> dict:
    return {
        "question_id": "q1",
        "question_type": "multiple_choice",
        "question_stem": {"text": "Which account do you use?"},
        "answer_options": [
            {
                "option_id": "T20",
                "text": "Retail Central",
                "bbox_norm": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                "click_point_norm": {"x": 0.2, "y": 0.3},
            },
            {
                "option_id": "T21",
                "text": "Amazon Central",
                "bbox_norm": {"x": 0.4, "y": 0.5, "width": 0.3, "height": 0.4},
                "click_point_norm": {"x": 0.5, "y": 0.6},
            },
        ],
    }


def _parse() -> dict:
    return {
        "task_id": "tts01",
        "parsed_page": {
            "task_id": "tts01",
            "questions": [_question()],
        },
    }


def _session() -> dict:
    return {
        "session_id": "session_1",
        "task_id": "tts01",
        "pages": [
            {
                "page_index": 1,
                "source_parse_path": "runtime_state/latest_orchestrated_parse.json",
                "page_type": "questionnaire",
                "questions": [
                    {
                        "question_id": "q1",
                        "question_type": "multiple_choice",
                        "question_text": "Which account do you use?",
                    }
                ],
                "answer_decisions": [],
                "status": "human_review_required",
                "linked_artifacts": {},
            }
        ],
        "current_page_index": 1,
    }


def _decision() -> dict:
    return {
        "decision_id": "decision_1",
        "task_id": "tts01",
        "source_parse": "runtime_state/latest_orchestrated_parse.json",
        "session_id": "session_1",
        "question_decisions": [
            {
                "question_id": "q1",
                "question_type": "multiple_choice",
                "question_category": "account_ownership",
                "question_text": "Which account do you use?",
                "answer_strategy": "multiple_choice_strategy",
                "recommended_option_ids": [],
                "recommended_text_answer": "",
                "confidence": 0.0,
                "reason": "No supported answer found.",
                "evidence": [],
                "missing_information": ["explicit supporting personal evidence"],
                "requires_human_review": True,
                "human_review_reason": "Needs profile evidence.",
                "click_targets": [
                    {
                        "option_id": "T21",
                        "click_point_norm": {"x": 0.5, "y": 0.6},
                        "bbox_norm": {"x": 0.4, "y": 0.5, "width": 0.3, "height": 0.4},
                    }
                ],
                "warnings": [],
            }
        ],
        "overall_confidence": 0.0,
        "requires_human_review": True,
        "warnings": [],
    }


def _manual_input(option_ids: list[str]) -> dict:
    return {
        "source_decision_id": "decision_1",
        "session_id": "session_1",
        "task_id": "tts01",
        "approvals": [
            {
                "question_id": "q1",
                "approved_option_ids": option_ids,
                "approved_text_answer": "",
                "review_note": "User explicitly confirmed this answer.",
            }
        ],
    }


def _write_runtime(tmp_path: Path, option_ids: list[str]) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_answer_decision.json", _decision())
    _write_json(runtime / "latest_orchestrated_parse.json", _parse())
    _write_json(runtime / "latest_survey_session.json", _session())
    _write_json(runtime / "manual_review_input.json", _manual_input(option_ids))
    _write_json(
        runtime / "latest_answer_engine_report.json",
        {"validation_passed": True, "issues": [], "warnings": [], "requires_human_review": True},
    )


def test_valid_manual_approval_converts_human_review_required_to_decision_ready(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_runtime(tmp_path, ["T21"])

    reviewed, report = human_review_processor.process_manual_review("auto")
    session = _read_json(tmp_path / "runtime_state" / "latest_survey_session.json")

    assert report["validation_passed"] is True
    assert reviewed["requires_human_review"] is False
    assert reviewed["question_decisions"][0]["recommended_option_ids"] == ["T21"]
    assert reviewed["question_decisions"][0]["approval_source"] == "manual_review"
    assert reviewed["question_decisions"][0]["confidence"] == 1.0
    assert session["pages"][0]["status"] == "decision_ready"


def test_invalid_option_id_keeps_human_review_required_and_reports_issue(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_runtime(tmp_path, ["missing"])

    reviewed, report = human_review_processor.process_manual_review("auto")

    assert report["validation_passed"] is False
    assert reviewed["requires_human_review"] is True
    assert reviewed["question_decisions"][0]["recommended_option_ids"] == []
    assert "unknown_option_id" in [issue["type"] for issue in report["issues"]]


def test_reviewed_decision_produces_click_option_action(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_runtime(tmp_path, ["T21"])

    human_review_processor.process_manual_review("auto")
    plan, report = action_plan_builder.build_action_plan("auto")

    assert report["validation_passed"] is True
    assert plan["status"] == "ready"
    assert [action["skill"] for action in plan["actions"]] == ["click_option"]
    assert plan["actions"][0]["target"] == {
        "question_id": "q1",
        "option_id": "T21",
        "option_text": "Amazon Central",
    }


def test_no_coordinates_appear_in_reviewed_answer_decision_or_action_plan(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_runtime(tmp_path, ["T21"])

    human_review_processor.process_manual_review("auto")
    action_plan_builder.build_action_plan("auto")
    reviewed_text = (tmp_path / "runtime_state" / "latest_reviewed_answer_decision.json").read_text(encoding="utf-8")
    plan_text = (tmp_path / "runtime_state" / "latest_action_plan.json").read_text(encoding="utf-8")

    for text in (reviewed_text, plan_text):
        assert "click_point_norm" not in text
        assert "bbox_norm" not in text
        assert '"x"' not in text
        assert '"y"' not in text


def test_session_linked_artifacts_includes_reviewed_answer_decision(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_runtime(tmp_path, ["T21"])

    human_review_processor.process_manual_review("auto")
    session = _read_json(tmp_path / "runtime_state" / "latest_survey_session.json")

    assert (
        session["pages"][0]["linked_artifacts"]["reviewed_answer_decision"]
        == "runtime_state/latest_reviewed_answer_decision.json"
    )


def test_output_json_has_no_utf8_bom(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_runtime(tmp_path, ["T21"])

    human_review_processor.process_manual_review("auto")
    reviewed_path = tmp_path / "runtime_state" / "latest_reviewed_answer_decision.json"
    report_path = tmp_path / "runtime_state" / "latest_human_review_report.json"

    assert not reviewed_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not report_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run([sys.executable, "-m", "json.tool", str(reviewed_path)], check=True, capture_output=True, text=True)
    subprocess.run([sys.executable, "-m", "json.tool", str(report_path)], check=True, capture_output=True, text=True)

