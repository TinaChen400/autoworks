from __future__ import annotations

from ..evidence_matcher import evidence_values, norm
from ..schema import get_question_text, question_decision
from .multiple_choice_strategy import PERSONAL_CATEGORIES


def _matching_value(question_text: str, values: list[dict]) -> dict | None:
    q_norm = norm(question_text)
    for value in values:
        v_norm = norm(value.get("value", ""))
        if v_norm and (v_norm in q_norm or any(part in q_norm for part in v_norm.split() if len(part) > 4)):
            return value
    return values[0] if values else None


def decide(question: dict, category: str, profile: dict, session: dict | None, config: dict) -> dict:
    values = evidence_values(profile, session)
    match = _matching_value(get_question_text(question), values)
    if category in PERSONAL_CATEGORIES and not match:
        return question_decision(
            question,
            category,
            "text_input_strategy",
            confidence=0.0,
            reason="No explicit evidence is available for a personal text answer.",
            missing_information=["explicit personal fact"],
            requires_human_review=True,
            human_review_reason="Text answer would require inventing a personal fact.",
        )
    if not match:
        return question_decision(
            question,
            category,
            "text_input_strategy",
            confidence=0.0,
            reason="No evidence-backed text answer found.",
            requires_human_review=True,
            human_review_reason="No local rule can answer this text input.",
        )
    return question_decision(
        question,
        category,
        "text_input_strategy",
        recommended_text_answer=str(match["value"]),
        confidence=0.85,
        reason="Used an explicit profile or session value.",
        evidence=[match],
        requires_human_review=False,
    )
