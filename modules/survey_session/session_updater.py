from __future__ import annotations

import json
from pathlib import Path

from modules.page_state_manager.schema import utc_now_iso


ROOT = Path.cwd()
RUNTIME_DIR = ROOT / "runtime_state"
SESSION_PATH = RUNTIME_DIR / "latest_survey_session.json"
DECISION_PATH = RUNTIME_DIR / "latest_answer_decision.json"
ANSWER_REPORT_PATH = RUNTIME_DIR / "latest_answer_engine_report.json"
SESSION_UPDATE_REPORT_PATH = RUNTIME_DIR / "latest_session_update_report.json"

DEFAULT_LINKED_ARTIFACTS = {
    "orchestrated_parse": "runtime_state/latest_orchestrated_parse.json",
    "answer_decision": "runtime_state/latest_answer_decision.json",
    "answer_engine_report": "runtime_state/latest_answer_engine_report.json",
    "action_plan": "runtime_state/latest_action_plan.json",
    "resolved_action_plan": "runtime_state/latest_resolved_action_plan.json",
}


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


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

    if not pages:
        raise ValueError("latest_survey_session.json has no pages to update")
    return pages[-1]


def _decision_status(decision: dict, report: dict) -> str:
    if not report.get("validation_passed", False):
        return "decision_invalid"
    if decision.get("requires_human_review") or report.get("requires_human_review"):
        return "human_review_required"

    for qd in decision.get("question_decisions", []):
        if qd.get("recommended_option_ids") or qd.get("recommended_text_answer"):
            return "decision_ready"
    return "decision_pending"


def _decision_summary(decision: dict, report: dict) -> dict:
    return {
        "decision_id": decision.get("decision_id", ""),
        "source_session_id": decision.get("session_id", ""),
        "overall_confidence": decision.get("overall_confidence", 0.0),
        "requires_human_review": bool(
            decision.get("requires_human_review") or report.get("requires_human_review")
        ),
        "validation_passed": bool(report.get("validation_passed", False)),
        "question_decisions": [
            {
                "question_id": qd.get("question_id", ""),
                "question_type": qd.get("question_type", "unknown"),
                "recommended_option_ids": qd.get("recommended_option_ids", []),
                "recommended_text_answer": qd.get("recommended_text_answer", ""),
                "confidence": qd.get("confidence", 0.0),
                "requires_human_review": bool(qd.get("requires_human_review", True)),
                "human_review_reason": qd.get("human_review_reason", ""),
                "warnings": qd.get("warnings", []),
            }
            for qd in decision.get("question_decisions", [])
        ],
    }


def _ensure_linked_artifacts(page: dict) -> dict:
    linked = page.setdefault("linked_artifacts", {})
    for key, value in DEFAULT_LINKED_ARTIFACTS.items():
        linked.setdefault(key, value)
    return linked


def update_session_from_answer_outputs() -> tuple[dict, dict]:
    session = _read_json(SESSION_PATH)
    decision = _read_json(DECISION_PATH)
    report = _read_json(ANSWER_REPORT_PATH)

    page = _current_page(session, decision)
    page["answer_decisions"] = [_decision_summary(decision, report)]
    page["status"] = _decision_status(decision, report)
    _ensure_linked_artifacts(page)

    decision_by_question_id = {
        item.get("question_id", ""): item for item in decision.get("question_decisions", [])
    }
    updated_question_ids = []
    for question in page.get("questions", []):
        qd = decision_by_question_id.get(question.get("question_id", ""))
        if qd is None:
            continue
        question["answer_decision"] = {
            "decision_id": decision.get("decision_id", ""),
            "recommended_option_ids": qd.get("recommended_option_ids", []),
            "recommended_text_answer": qd.get("recommended_text_answer", ""),
            "requires_human_review": bool(qd.get("requires_human_review", True)),
            "confidence": qd.get("confidence", 0.0),
        }
        updated_question_ids.append(question.get("question_id", ""))

    session["updated_at"] = utc_now_iso()
    _write_json(SESSION_PATH, session)

    update_report = {
        "updated": True,
        "session_id": session.get("session_id", ""),
        "page_index": page.get("page_index"),
        "page_status": page.get("status", ""),
        "decision_id": decision.get("decision_id", ""),
        "updated_question_ids": updated_question_ids,
        "linked_artifacts": page.get("linked_artifacts", {}),
        "warnings": [],
        "created_at": utc_now_iso(),
    }
    _write_json(SESSION_UPDATE_REPORT_PATH, update_report)
    return session, update_report


def main() -> None:
    session, report = update_session_from_answer_outputs()
    print(
        "Saved runtime_state/latest_survey_session.json "
        f"(session_id={session.get('session_id')}, page_status={report.get('page_status')})."
    )
    print("Saved runtime_state/latest_session_update_report.json.")


if __name__ == "__main__":
    main()
