from __future__ import annotations

import re


FINISHED_TERMS = (
    "thank you",
    "thanks for completing",
    "survey complete",
    "completed",
    "submitted",
    "your response has been recorded",
)

KICKED_OUT_TERMS = (
    "not qualified",
    "do not qualify",
    "don't qualify",
    "did not qualify",
    "screened out",
    "quota full",
    "quota has been filled",
    "unfortunately you are not",
    "not eligible",
    "\u4e0d\u7b26\u5408",
    "\u914d\u989d\u5df2\u6ee1",
    "\u7504\u522b\u5931\u8d25",
)


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _page_text(parsed_page: dict) -> str:
    parts: list[str] = []
    page = parsed_page.get("page") or {}
    for key in ("summary", "title", "message", "page_status"):
        parts.append(str(page.get(key) or ""))
    for question in parsed_page.get("questions", []) or []:
        stem = question.get("question_stem") or {}
        parts.append(str(stem.get("text") or ""))
        parts.extend(str(item.get("text") or "") for item in question.get("instructions", []) or [])
    for button in parsed_page.get("navigation_buttons", []) or []:
        parts.append(str(button.get("text") or ""))
        parts.append(str(button.get("action") or ""))
    for element in parsed_page.get("visual_elements", []) or []:
        parts.append(str(element.get("text") or ""))
    return normalize_text(" ".join(parts))


def classify_flow_status(parsed_page: dict) -> str:
    text = _page_text(parsed_page)
    if any(term in text for term in KICKED_OUT_TERMS):
        return "kicked_out"
    if any(term in text for term in FINISHED_TERMS):
        return "finished"
    if parsed_page.get("questions"):
        return "question_page"
    return "unknown"


def answer_text_from_decision(qd: dict) -> str:
    text_answer = str(qd.get("recommended_text_answer") or "").strip()
    if text_answer:
        return text_answer
    target_texts = [
        str(target.get("text") or "").strip()
        for target in qd.get("click_targets", []) or []
        if str(target.get("text") or "").strip()
    ]
    if target_texts:
        return ", ".join(target_texts)
    return ", ".join(str(option_id) for option_id in qd.get("recommended_option_ids", []) or [])


def append_recent_answers(
    session: dict,
    *,
    page_index: int,
    decision_id: str,
    question_decisions: list[dict],
    confirmed: bool,
    limit: int = 20,
) -> None:
    recent = session.setdefault("recent_answers", [])
    existing = {
        (
            item.get("decision_id", ""),
            item.get("question_id", ""),
            normalize_text(item.get("answer_text", "")),
        )
        for item in recent
    }
    for qd in question_decisions:
        answer_text = answer_text_from_decision(qd)
        if not answer_text:
            continue
        key = (decision_id, qd.get("question_id", ""), normalize_text(answer_text))
        if key in existing:
            continue
        recent.append(
            {
                "page_index": page_index,
                "question_id": qd.get("question_id", ""),
                "question_text": qd.get("question_text", ""),
                "answer_text": answer_text,
                "confirmed": bool(confirmed),
                "decision_id": decision_id,
            }
        )
        existing.add(key)
    if len(recent) > limit:
        del recent[:-limit]
