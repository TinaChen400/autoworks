from __future__ import annotations

from ..evidence_matcher import is_all_of_the_above, supported_options
from ..schema import click_target_from_option, question_decision


def decide(question: dict, category: str, profile: dict, session: dict | None, config: dict) -> dict:
    options = [option for option in question.get("answer_options", []) if not is_all_of_the_above(option)]
    supported = supported_options(options, profile, session)
    selected = [option for option in options if option.get("option_id") in supported]
    if len(selected) != 1:
        reason = "No supported option found." if not selected else "Multiple supported options found."
        return question_decision(
            question,
            category,
            "single_choice_strategy",
            confidence=0.0,
            reason=reason,
            requires_human_review=True,
            human_review_reason="Single choice requires exactly one clear evidence-supported option.",
        )
    option = selected[0]
    confidence = 0.9
    return question_decision(
        question,
        category,
        "single_choice_strategy",
        recommended_option_ids=[option.get("option_id", "")],
        confidence=confidence,
        reason="Selected the only option supported by explicit evidence.",
        evidence=supported.get(option.get("option_id", ""), []),
        requires_human_review=confidence < config.get("minimum_confidence_without_review", 0.85),
        click_targets=[click_target_from_option(option)],
    )
