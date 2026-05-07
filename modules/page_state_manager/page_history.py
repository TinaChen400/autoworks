from __future__ import annotations

import re


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def question_text(question: dict) -> str:
    stem = question.get("question_stem") or {}
    parts = [stem.get("text", "")]
    parts.extend(item.get("text", "") for item in question.get("instructions", []))
    return normalize_text(" ".join(parts))


def similar_questions(current_question: dict, pages: list[dict]) -> list[dict]:
    current_text = question_text(current_question)
    if not current_text:
        return []
    matches = []
    for page in pages:
        for prior in page.get("questions", []):
            prior_text = question_text(prior)
            if prior_text and (prior_text == current_text or current_text in prior_text or prior_text in current_text):
                matches.append(
                    {
                        "page_index": page.get("page_index"),
                        "question_id": prior.get("question_id", ""),
                        "question_text": prior_text,
                    }
                )
    return matches


def question_summaries(questions: list[dict]) -> list[dict]:
    return [
        {
            "question_id": question.get("question_id", ""),
            "question_type": question.get("question_type", "unknown"),
            "question_text": question_text(question),
            "confidence": question.get("confidence", 0.0),
        }
        for question in questions
    ]
