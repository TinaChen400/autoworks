from __future__ import annotations

from .consistency_checker import detect_decision_contradictions, normalize_key
from .input_loader import load_latest_answer_decision, load_latest_parse
from .page_history import question_summaries, similar_questions
from .schema import memory_fact, page_record, utc_now_iso
from .session_store import load_session, save_session


def _page_type(parsed_page: dict) -> str:
    return (parsed_page.get("page") or {}).get("page_type", "unknown")


def _task_id(parsed_page: dict) -> str:
    return parsed_page.get("task_id", "")


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

    warnings = []
    for question in parsed_page.get("questions", []):
        repeats = similar_questions(question, session.get("pages", []))
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

    page_index = len(session.get("pages", [])) + 1
    answer_decisions = decision.get("question_decisions", []) if decision else []
    status = "answered_pending_review" if answer_decisions else "decision_pending"
    session.setdefault("pages", []).append(
        page_record(
            page_index=page_index,
            source_parse_path=source_path,
            page_type=_page_type(parsed_page),
            questions=question_summaries(parsed_page.get("questions", [])),
            answer_decisions=answer_decisions,
            status=status,
        )
    )
    session["current_page_index"] = page_index

    detected_types = {q.get("question_type", "unknown") for q in parsed_page.get("questions", [])}
    existing_types = set(session.get("known_context", {}).get("detected_question_types", []))
    session.setdefault("known_context", {})["detected_question_types"] = sorted(existing_types | detected_types)
    session.setdefault("warnings", []).extend(warnings)

    existing_facts = {
        (fact.get("fact_key", ""), fact.get("value", "")) for fact in session.get("consistency_memory", [])
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
    print(f"Saved runtime_state/latest_survey_session.json ({len(session.get('pages', []))} page(s)).")


if __name__ == "__main__":
    main()
