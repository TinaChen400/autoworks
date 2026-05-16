from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.answer_engine import answer_context_loader, answer_engine, input_loader, panel, user_profile_loader
from modules.answer_engine.answer_validator import validate_decision
from modules.answer_engine.decision_store import save_decision
from modules.answer_engine import decision_store
from modules.answer_engine import profile_llm_strategy
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


def test_answer_validator_rejects_option_id_not_on_current_page():
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "Compared to what already exists?"},
        "answer_options": [
            {"option_id": "T24", "text": "This is essentially the same as what already exists"},
            {"option_id": "T25", "text": "This would be slightly better than what already exists"},
        ],
    }
    decision = {
        "question_decisions": [
            {
                "question_id": "q1",
                "question_category": "preference",
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["T29"],
                "recommended_text_answer": "",
                "evidence": [],
                "basis": "current page judgement",
                "confidence": 0.9,
                "click_targets": [{"option_id": "T29"}],
            }
        ],
        "requires_human_review": False,
    }
    report = validate_decision(decision, {"questions": [question], "page": {"confidence": 1.0}}, config())
    assert report["validation_passed"] is False
    assert any(issue["type"] == "invalid_option_id" and issue["option_ids"] == ["T29"] for issue in report["issues"])
    assert report["requires_human_review"] is True


def test_answer_validator_accepts_current_page_option_id():
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "Compared to what already exists?"},
        "answer_options": [
            {"option_id": "T24", "text": "This is essentially the same as what already exists"},
            {"option_id": "T25", "text": "This would be slightly better than what already exists"},
        ],
    }
    decision = {
        "question_decisions": [
            {
                "question_id": "q1",
                "question_category": "preference",
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["T25"],
                "recommended_text_answer": "",
                "evidence": [],
                "basis": "current page judgement",
                "confidence": 0.9,
                "click_targets": [{"option_id": "T25"}],
            }
        ],
        "requires_human_review": False,
    }
    report = validate_decision(decision, {"questions": [question], "page": {"confidence": 1.0}}, config())
    assert report["validation_passed"] is True
    assert report["requires_human_review"] is False


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
    monkeypatch.setattr(answer_context_loader, "ANSWER_NOTES_PATH", tmp_path / "knowledge_base" / "answer_notes.json")


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


