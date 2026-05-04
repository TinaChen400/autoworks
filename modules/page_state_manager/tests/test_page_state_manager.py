from __future__ import annotations

import json
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


def test_session_manager_adds_current_page_to_latest_survey_session(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "runtime_state" / "latest_local_parse.json",
        {
            "parsed_page": {
                "task_id": "task1",
                "page": {"page_type": "questionnaire", "confidence": 1.0},
                "questions": [
                    {
                        "question_id": "q1",
                        "question_type": "multiple_choice",
                        "question_stem": {"text": "Question?"},
                        "instructions": [],
                        "confidence": 1.0,
                    }
                ],
            }
        },
    )
    session = session_manager.update_session()
    assert session["current_page_index"] == 1
    assert session["pages"][0]["questions"][0]["question_id"] == "q1"
    assert (tmp_path / "runtime_state" / "latest_survey_session.json").exists()


def test_consistency_checker_detects_conflicting_answers():
    memory = [{"fact_key": "has seller central", "value": "yes", "source": "prior", "confidence": 0.9}]
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
