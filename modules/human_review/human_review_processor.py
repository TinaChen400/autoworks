from __future__ import annotations

import argparse
from copy import deepcopy

from modules.page_state_manager.schema import utc_now_iso
from modules.page_state_manager.session_lite import append_recent_answers

from . import review_store
from .review_validator import CHOICE_QUESTION_TYPES, TEXT_QUESTION_TYPES, extract_parsed_page, validate_manual_review_input
from .schema import REVIEWED_ANSWER_DECISION_ARTIFACT_PATH, human_review_report


COORDINATE_KEYS = {
    "x",
    "y",
    "left",
    "top",
    "right",
    "bottom",
    "width",
    "height",
    "bbox",
    "bbox_norm",
    "click_point",
    "click_point_norm",
    "coordinates",
    "coordinate",
    "click_targets",
}


def _without_coordinates(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_coordinates(child)
            for key, child in value.items()
            if key not in COORDINATE_KEYS
        }
    if isinstance(value, list):
        return [_without_coordinates(child) for child in value]
    return value


def _apply_approval(qd: dict, approval: dict) -> None:
    question_type = qd.get("question_type", "unknown")
    if question_type in CHOICE_QUESTION_TYPES:
        qd["recommended_option_ids"] = [str(option_id) for option_id in approval.get("approved_option_ids", [])]
        qd["recommended_text_answer"] = ""
    elif question_type in TEXT_QUESTION_TYPES:
        qd["recommended_text_answer"] = str(approval.get("approved_text_answer", ""))
        qd["recommended_option_ids"] = []

    qd["requires_human_review"] = False
    qd["human_review_reason"] = ""
    qd["confidence"] = 1.0
    qd["approval_source"] = "manual_review"
    if approval.get("review_note"):
        qd["review_note"] = str(approval.get("review_note", ""))


def _refresh_decision_rollup(decision: dict) -> None:
    question_decisions = decision.get("question_decisions", [])
    confidences = [item.get("confidence", 0.0) for item in question_decisions]
    decision["overall_confidence"] = min(confidences) if confidences else 0.0
    decision["requires_human_review"] = any(
        item.get("requires_human_review", True) for item in question_decisions
    )
    decision["updated_at"] = utc_now_iso()
    decision["approval_source"] = "manual_review"


def _current_page(session: dict, decision: dict) -> dict:
    pages = session.get("pages", [])
    source_parse = decision.get("source_parse", "")
    for page in pages:
        if source_parse and page.get("source_parse_path") == source_parse:
            return page

    current_page_index = session.get("current_page_index")
    for page in pages:
        if page.get("page_index") == current_page_index:
            return page

    return pages[-1] if pages else {}


def _decision_summary(decision: dict, report: dict) -> dict:
    return {
        "decision_id": decision.get("decision_id", ""),
        "source_decision_id": decision.get("source_decision_id", ""),
        "source_session_id": decision.get("session_id", ""),
        "overall_confidence": decision.get("overall_confidence", 0.0),
        "requires_human_review": bool(decision.get("requires_human_review") or report.get("requires_human_review")),
        "validation_passed": bool(report.get("validation_passed", False)),
        "approval_source": decision.get("approval_source", ""),
        "question_decisions": [
            {
                "question_id": qd.get("question_id", ""),
                "question_type": qd.get("question_type", "unknown"),
                "recommended_option_ids": qd.get("recommended_option_ids", []),
                "recommended_text_answer": qd.get("recommended_text_answer", ""),
                "confidence": qd.get("confidence", 0.0),
                "requires_human_review": bool(qd.get("requires_human_review", True)),
                "human_review_reason": qd.get("human_review_reason", ""),
                "approval_source": qd.get("approval_source", ""),
                "warnings": qd.get("warnings", []),
            }
            for qd in decision.get("question_decisions", [])
        ],
    }


