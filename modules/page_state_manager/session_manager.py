from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .consistency_checker import detect_decision_contradictions, normalize_key
from .input_loader import load_latest_answer_decision, load_latest_parse, resolve_parse_source
from .page_history import normalize_text, question_summaries, similar_questions
from .schema import memory_fact, new_session, page_record, utc_now_iso
from .session_lite import answer_text_from_decision, append_recent_answers, classify_flow_status
from .session_store import load_session, save_session

ROOT = Path.cwd()
RUNTIME_DIR = ROOT / "runtime_state"
REPORT_PATH = RUNTIME_DIR / "latest_session_update_report.json"


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
        value = answer_text_from_decision(qd)
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


def _visual_element_count(parsed_page: dict) -> int:
    visual_elements = parsed_page.get("visual_elements", [])
    return len(visual_elements) if isinstance(visual_elements, list) else 0


def _decision_matches_current_questions(decision: dict | None, questions: list[dict]) -> bool:
    if not decision:
        return False
    current_texts = {
        normalize_text(question.get("question_text", ""))
        for question in questions
        if question.get("question_text")
    }
    if not current_texts:
        return False
    for qd in decision.get("question_decisions", []) or []:
        if normalize_text(qd.get("question_text", "")) in current_texts:
            return True
    return False


def _requires_human_review(parsed_page: dict, warnings: list[dict]) -> bool:
    if parsed_page.get("requires_human_review") is True:
        return True
    page = parsed_page.get("page") or {}
    if page.get("requires_human_review") is True:
        return True
    return any(warning.get("type") == "contradiction" for warning in warnings)


def _should_start_new_session(session: dict, flow_status: str, questions: list[dict]) -> bool:
    previous_status = session.get("flow_status", "unknown")
    return previous_status in {"finished", "kicked_out"} and flow_status == "question_page" and bool(questions)


def _write_report(report: dict) -> Path:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return REPORT_PATH


def _build_report(
    *,
    ok: bool,
    source_parse: str,
    output_path: Path,
    report_path: Path,
    task_id: str = "",
    session_id: str = "",
    page_count: int = 0,
    question_count: int = 0,
    visual_element_count: int = 0,
    requires_human_review: bool = False,
    flow_status: str = "unknown",
    session_continuity: str = "same_session",
    session_continuity_reason: str = "",
    warnings: list | None = None,
    errors: list | None = None,
) -> dict:
    return {
        "ok": ok,
        "source_parse": source_parse,
        "output_path": str(output_path),
        "report_path": str(report_path),
        "task_id": task_id,
        "session_id": session_id,
        "page_count": page_count,
        "question_count": question_count,
        "visual_element_count": visual_element_count,
        "flow_status": flow_status,
        "session_continuity": session_continuity,
        "session_continuity_reason": session_continuity_reason,
        "requires_human_review": requires_human_review,
        "warnings": warnings or [],
        "errors": errors or [],
        "created_at": utc_now_iso(),
    }


def update_session(source: str | Path = "auto", task_id: str = "") -> dict:
    parsed_page, source_path = load_latest_parse(source)
    decision = load_latest_answer_decision()
    effective_task_id = _task_id(parsed_page) or task_id
    session = load_session(effective_task_id)
    page_type = _page_type(parsed_page)
    flow_status = classify_flow_status(parsed_page)
    questions = question_summaries(parsed_page.get("questions", []))
    if _should_start_new_session(session, flow_status, questions):
        session = new_session(effective_task_id)
        session["session_continuity"] = "new_session"
        session["session_continuity_reason"] = (
            "Previous survey was terminal and a new question page appeared."
        )
    else:
        session["session_continuity"] = "same_session"
        session["session_continuity_reason"] = ""
    session["task_id"] = session.get("task_id") or effective_task_id
    pages = session.setdefault("pages", [])
    decision_matches_current = _decision_matches_current_questions(decision, questions)
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

    conflicts = detect_decision_contradictions(session, decision) if decision_matches_current else []
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
    incoming_page["flow_status"] = flow_status
    if existing_page_index is None:
        pages.append(incoming_page)
    else:
        pages[existing_page_index] = _merge_existing_page(pages[existing_page_index], incoming_page)
    session["current_page_index"] = page_index
    session["flow_status"] = flow_status

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
    decision_facts = _decision_facts(decision) if decision_matches_current else []
    for fact in decision_facts:
        key = (fact.get("fact_key", ""), fact.get("value", ""))
        if key not in existing_facts:
            session.setdefault("consistency_memory", []).append(fact)
            existing_facts.add(key)

    if decision_matches_current:
        append_recent_answers(
            session,
            page_index=page_index,
            decision_id=decision.get("decision_id", ""),
            question_decisions=decision.get("question_decisions", []),
            confirmed=False,
        )

    session["updated_at"] = utc_now_iso()
    save_session(session)
    return session


def update_session_with_report(
    source: str | Path = "auto",
    task_id: str = "",
) -> tuple[dict | None, dict]:
    source_path = str(resolve_parse_source(source))
    try:
        parsed_page, loaded_source_path = load_latest_parse(source)
        session = update_session(loaded_source_path, task_id=task_id)
        warnings = session.get("warnings", [])
        report = _build_report(
            ok=True,
            source_parse=loaded_source_path,
            output_path=RUNTIME_DIR / "latest_survey_session.json",
            report_path=REPORT_PATH,
            task_id=session.get("task_id", ""),
            session_id=session.get("session_id", ""),
            page_count=len(session.get("pages", [])),
            question_count=len(parsed_page.get("questions", []) or []),
            visual_element_count=_visual_element_count(parsed_page),
            flow_status=session.get("flow_status", "unknown"),
            session_continuity=session.get("session_continuity", "same_session"),
            session_continuity_reason=session.get("session_continuity_reason", ""),
            requires_human_review=_requires_human_review(parsed_page, warnings),
            warnings=warnings,
            errors=[],
        )
        _write_report(report)
        return session, report
    except Exception as exc:
        report = _build_report(
            ok=False,
            source_parse=source_path,
            output_path=RUNTIME_DIR / "latest_survey_session.json",
            report_path=REPORT_PATH,
            errors=[str(exc)],
        )
        _write_report(report)
        return None, report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update page state from the latest parse output.")
    parser.add_argument(
        "--source",
        default="auto",
        help="Parse JSON path to read, or 'auto' for runtime_state/latest_orchestrated_parse.json.",
    )
    parser.add_argument("--task", default="", help="Accepted for runner compatibility.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    session, report = update_session_with_report(args.source, task_id=args.task)
    if not report["ok"]:
        print(
            f"Failed to update session from {report['source_parse']}: "
            f"{'; '.join(report['errors'])}",
            file=sys.stderr,
        )
        return 1
    page_count = len(session.get("pages", []))
    print(
        "Saved runtime_state/latest_survey_session.json and "
        f"runtime_state/latest_session_update_report.json ({page_count} page(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
