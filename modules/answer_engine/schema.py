from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def click_target_from_option(option: dict) -> dict:
    return {
        "option_id": option.get("option_id", ""),
        "text": option.get("text", ""),
        "click_point_norm": option.get("click_point_norm") or {"x": 0, "y": 0},
        "bbox_norm": option.get("bbox_norm") or {"x": 0, "y": 0, "width": 0, "height": 0},
    }


def question_decision(
    question: dict,
    question_category: str,
    answer_strategy: str,
    recommended_option_ids: list[str] | None = None,
    recommended_text_answer: str = "",
    confidence: float = 0.0,
    reason: str = "",
    evidence: list[dict] | None = None,
    missing_information: list[str] | None = None,
    requires_human_review: bool = True,
    human_review_reason: str = "",
    click_targets: list[dict] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "question_id": question.get("question_id", ""),
        "question_type": question.get("question_type", "unknown"),
        "question_category": question_category,
        "question_text": get_question_text(question),
        "answer_strategy": answer_strategy,
        "recommended_option_ids": recommended_option_ids or [],
        "recommended_text_answer": recommended_text_answer,
        "confidence": float(confidence),
        "reason": reason,
        "evidence": evidence or [],
        "missing_information": missing_information or [],
        "requires_human_review": bool(requires_human_review),
        "human_review_reason": human_review_reason,
        "click_targets": click_targets or [],
        "warnings": warnings or [],
    }


def answer_decision(task_id: str, source_parse: str, session_id: str, question_decisions: list[dict]) -> dict:
    confidences = [item.get("confidence", 0.0) for item in question_decisions]
    return {
        "decision_id": f"decision_{uuid4().hex}",
        "task_id": task_id,
        "source_parse": source_parse,
        "session_id": session_id,
        "question_decisions": question_decisions,
        "overall_confidence": min(confidences) if confidences else 0.0,
        "requires_human_review": any(item.get("requires_human_review", True) for item in question_decisions),
        "warnings": [],
        "created_at": utc_now_iso(),
    }


def get_question_text(question: dict) -> str:
    stem = question.get("question_stem") or {}
    parts = [stem.get("text", "")]
    parts.extend(item.get("text", "") for item in question.get("instructions", []))
    return " ".join(part for part in parts if part).strip()