def _update_session(session: dict, decision: dict, report: dict) -> dict:
    page = _current_page(session, decision)
    if not page:
        return session

    page["answer_decisions"] = [_decision_summary(decision, report)]
    page["status"] = "decision_ready" if not report.get("requires_human_review") else "human_review_required"
    linked = page.setdefault("linked_artifacts", {})
    linked["reviewed_answer_decision"] = REVIEWED_ANSWER_DECISION_ARTIFACT_PATH

    decision_by_question_id = {
        item.get("question_id", ""): item for item in decision.get("question_decisions", [])
    }
    for question in page.get("questions", []):
        qd = decision_by_question_id.get(question.get("question_id", ""))
        if not qd:
            continue
        question["answer_decision"] = {
            "decision_id": decision.get("decision_id", ""),
            "recommended_option_ids": qd.get("recommended_option_ids", []),
            "recommended_text_answer": qd.get("recommended_text_answer", ""),
            "requires_human_review": bool(qd.get("requires_human_review", True)),
            "confidence": qd.get("confidence", 0.0),
            "approval_source": qd.get("approval_source", ""),
        }

    append_recent_answers(
        session,
        page_index=page.get("page_index", session.get("current_page_index", 0)),
        decision_id=decision.get("decision_id", ""),
        question_decisions=decision.get("question_decisions", []),
        confirmed=True,
    )
    session["updated_at"] = utc_now_iso()
    return session


def process_manual_review(source: str = "auto") -> tuple[dict, dict]:
    _ = source
    manual_input, source_decision, orchestrated_parse, session = review_store.load_inputs()
    parsed_page = extract_parsed_page(orchestrated_parse)
    approvals_by_question_id, issues, warnings = validate_manual_review_input(
        manual_input,
        source_decision,
        parsed_page,
        session,
    )

    reviewed_decision = deepcopy(source_decision)
    reviewed_decision["source_decision_id"] = source_decision.get("decision_id", "")
    reviewed_decision["reviewed_answer_decision_path"] = REVIEWED_ANSWER_DECISION_ARTIFACT_PATH

    for qd in reviewed_decision.get("question_decisions", []):
        approval = approvals_by_question_id.get(qd.get("question_id", ""))
        if approval:
            _apply_approval(qd, approval)

    _refresh_decision_rollup(reviewed_decision)
    unresolved_question_ids = [
        qd.get("question_id", "")
        for qd in reviewed_decision.get("question_decisions", [])
        if qd.get("requires_human_review", True)
    ]
    report = human_review_report(
        validation_passed=not issues and not unresolved_question_ids,
        source_decision_id=source_decision.get("decision_id", ""),
        session_id=session.get("session_id", ""),
        task_id=session.get("task_id", ""),
        approved_question_ids=sorted(approvals_by_question_id),
        unresolved_question_ids=unresolved_question_ids,
        issues=issues,
        warnings=warnings,
    )

    reviewed_decision["validation_passed"] = report["validation_passed"]
    reviewed_decision["human_review_report_path"] = "runtime_state/latest_human_review_report.json"
    reviewed_decision = _without_coordinates(reviewed_decision)
    review_store.save_json(review_store.REVIEWED_DECISION_PATH, reviewed_decision)
    review_store.save_json(review_store.HUMAN_REVIEW_REPORT_PATH, report)

    updated_session = _update_session(session, reviewed_decision, report)
    review_store.save_json(review_store.SESSION_PATH, updated_session)
    return reviewed_decision, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apply explicit manual human review approvals.")
    parser.add_argument("--source", choices=["auto"], default="auto")
    args = parser.parse_args(argv)
    reviewed_decision, report = process_manual_review(args.source)
    print(
        "Saved runtime_state/latest_reviewed_answer_decision.json "
        f"(requires_human_review={reviewed_decision.get('requires_human_review')})."
    )
    print(
        "Saved runtime_state/latest_human_review_report.json "
        f"(validation_passed={report.get('validation_passed')})."
    )


if __name__ == "__main__":
    main()
