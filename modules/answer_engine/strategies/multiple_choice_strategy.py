from __future__ import annotations

from ..evidence_matcher import is_all_of_the_above, supported_options
from ..schema import click_target_from_option, question_decision


PERSONAL_CATEGORIES = {
    "personal_experience",
    "account_ownership",
    "device_capability",
    "language_proficiency",
    "demographic",
    "preference",
    "screening_question",
}


def decide(question: dict, category: str, profile: dict, session: dict | None, config: dict) -> dict:
    options = question.get("answer_options", [])
    supported = supported_options(options, profile, session)
    all_option = next((option for option in options if is_all_of_the_above(option)), None)
    substantive = [option for option in options if not is_all_of_the_above(option)]

    selected_options = [option for option in substantive if option.get("option_id") in supported]
    selected_ids = [option.get("option_id", "") for option in selected_options]

    if all_option and substantive and len(selected_options) == len(substantive):
        selected_options = [all_option]
        selected_ids = [all_option.get("option_id", "")]

    evidence = []
    for option_id in selected_ids:
        evidence.extend(supported.get(option_id, []))
    if all_option and selected_ids == [all_option.get("option_id", "")]:
        for option in substantive:
            evidence.extend(supported.get(option.get("option_id", ""), []))

    if category in PERSONAL_CATEGORIES and not selected_ids:
        return question_decision(
            question,
            category,
            "multiple_choice_strategy",
            confidence=0.0,
            reason="No option is explicitly supported by profile or session evidence.",
            missing_information=["explicit supporting personal evidence"],
            requires_human_review=True,
            human_review_reason="Personal or screening question needs evidence before selecting options.",
        )

    if not selected_ids:
        return question_decision(
            question,
            category,
            "multiple_choice_strategy",
            confidence=0.0,
            reason="No local rule selected an answer.",
            requires_human_review=True,
            human_review_reason="No supported answer found.",
        )

    confidence = 0.9
    return question_decision(
        question,
        category,
        "multiple_choice_strategy",
        recommended_option_ids=selected_ids,
        confidence=confidence,
        reason="Selected only options supported by explicit evidence.",
        evidence=evidence,
        requires_human_review=confidence < config.get("minimum_confidence_without_review", 0.85),
        human_review_reason="" if confidence >= config.get("minimum_confidence_without_review", 0.85) else "Confidence below threshold.",
        click_targets=[click_target_from_option(option) for option in selected_options],
    )
