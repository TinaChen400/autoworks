from __future__ import annotations

from ..evidence_matcher import evidence_values
from ..schema import question_decision


def decide(question: dict, category: str, profile: dict, session: dict | None, config: dict) -> dict:
    values = evidence_values(profile, session)
    if not values:
        return question_decision(
            question,
            category,
            "form_fill_strategy",
            confidence=0.0,
            reason="No explicit profile fields are available for form fill.",
            missing_information=["profile field values"],
            requires_human_review=True,
            human_review_reason="Form fill requires explicit user profile evidence.",
        )
    return question_decision(
        question,
        category,
        "form_fill_strategy",
        confidence=0.0,
        reason="Form-fill mapping is scaffolded but not implemented.",
        evidence=values,
        requires_human_review=True,
        human_review_reason="MVP form fill strategy does not map fields yet.",
    )