def test_profile_llm_single_choice_selects_existing_option(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(
        tmp_path / "config" / "user_profile.json",
        {"notes": ["I think the new broadband setup app idea is essentially the same as what already exists."]},
    )
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "Compared to what already exists?"},
        "answer_options": [
            {"option_id": "T27", "text": "What exists already is better than this"},
            {"option_id": "T28", "text": "This is essentially the same as what already exists"},
        ],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )

    def fake_call(**_kwargs):
        return json.dumps(
            {
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["T28"],
                "recommended_text_answer": "",
                "confidence": 0.9,
                "basis": "mainstream practical consumer persona",
                "reason": "Matches profile note.",
                "evidence": [
                    {
                        "source": "user_profile.notes",
                        "value": "same as what already exists",
                        "matched_text": "This is essentially the same as what already exists",
                    }
                ],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert qd["answer_strategy"] == "profile_llm_strategy"
    assert qd["answer_mode"] == "representative_persona"
    assert qd["recommended_option_ids"] == ["T28"]
    assert qd["requires_human_review"] is False
    assert report["validation_passed"] is True
    assert report["requires_human_review"] is False


def test_missing_answer_notes_file_does_not_break_profile_llm(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(tmp_path / "config" / "user_profile.json", {"notes": ["Use current page only."]})
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "Compared to what already exists?"},
        "answer_options": [
            {"option_id": "T24", "text": "This is essentially the same as what already exists"},
            {"option_id": "T25", "text": "This would be slightly better than what already exists"},
        ],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )

    def fake_call(**kwargs):
        assert '"external_reference_notes":[]' in kwargs["prompt"]
        return json.dumps(
            {
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["T25"],
                "recommended_text_answer": "",
                "confidence": 0.9,
                "basis": "current page representative judgement",
                "reason": "Selected from current options.",
                "evidence": [],
                "used_answer_notes": [],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert qd["recommended_option_ids"] == ["T25"]
    assert qd["used_answer_notes"] == []
    assert qd["answer_source"] == "profile_llm_profile_only"
    assert report["validation_passed"] is True


def test_matching_answer_notes_are_included_in_decision_evidence(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "knowledge_base" / "answer_notes.json",
        [
            {
                "id": "broadband_setup_balance",
                "tags": ["broadband", "setup", "virgin media"],
                "text": "Prefer a balanced answer about setup guidance and troubleshooting.",
            }
        ],
    )
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(tmp_path / "config" / "user_profile.json", {"notes": ["Use concise answers."]})
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "How useful is this Virgin Media broadband setup app?"},
        "answer_options": [
            {"option_id": "T24", "text": "It is not useful"},
            {"option_id": "T25", "text": "It is somewhat useful"},
        ],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )

    def fake_call(**kwargs):
        assert "broadband_setup_balance" in kwargs["prompt"]
        return json.dumps(
            {
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["T25"],
                "recommended_text_answer": "",
                "confidence": 0.9,
                "basis": "answer note plus representative persona",
                "reason": "The answer note supports a balanced usefulness answer.",
                "evidence": [],
                "used_answer_notes": ["broadband_setup_balance", "missing_note"],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert qd["used_answer_notes"] == ["broadband_setup_balance"]
    assert qd["answer_source"] == "profile_llm_with_answer_notes"
    assert {
        "source": "answer_notes",
        "id": "broadband_setup_balance",
        "value": "Prefer a balanced answer about setup guidance and troubleshooting.",
        "matched_text": "broadband_setup_balance",
        "match_type": "answer_note",
    } in qd["evidence"]
    assert report["validation_passed"] is True


def test_profile_llm_prompt_excludes_prior_session_memory(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(
        tmp_path / "config" / "user_profile.json",
        {"notes": ["Use the current page only."]},
    )
    _write_json(
        tmp_path / "runtime_state" / "latest_survey_session.json",
        {
            "session_id": "session_1",
            "current_page_index": 2,
            "consistency_memory": [
                {
                    "fact_key": "Compared to previous page",
                    "value": "T29",
                    "source": "old_decision",
                    "confidence": 1.0,
                }
            ],
        },
    )
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "Compared to what already exists?"},
        "answer_options": [
            {"option_id": "T24", "text": "This is essentially the same as what already exists"},
            {"option_id": "T25", "text": "This would be slightly better than what already exists"},
        ],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )

    def fake_call(**kwargs):
        assert "session_memory" not in kwargs["prompt"]
        assert "consistency_memory" not in kwargs["prompt"]
        assert "T29" not in kwargs["prompt"]
        return json.dumps(
            {
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["T25"],
                "recommended_text_answer": "",
                "confidence": 0.9,
                "basis": "current page representative judgement",
                "reason": "Selected from the current page options.",
                "evidence": [
                    {
                        "source": "user_profile.notes",
                        "value": "Use the current page only.",
                    }
                ],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert qd["recommended_option_ids"] == ["T25"]
    assert qd["requires_human_review"] is False
    assert report["requires_human_review"] is False


def test_profile_llm_rejects_non_current_option_references(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(tmp_path / "config" / "user_profile.json", {"notes": ["Answer from current page."]})
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "Compared to what already exists?"},
        "answer_options": [
            {"option_id": "T24", "text": "This is essentially the same as what already exists"},
            {"option_id": "T25", "text": "This would be slightly better than what already exists"},
        ],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )

    def fake_call(**_kwargs):
        return json.dumps(
            {
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["T25"],
                "recommended_text_answer": "",
                "confidence": 0.9,
                "basis": "current page judgement",
                "reason": "I remember T29 from before, so choose the closest current option.",
                "evidence": [
                    {
                        "source": "session_memory",
                        "value": "T29",
                        "matched_text": "T29",
                    }
                ],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert qd["recommended_option_ids"] == []
    assert qd["evidence"] == []
    assert qd["requires_human_review"] is True
    assert "non-current option IDs" in qd["warnings"][0]
    assert report["requires_human_review"] is True


def test_profile_llm_retries_when_reason_references_non_current_option_id(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(tmp_path / "config" / "user_profile.json", {"notes": ["Answer from current page."]})
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "Compared to what already exists?"},
        "answer_options": [
            {"option_id": "T24", "text": "This is essentially the same as what already exists"},
            {"option_id": "T25", "text": "This would be slightly better than what already exists"},
        ],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )
    prompts = []

    def fake_call(**kwargs):
        prompts.append(kwargs["prompt"])
        if len(prompts) == 1:
            return json.dumps(
                {
                    "answer_mode": "representative_persona",
                    "recommended_option_ids": ["T25"],
                    "recommended_text_answer": "",
                    "confidence": 0.9,
                    "basis": "current page judgement",
                    "reason": "The older T29 answer is closest, so choose T25.",
                    "evidence": [],
                    "used_answer_notes": [],
                    "requires_human_review": False,
                    "human_review_reason": "",
                }
            )
        assert "This is a retry" in kwargs["prompt"]
        assert "T29" in kwargs["prompt"]
        return json.dumps(
            {
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["T25"],
                "recommended_text_answer": "",
                "confidence": 0.9,
                "basis": "current page representative judgement",
                "reason": "Selected the balanced current-page option.",
                "evidence": [],
                "used_answer_notes": [],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert len(prompts) == 2
    assert qd["recommended_option_ids"] == ["T25"]
    assert qd["requires_human_review"] is False
    assert qd["warnings"] == []
    assert report["requires_human_review"] is False


def test_profile_llm_retry_still_referencing_old_option_requires_review(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(tmp_path / "config" / "user_profile.json", {"notes": ["Answer from current page."]})
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "Compared to what already exists?"},
        "answer_options": [
            {"option_id": "T24", "text": "This is essentially the same as what already exists"},
            {"option_id": "T25", "text": "This would be slightly better than what already exists"},
        ],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )
    calls = 0

    def fake_call(**_kwargs):
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["T25"],
                "recommended_text_answer": "",
                "confidence": 0.9,
                "basis": "T29 was selected before.",
                "reason": "Use T29 as the prior reference and choose the closest current option.",
                "evidence": [],
                "used_answer_notes": [],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert calls == 2
    assert qd["recommended_option_ids"] == []
    assert qd["requires_human_review"] is True
    assert qd["human_review_reason"] == "Profile LLM referenced non-current option IDs."
    assert "non-current option IDs" in qd["warnings"][0]
    assert report["requires_human_review"] is True


def test_profile_llm_does_not_retry_when_response_has_only_current_option_ids(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(tmp_path / "config" / "user_profile.json", {"notes": ["Answer from current page."]})
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "Compared to what already exists?"},
        "answer_options": [
            {"option_id": "T24", "text": "This is essentially the same as what already exists"},
            {"option_id": "T25", "text": "This would be slightly better than what already exists"},
        ],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )
    calls = 0

    def fake_call(**_kwargs):
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["T25"],
                "recommended_text_answer": "",
                "confidence": 0.9,
                "basis": "current page representative judgement",
                "reason": "Selected T25 from the current page options.",
                "evidence": [
                    {
                        "source": "user_profile.notes",
                        "value": "Answer from current page.",
                        "matched_text": "T25",
                    }
                ],
                "used_answer_notes": [],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert calls == 1
    assert qd["recommended_option_ids"] == ["T25"]
    assert qd["requires_human_review"] is False
    assert report["requires_human_review"] is False


def test_profile_llm_missing_profile_can_use_representative_persona(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [account_question()]}},
    )

    def fake_call(**_kwargs):
        return json.dumps(
            {
                "answer_mode": "representative_persona",
                "recommended_option_ids": ["o2"],
                "recommended_text_answer": "",
                "confidence": 0.9,
                "basis": "mainstream representative account/tool usage",
                "reason": "Selected a plausible mainstream option.",
                "evidence": [],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert qd["answer_strategy"] == "profile_llm_strategy"
    assert qd["answer_mode"] == "representative_persona"
    assert qd["requires_human_review"] is False
    assert report["requires_human_review"] is False


def test_profile_llm_text_input_generates_profile_backed_text(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(
        tmp_path / "config" / "user_profile.json",
        {"known_tools": ["Virgin Media broadband app"], "notes": ["I prefer concise survey answers."]},
    )
    question = {
        "question_id": "q1",
        "question_type": "text_input",
        "question_stem": {"text": "Please explain your answer in detail."},
        "answer_options": [],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )

    def fake_call(**_kwargs):
        return json.dumps(
            {
                "answer_mode": "representative_persona",
                "recommended_option_ids": [],
                "recommended_text_answer": "It feels too similar to existing setup support to be especially useful.",
                "confidence": 0.9,
                "basis": "mainstream practical consumer persona",
                "reason": "Generated from profile preference.",
                "evidence": [
                    {
                        "source": "user_profile.notes",
                        "value": "I prefer concise survey answers.",
                    }
                ],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert qd["recommended_text_answer"].startswith("It feels")
    assert qd["requires_human_review"] is False
    assert report["validation_passed"] is True


def test_profile_llm_strict_private_without_profile_requires_review(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    question = {
        "question_id": "q1",
        "question_type": "text_input",
        "question_stem": {"text": "What is your exact address?"},
        "answer_options": [],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert qd["answer_mode"] == "strict_private"
    assert qd["requires_human_review"] is True
    assert "user_profile.json" in qd["human_review_reason"]
    assert report["requires_human_review"] is True


def test_professional_research_range_uses_professional_judgement(tmp_path, monkeypatch):
    _patch_answer_engine_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "config" / "answer_engine.json",
        {
            "minimum_confidence_without_review": 0.85,
            "allow_profile_llm_answerer": True,
        },
    )
    _write_json(
        tmp_path / "config" / "user_profile.json",
        {
            "professional_identity_policy": {
                "allow_representative_professional_identity": True,
                "allowed_research_contexts": ["independent research", "self-directed research"],
            }
        },
    )
    question = {
        "question_id": "q1",
        "question_type": "single_choice",
        "question_stem": {"text": "Where do you conduct your research?"},
        "answer_options": [
            {"option_id": "o1", "text": "University"},
            {"option_id": "o2", "text": "Independent / self-directed"},
        ],
        "confidence": 1.0,
    }
    _write_json(
        tmp_path / "runtime_state" / "latest_orchestrated_parse.json",
        {"parsed_page": {"task_id": "t1", "page": {"confidence": 1.0}, "questions": [question]}},
    )

    def fake_call(**kwargs):
        assert '"answer_mode":"professional_judgement"' in kwargs["prompt"]
        return json.dumps(
            {
                "answer_mode": "professional_judgement",
                "recommended_option_ids": ["o2"],
                "recommended_text_answer": "",
                "confidence": 0.9,
                "basis": "allowed professional identity range: independent research",
                "reason": "The profile allows broad independent/self-directed research context.",
                "evidence": [],
                "requires_human_review": False,
                "human_review_reason": "",
            }
        )

    monkeypatch.setattr(profile_llm_strategy, "call_ollama_answerer", fake_call)

    decision, report = answer_engine.build_answer_decision("auto")

    qd = decision["question_decisions"][0]
    assert qd["answer_mode"] == "professional_judgement"
    assert qd["recommended_option_ids"] == ["o2"]
    assert qd["requires_human_review"] is False
    assert report["requires_human_review"] is False


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
