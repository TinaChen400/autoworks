from __future__ import annotations

from .consistency_checker import detect_decision_contradictions, normalize_key
from .input_loader import load_latest_answer_decision, load_latest_parse
from .page_history import normalize_text, question_summaries, similar_questions
from .schema import memory_fact, page_record, utc_now_iso
from .session_store import load_session, save_session


def _page_type(parsed_page: dict) -> str:
    return (parsed_page.get("page") or {}).get("page_type", "unknown")


def _task_id(parsed_page: dict) -> str:
    return parsed_page.get("task_id", "")


def _question_identity(question: dict) -> tuple[str, str]:
    return (
        normalize_key(question.get("question_id", "")),
        normalize_text(question.get("question_text", "")),
    )


def _page_identity(
    source_parse_path: str,
    page_type: str,
    questions: list[dict],
) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    return (
        normalize_text(source_parse_path),
        normalize_key(page_type),
        tuple(_question_identity(question) for question in questions),
    )


def _find_existing_page_index(
    pages: list[dict],
    source_parse_path: str,
    page_type: str,
    questions: list[dict],
) -> int | None:
    current_identity = _page_identity(source_parse_path, page_type, questions)
    for index, page in enumerate(pages):
        page_questions = page.get("questions", [])
        if current_identity == _page_identity(
            page.get("source_parse_path", ""),
            page.get("page_type", "unknown"),
            page_questions,
        ):
            return index
    return None


def _merge_existing_page(existing: dict, incoming: dict) -> dict:
    merged = {**incoming}
    for field in ("answer_decisions", "status", "linked_artifacts"):
        if existing.get(field):
            merged[field] = existing[field]

    existing_questions = {
        _question_identity(question): question for question in existing.get("questions", [])
    }
    for question in merged.get("questions", []):
        previous = existing_questions.get(_question_identity(question))
        if previous and previous.get("answer_decision"):
            question["answer_decision"] = previous["answer_decision"]

    return merged


def _append_unique_warnings(session: dict, warnings: list[dict]) -> None:
    existing_warning_keys = {
        repr(sorted(warning.items()))
        for warning in session.get("warnings", [])
    }
    for warning in warnings:
        warning_key = repr(sorted(warning.items()))
        if warning_key not in existing_warning_keys:
            session.setdefault("warnings", []).append(warning)
            existing_warning_keys.add(warning_key)


def _decision_facts(decision: dict | None) -> list[dict]:
    if not decision:
        return []
    facts = []
    for qd in decision.get("question_decisions", []):
        value = qd.get("recommended_text_answer") or ", ".join(qd.get("recommended_option_ids", []))
        if not qd.get("requires_human_review") and value:
            facts.append(
                memory_fact(
                    fact_key=normalize_key(qd.get("question_text", "")),
                    value=value,
                    source=decision.get("decision_id", "latest_answer_decision"),
                    confidence=qd.get("confidence", 0.0),
                )
            )
    return facts


def update_session() -> dict:
    parsed_page, source_path = load_latest_parse()
    decision = load_latest_answer_decision()
    session = load_session(_task_id(parsed_page))
    session["task_id"] = session.get("task_id") or _task_id(parsed_page)
    pages = session.setdefault("pages", [])
    page_type = _page_type(parsed_page)
    questions = question_summaries(parsed_page.get("questions", []))
    existing_page_index = _find_existing_page_index(pages, source_path, page_type, questions)
    pages_for_history = [page for index, page in enumerate(pages) if index != existing_page_index]

    warnings = []
    for question in parsed_page.get("questions", []):
        repeats = similar_questions(question, pages_for_history)
        if repeats:
            warnings.append(
                {
                    "type": "repeated_or_similar_question",
                    "question_id": question.get("question_id", ""),
                    "matches": repeats,
                }
            )

    conflicts = detect_decision_contradictions(session, decision)
    for conflict in conflicts:
        warnings.append({"type": "contradiction", **conflict})

    page_index = (
        pages[existing_page_index].get("page_index", existing_page_index + 1)
        if existing_page_index is not None
        else len(pages) + 1
    )
    answer_decisions = decision.get("question_decisions", []) if decision else []
    status = "answered_pending_review" if answer_decisions else "decision_pending"
    incoming_page = page_record(
        page_index=page_index,
        source_parse_path=source_path,
        page_type=page_type,
        questions=questions,
        answer_decisions=answer_decisions,
        status=status,
    )
    if existing_page_index is None:
        pages.append(incoming_page)
    else:
        pages[existing_page_index] = _merge_existing_page(pages[existing_page_index], incoming_page)
    session["current_page_index"] = page_index

    detected_types = {q.get("question_type", "unknown") for q in parsed_page.get("questions", [])}
    existing_types = set(session.get("known_context", {}).get("detected_question_types", []))
    session.setdefault("known_context", {})["detected_question_types"] = sorted(
        existing_types | detected_types
    )
    _append_unique_warnings(session, warnings)

    existing_facts = {
        (fact.get("fact_key", ""), fact.get("value", ""))
        for fact in session.get("consistency_memory", [])
    }
    for fact in _decision_facts(decision):
        key = (fact.get("fact_key", ""), fact.get("value", ""))
        if key not in existing_facts:
            session.setdefault("consistency_memory", []).append(fact)
            existing_facts.add(key)

    session["updated_at"] = utc_now_iso()
    save_session(session)
    return session


def main() -> None:
    session = update_session()
    page_count = len(session.get("pages", []))
    print(f"Saved runtime_state/latest_survey_session.json ({page_count} page(s)).")


if __name__ == "__main__":
    main()
