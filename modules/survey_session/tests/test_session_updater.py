from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.survey_session import session_updater


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_paths(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    monkeypatch.setattr(session_updater, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(session_updater, "SESSION_PATH", runtime / "latest_survey_session.json")
    monkeypatch.setattr(session_updater, "DECISION_PATH", runtime / "latest_answer_decision.json")
    monkeypatch.setattr(
        session_updater,
        "ANSWER_REPORT_PATH",
        runtime / "latest_answer_engine_report.json",
    )
    monkeypatch.setattr(
        session_updater,
        "SESSION_UPDATE_REPORT_PATH",
        runtime / "latest_session_update_report.json",
    )


def _base_session() -> dict:
    return {
        "session_id": "session_1",
        "task_id": "task1",
        "pages": [
            {
                "page_index": 1,
                "source_parse_path": "runtime_state/latest_orchestrated_parse.json",
                "page_type": "questionnaire",
                "questions": [{"question_id": "q1", "question_type": "multiple_choice"}],
                "answer_decisions": [],
                "status": "decision_pending",
            }
        ],
        "current_page_index": 1,
        "created_at": "2026-05-04T00:00:00+00:00",
        "updated_at": "2026-05-04T00:00:00+00:00",
    }


def test_session_status_updates_from_pending_to_human_review_required(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "runtime_state" / "latest_survey_session.json", _base_session())
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_decision.json",
        {
            "decision_id": "decision_1",
            "task_id": "task1",
            "source_parse": "runtime_state/latest_orchestrated_parse.json",
            "session_id": "session_1",
            "question_decisions": [
                {
                    "question_id": "q1",
                    "question_type": "multiple_choice",
                    "recommended_option_ids": [],
                    "recommended_text_answer": "",
                    "confidence": 0.0,
                    "requires_human_review": True,
                    "human_review_reason": "Needs profile evidence.",
                    "warnings": [],
                }
            ],
            "overall_confidence": 0.0,
            "requires_human_review": True,
            "warnings": [],
        },
    )
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_engine_report.json",
        {"validation_passed": True, "issues": [], "warnings": [], "requires_human_review": True},
    )

    session, report = session_updater.update_session_from_answer_outputs()

    page = session["pages"][0]
    assert page["status"] == "human_review_required"
    assert page["answer_decisions"][0]["decision_id"] == "decision_1"
    assert page["questions"][0]["answer_decision"]["requires_human_review"] is True
    assert report["page_status"] == "human_review_required"
    assert (tmp_path / "runtime_state" / "latest_session_update_report.json").exists()


def test_session_updater_adds_expected_linked_artifacts(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    session = _base_session()
    _write_json(tmp_path / "runtime_state" / "latest_survey_session.json", session)
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_decision.json",
        {
            "decision_id": "decision_1",
            "source_parse": "runtime_state/latest_orchestrated_parse.json",
            "session_id": "session_1",
            "question_decisions": [],
            "requires_human_review": False,
        },
    )
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_engine_report.json",
        {"validation_passed": True, "issues": [], "warnings": [], "requires_human_review": False},
    )

    updated, _report = session_updater.update_session_from_answer_outputs()

    linked = updated["pages"][0]["linked_artifacts"]
    assert linked["orchestrated_parse"].endswith("latest_orchestrated_parse.json")
    assert linked["answer_decision"].endswith("latest_answer_decision.json")
    assert linked["answer_engine_report"].endswith("latest_answer_engine_report.json")
    assert linked["action_plan"].endswith("latest_action_plan.json")
    assert linked["resolved_action_plan"].endswith("latest_resolved_action_plan.json")


def test_generated_session_update_files_parse_with_json_tool(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "runtime_state" / "latest_survey_session.json", _base_session())
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_decision.json",
        {
            "decision_id": "decision_1",
            "task_id": "task1",
            "source_parse": "runtime_state/latest_orchestrated_parse.json",
            "session_id": "session_1",
            "question_decisions": [
                {
                    "question_id": "q1",
                    "question_type": "multiple_choice",
                    "recommended_option_ids": [],
                    "recommended_text_answer": "",
                    "confidence": 0.0,
                    "requires_human_review": True,
                    "human_review_reason": "Needs profile evidence.",
                    "warnings": [],
                }
            ],
            "overall_confidence": 0.0,
            "requires_human_review": True,
            "warnings": [],
        },
    )
    _write_json(
        tmp_path / "runtime_state" / "latest_answer_engine_report.json",
        {"validation_passed": True, "issues": [], "warnings": [], "requires_human_review": True},
    )

    session_updater.update_session_from_answer_outputs()
    session_path = tmp_path / "runtime_state" / "latest_survey_session.json"
    report_path = tmp_path / "runtime_state" / "latest_session_update_report.json"

    assert not session_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not report_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(session_path)],
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
