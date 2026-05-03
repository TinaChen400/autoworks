from __future__ import annotations

from ..schema import question_decision


def decide(question: dict, category: str, profile: dict, session: dict | None, config: dict) -> dict:
    if question.get("confidence", 0.0) >= 0.95 and question.get("answer_options"):
        return question_decision(
            question,
            category,
            "image_task_strategy",
            confidence=0.0,
            reason="Parsed image evidence exists, but local image answering is not implemented.",
            requires_human_review=True,
            human_review_reason="MVP does not call a vision model or infer image answers.",
        )
    return question_decision(
        question,
        category,
        "image_task_strategy",
        confidence=0.0,
        reason="Image task strategy is an MVP stub.",
        requires_human_review=True,
        human_review_reason="Image reasoning requires human review unless a later parser provides explicit evidence.",
    )
