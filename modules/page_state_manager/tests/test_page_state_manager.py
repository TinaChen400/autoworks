from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from modules.page_state_manager import input_loader, session_manager, session_store
from modules.page_state_manager.consistency_checker import detect_conflicting_answer
from modules.page_state_manager.schema import new_session


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_paths(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    monkeypatch.setattr(input_loader, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(
        input_loader,
        "PARSE_PATHS",
        [
            runtime / "latest_orchestrated_parse.json",
            runtime / "latest_local_parse.json",
            runtime / "latest_parsed_page.json",
        ],
    )
    monkeypatch.setattr(session_store, "SESSION_PATH", runtime / "latest_survey_session.json")
    monkeypatch.setattr(input_loader, "DEFAULT_PARSE_PATH", runtime / "latest_orchestrated_parse.json")
    monkeypatch.setattr(session_manager, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(session_manager, "REPORT_PATH", runtime / "latest_session_update_report.json")


def _write_parse(tmp_path: Path, question_text: str = "Question?") -> Path:
    parse_path = tmp_path / "runtime_state" / "latest_orchestrated_parse.json"
    _write_json(
        parse_path,
        {
            "parsed_page": {
                "task_id": "task1",
                "page": {"page_type": "questionnaire", "confidence": 1.0},
                "questions": [
                    {
                        "question_id": "q1",
                        "question_type": "multiple_choice",
                        "question_stem": {"text": question_text},
                        "instructions": [],
                        "confidence": 1.0,
                    }
                ],
            }
        },
    )
    return parse_path


def _module_env() -> dict[str, str]:
    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[3]
    env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_session_manager_cli_help_does_not_write_session_output(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "modules.page_state_manager.session_manager", "--help"],
        cwd=tmp_path,
        env=_module_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "usage:" in completed.stdout
    assert "--source" in completed.stdout
    assert not (tmp_path / "runtime_state" / "latest_survey_session.json").exists()
    assert not (tmp_path / "runtime_state" / "latest_session_update_report.json").exists()


def test_session_manager_cli_source_auto_reads_latest_orchestrated_parse(tmp_path):
    _write_parse(tmp_path, question_text="Auto source question?")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "modules.page_state_manager.session_manager",
            "--source",
            "auto",
        ],
        cwd=tmp_path,
        env=_module_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    session = json.loads(
        (tmp_path / "runtime_state" / "latest_survey_session.json").read_text(encoding="utf-8")
    )
    assert session["pages"][0]["questions"][0]["question_text"] == "auto source question?"


def test_session_manager_cli_valid_parse_writes_session_and_report(tmp_path):
    parse_path = _write_parse(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "modules.page_state_manager.session_manager",
            "--source",
            str(parse_path),
        ],
        cwd=tmp_path,
        env=_module_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    report_path = tmp_path / "runtime_state" / "latest_session_update_report.json"
    assert completed.returncode == 0
    assert (tmp_path / "runtime_state" / "latest_survey_session.json").exists()
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["source_parse"] == str(parse_path)
    assert report["page_count"] == 1
    assert report["question_count"] == 1
    assert report["visual_element_count"] == 0
    assert report["errors"] == []


def test_session_manager_cli_missing_parse_writes_failed_report_and_exits_nonzero(tmp_path):
    missing_path = tmp_path / "runtime_state" / "missing_parse.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "modules.page_state_manager.session_manager",
            "--source",
            str(missing_path),
        ],
        cwd=tmp_path,
        env=_module_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    report_path = tmp_path / "runtime_state" / "latest_session_update_report.json"
    assert completed.returncode != 0
    assert report_path.exists()
    assert not (tmp_path / "runtime_state" / "latest_survey_session.json").exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_parse"] == str(missing_path)
    assert report["errors"]


def test_session_manager_adds_current_page_to_latest_survey_session(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_parse(tmp_path)
    session = session_manager.update_session()
    assert session["current_page_index"] == 1
    assert session["pages"][0]["questions"][0]["question_id"] == "q1"
    assert (tmp_path / "runtime_state" / "latest_survey_session.json").exists()


def test_session_manager_rerun_same_parse_is_idempotent(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_parse(tmp_path)
    timestamps = iter(["2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00"])
    monkeypatch.setattr(session_manager, "utc_now_iso", lambda: next(timestamps))

    first = session_manager.update_session()
    second = session_manager.update_session()

    assert len(first["pages"]) == 1
    assert len(second["pages"]) == 1
    assert second["pages"][0]["page_index"] == first["pages"][0]["page_index"]
    assert first["updated_at"] == "2026-01-01T00:00:00+00:00"
    assert second["updated_at"] == "2026-01-01T00:00:01+00:00"


def test_session_manager_preserves_answer_decisions_on_idempotent_update(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    parse_path = _write_parse(tmp_path)
    session = new_session("task1")
    session["current_page_index"] = 1
    session["pages"] = [
        {
            "page_index": 1,
            "source_parse_path": str(parse_path),
            "page_type": "questionnaire",
            "questions": [
                {
                    "question_id": "q1",
                    "question_type": "multiple_choice",
                    "question_text": "question?",
                    "confidence": 1.0,
                    "answer_decision": {
                        "decision_id": "decision_1",
                        "recommended_option_ids": ["yes"],
                        "recommended_text_answer": "",
                        "requires_human_review": False,
                        "confidence": 0.9,
                    },
                }
            ],
            "answer_decisions": [{"decision_id": "decision_1"}],
            "status": "decision_ready",
            "linked_artifacts": {"answer_decision": "runtime_state/latest_answer_decision.json"},
        }
    ]
    _write_json(tmp_path / "runtime_state" / "latest_survey_session.json", session)

    updated = session_manager.update_session()

    page = updated["pages"][0]
    assert len(updated["pages"]) == 1
    assert page["answer_decisions"] == [{"decision_id": "decision_1"}]
    assert page["questions"][0]["answer_decision"]["decision_id"] == "decision_1"
    assert page["status"] == "decision_ready"
    assert page["linked_artifacts"] == {
        "answer_decision": "runtime_state/latest_answer_decision.json"
    }


def test_consistency_checker_detects_conflicting_answers():
    memory = [
        {"fact_key": "has seller central", "value": "yes", "source": "prior", "confidence": 0.9}
    ]
    conflicts = detect_conflicting_answer(memory, "has seller central", "no")
    assert conflicts
    assert conflicts[0]["previous_value"] == "yes"


def test_session_store_writes_json_tool_parseable_utf8_without_bom(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    session_store.save_session(new_session("task1"))
    session_path = tmp_path / "runtime_state" / "latest_survey_session.json"

    assert not session_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(session_path)],
        check=True,
        capture_output=True,
        text=True,
    )
