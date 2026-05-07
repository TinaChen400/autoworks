from __future__ import annotations

from ..schema import question_decision


def decide(question: dict, category: str, profile: dict, session: dict | None, config: dict) -> dict:
    return question_decision(
        question,
        category,
        "unknown_strategy",
        confidence=0.0,
        reason="Question type or category is unknown.",
        requires_human_review=True,
        human_review_reason="Unknown questions are never answered automatically.",
    )
