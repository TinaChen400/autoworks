from __future__ import annotations

import argparse

from .answer_validator import validate_decision
from .decision_store import save_decision, save_report
from .input_loader import load_config, load_parse, load_session
from .question_classifier import classify_category, detect_question_type
from .schema import answer_decision
from .profile_llm_strategy import decide as profile_llm_decide, should_use_profile_llm
from .user_profile_loader import load_user_profile
from .strategies import (
    form_fill_strategy,
    image_task_strategy,
    matrix_strategy,
    multiple_choice_strategy,
    single_choice_strategy,
    text_input_strategy,
    unknown_strategy,
)


def choose_strategy(question_type: str):
    return {
        "single_choice": single_choice_strategy,
        "multiple_choice": multiple_choice_strategy,
        "text_input": text_input_strategy,
        "number_input": text_input_strategy,
        "rating_scale": single_choice_strategy,
        "matrix": matrix_strategy,
        "image_task": image_task_strategy,
        "form_fill": form_fill_strategy,
    }.get(question_type, unknown_strategy)


def build_answer_decision(source: str = "auto") -> tuple[dict, dict]:
    config = load_config()
    parsed_page, source_path = load_parse(source)
    session = load_session()
    profile, profile_exists, _example = load_user_profile()

    question_decisions = []
    for question in parsed_page.get("questions", []):
        question = dict(question)
        question_type = detect_question_type(question)
        question["question_type"] = question_type
        category = classify_category(question)
        if should_use_profile_llm(config, question_type):
            qd = profile_llm_decide(question, category, profile, profile_exists, session, config)
        else:
            strategy = choose_strategy(question_type)
            qd = strategy.decide(question, category, profile, session, config)
        if (
            not profile_exists
            and qd.get("answer_mode") == "strict_private"
            and category in {
            "personal_experience",
            "account_ownership",
            "device_capability",
            "language_proficiency",
            "demographic",
            "preference",
            "screening_question",
            }
        ):
            qd["requires_human_review"] = True
            qd["human_review_reason"] = qd["human_review_reason"] or "config/user_profile.json is missing."
            if "user_profile missing" not in qd["warnings"]:
                qd["warnings"].append("user_profile missing")
        question_decisions.append(qd)

    decision = answer_decision(
        task_id=parsed_page.get("task_id", ""),
        source_parse=source_path,
        session_id=(session or {}).get("session_id", ""),
        question_decisions=question_decisions,
    )
    report = validate_decision(decision, parsed_page, config, session)
    if report["requires_human_review"]:
        decision["requires_human_review"] = True
    decision["warnings"].extend(report.get("warnings", []))
    save_decision(decision)
    save_report(report)
    return decision, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build answer recommendations without executing actions.")
    parser.add_argument("--source", choices=["auto", "local", "orchestrated", "parsed"], default="auto")
    args = parser.parse_args(argv)
    decision, report = build_answer_decision(args.source)
    print(
        "Saved runtime_state/latest_answer_decision.json "
        f"({len(decision.get('question_decisions', []))} question(s), "
        f"requires_human_review={decision.get('requires_human_review')})."
    )
    print(
        "Saved runtime_state/latest_answer_engine_report.json "
        f"(validation_passed={report.get('validation_passed')})."
    )


if __name__ == "__main__":
    main()
