from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_session(task_id: str = "") -> dict:
    now = utc_now_iso()
    return {
        "session_id": f"session_{uuid4().hex}",
        "task_id": task_id,
        "pages": [],
        "current_page_index": 0,
        "known_context": {
            "task_topic": "",
            "platform": "",
            "detected_question_types": [],
        },
        "flow_status": "unknown",
        "session_continuity": "same_session",
        "session_continuity_reason": "",
        "recent_answers": [],
        "consistency_memory": [],
        "warnings": [],
        "created_at": now,
        "updated_at": now,
    }


def page_record(
    page_index: int,
    source_parse_path: str,
    page_type: str,
    questions: list[dict],
    answer_decisions: list[dict] | None = None,
    status: str = "decision_pending",
) -> dict:
    return {
        "page_index": page_index,
        "source_parse_path": source_parse_path,
        "page_type": page_type,
        "questions": questions,
        "answer_decisions": answer_decisions or [],
        "status": status,
    }


def memory_fact(fact_key: str, value: str, source: str, confidence: float) -> dict:
    return {
        "fact_key": fact_key,
        "value": value,
        "source": source,
        "confidence": float(confidence),
    }
