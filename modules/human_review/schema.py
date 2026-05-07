from __future__ import annotations

from datetime import datetime, timezone


REVIEWED_ANSWER_DECISION_ARTIFACT_PATH = "runtime_state/latest_reviewed_answer_decision.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def issue(issue_type: str, message: str, question_id: str = "", **extra: object) -> dict:
    payload = {
        "type": issue_type,
        "message": message,
    }
    if question_id:
        payload["question_id"] = question_id
    payload.update(extra)
    return payload


def human_review_report(
    *,
    validation_passed: bool,
    source_decision_id: str,
    session_id: str,
    task_id: str,
    approved_question_ids: list[str],
    unresolved_question_ids: list[str],
    issues: list[dict],
    warnings: list[dict] | None = None,
) -> dict:
    return {
        "validation_passed": bool(validation_passed),
        "source_decision_id": source_decision_id,
        "session_id": session_id,
        "task_id": task_id,
        "approved_question_ids": approved_question_ids,
        "unresolved_question_ids": unresolved_question_ids,
        "requires_human_review": bool(unresolved_question_ids or issues),
        "issues": issues,
        "warnings": warnings or [],
        "created_at": utc_now_iso(),
    }

