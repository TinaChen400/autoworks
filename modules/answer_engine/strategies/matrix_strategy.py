from __future__ import annotations

from ..schema import question_decision


def decide(question: dict, category: str, profile: dict, session: dict | None, config: dict) -> dict:
    return question_decision(
        question,
        category,
        "matrix_strategy",
        confidence=0.0,
        reason="Matrix strategy is an MVP stub.",
        requires_human_review=True,
        human_review_reason="Matrix questions require human review in this scaffold.",
    )
