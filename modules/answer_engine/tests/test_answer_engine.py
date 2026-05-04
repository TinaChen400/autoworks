from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.answer_engine import answer_engine, input_loader, panel, user_profile_loader
from modules.answer_engine.answer_validator import validate_decision
from modules.answer_engine.decision_store import save_decision
from modules.answer_engine import decision_store
from modules.answer_engine.strategies import multiple_choice_strategy, text_input_strategy, unknown_strategy


def account_question() -> dict:
    return {
        "question_id": "q1",
        "question_type": "multiple_choice",
        "question_stem": {"text": "Which accounts do you have experience using?"},
        "instructions": [{"text": "Please select all that apply."}],
        "answer_options": [
            {"option_id": "o1", "text": "Retail Central", "click_point_norm": {"x": 0.1, "y": 0.1}, "bbox_norm": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"option_id": "o2", "text": "Amazon Seller", "click_point_norm": {"x": 0.2, "y": 0.2}, "bbox_norm": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"option_id": "o3", "text": "Seller Central", "click_point_norm": {"x": 0.3, "y": 0.3}, "bbox_norm": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"option_id": "o4", "text": "Vendor Central", "click_point_norm": {"x": 0.4, "y": 0.4}, "bbox_norm": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"option_id": "all", "text": "All of the above", "click_point_norm": {"x": 0.5, "y": 0.5}, "bbox_norm": {"x": 0, "y": 0, "width": 1, "height": 1}},
        ],
        "confidence": 1.0,
    }


def config() -> dict:
    return {"minimum_confidence_without_review": 0.85}


def test_multiple_choice_personal_without_user_profile_requires_human_review():
    decision = multiple_choice_strategy.decide(account_question(), "account_ownership", {}, None, config())
    assert decision["requires_human_review"] is True
    assert decision["recommended_option_ids"] == []


def test_explicit_amazon_seller_central_selects_amazon_seller_and_seller_central():
    profile = {"known_accounts_or_experience": ["Amazon Seller Central"]}
    decision = multiple_choice_strategy.decide(account_question(), "account_ownership", profile, None, config())
    assert set(decision["recommended_option_ids"]) == {"o2", "o3"}
    assert decision["requires_human_review"] is False


def test_all_of_the_above_is_not_selected_unless_all_options_supported():
    profile = {"known_accounts_or_experience": ["Amazon Seller Central", "Vendor Central"]}
    decision = multiple_choice_strategy.decide(account_question(), "account_ownership", profile, None, config())
    assert "all" not in decision["recommended_option_ids"]


def test_unknown_question_requires_human_review():
    question = {"question_id": "q1", "question_type": "unknown", "question_stem": {"text": ""}}
    decision = unknown_strategy.decide(question, "unknown", {}, None, config())
    assert decision["requires_human_review"] is True


def test_text_input_personal_question_without_evidence_requires_human_review():
    question = {"question_id": "q1", "question_type": "text_input", "question_stem": {"text": "What tools have you used?"}}
    decision = text_input_strategy.decide(question, "personal_experience", {}, None, config())
    assert decision["requires_human_review"] is True
    assert decision["recommended_text_answer"] == ""


def test_click_targets_copied_from_selected_options():
    profile = {"known_accounts_or_experience": ["Amazon Seller Central"]}
    decision = multiple_choice_strategy.decide(account_question(), "account_ownership", profile, None, config())
    target_ids = {target["option_id"] for target in decision["click_targets"]}
    assert target_ids == {"o2", "o3"}
    assert all("click_point_norm" in target for target in decision["click_targets"])


def test_answer_validator_flags_unsupported_personal_claim():
    question = account_question()
    decision = {
        "question_decisions": [
            {
                "question_id": "q1",
                "question_category": "account_ownership",
                "recommended_option_ids": ["o2"],
                "recommended_text_answer": "",
                "evidence": [],
                "confidence": 0.9,
                "click_targets": [{"option_id": "o2"}],
            }
        ],
        "requires_human_review": False,
    }
    report = validate_decision(decision, {"questions": [question], "page": {"confidence": 1.0}}, config())
    assert report["validation_passed"] is False
    assert report["issues"][0]["type"] == "unsupported_personal_claim"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_answer_engine_paths(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    config_dir = tmp_path / "config"
    monkeypatch.setattr(input_loader, "ROOT", tmp_path)
    monkeypatch.setattr(input_loader, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(
        input_loader,
        "SOURCE_PATHS",
        {
            "orchestrated": runtime / "latest_orchestrated_parse.json",
            "local": runtime / "latest_local_parse.json",
            "parsed": runtime / "latest_parsed_page.json",
        },
    )
    monkeypatch.setattr(user_profile_loader, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(decision_store, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(decision_store, "DECISION_PATH", runtime / "latest_answer_decision.json")
    monkeypatch.setattr(decision_store, "REPORT_PATH", runtime / "latest_answer_engine_report.json")


def test_answer_engine_loads_latest_local_parse_when_orchestrated_absent(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "config" / "answer_engine.json", {"minimum_confidence_without_review": 0.85, "allow_llm_answerer": False})
    _write_json(
        tmp_path / "runtime_state" / "latest_local_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [account_question()]}},
    )
    decision, _report = answer_engine.build_answer_decision("auto")
    assert decision["source_parse"].endswith("latest_local_parse.json")


def test_answer_engine_does_not_call_external_llm(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "config" / "answer_engine.json", {"minimum_confidence_without_review": 0.85, "allow_llm_answerer": False})
    _write_json(
        tmp_path / "runtime_state" / "latest_local_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [account_question()]}},
    )
    decision, _report = answer_engine.build_answer_decision("auto")
    assert decision["question_decisions"]
    assert input_loader.load_config()["allow_llm_answerer"] is False


def test_panel_can_load_without_clicking(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(tmp_path / "config" / "answer_engine.json", {"minimum_confidence_without_review": 0.85, "allow_llm_answerer": False})
    _write_json(
        tmp_path / "runtime_state" / "latest_local_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [account_question()]}},
    )
    output = panel.render_panel("auto")
    assert "Answer Engine Panel" in output
    assert "Recommended answer" in output


def test_decision_store_writes_json_tool_parseable_utf8_without_bom(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    decision_store.save_decision({"decision_id": "decision_1", "question_decisions": []})
    decision_store.save_report({"validation_passed": True, "issues": [], "warnings": []})
    decision_path = tmp_path / "runtime_state" / "latest_answer_decision.json"
    report_path = tmp_path / "runtime_state" / "latest_answer_engine_report.json"

    assert not decision_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not report_path.read_bytes().startswith(b"\xef\xbb\xbf")
    for path in (decision_path, report_path):
        subprocess.run(
            [sys.executable, "-m", "json.tool", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
