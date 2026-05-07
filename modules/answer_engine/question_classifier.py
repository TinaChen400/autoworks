from __future__ import annotations

import re

from .schema import get_question_text


def _norm(text: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def classify_category(question: dict) -> str:
    text = _norm(get_question_text(question))
    if any(term in text for term in ("image", "picture", "screenshot", "shown")):
        return "image_reasoning"
    if any(term in text for term in ("account", "seller central", "vendor central")) and any(
        term in text for term in ("have", "own", "using", "experience")
    ):
        return "account_ownership"
    if any(term in text for term in ("experience", "used", "using", "worked with", "tried")):
        return "personal_experience"
    if any(term in text for term in ("device", "phone", "laptop", "computer", "camera")):
        return "device_capability"
    if any(term in text for term in ("language", "speak", "read", "write", "fluent")):
        return "language_proficiency"
    if any(term in text for term in ("age", "gender", "income", "employment", "health", "location")):
        return "demographic"
    if any(term in text for term in ("prefer", "favourite", "favorite", "like", "dislike")):
        return "preference"
    if any(term in text for term in ("enter", "provide", "fill")) and question.get("input_fields"):
        return "form_fill"
    if any(term in text for term in ("qualify", "screen", "eligible")):
        return "screening_question"
    if text:
        return "objective_task"
    return "unknown"


def detect_question_type(question: dict) -> str:
    qtype = question.get("question_type") or "unknown"
    if qtype != "unknown":
        return qtype
    if question.get("matrix"):
        return "matrix"
    if question.get("media"):
        return "image_task"
    if question.get("input_fields"):
        return "form_fill"
    if question.get("answer_options"):
        return "single_choice"
    return "unknown"
