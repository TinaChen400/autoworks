from __future__ import annotations

from .schema import issue


CHOICE_QUESTION_TYPES = {"single_choice", "multiple_choice", "dropdown"}
TEXT_QUESTION_TYPES = {"text_input", "number_input"}


def extract_parsed_page(orchestrated_parse: dict) -> dict:
    parsed_page = orchestrated_parse.get("parsed_page")
    if isinstance(parsed_page, dict):
        return parsed_page
    return orchestrated_parse


def question_map(parsed_page: dict) -> dict[str, dict]:
    return {
        str(question.get("question_id", "")): question
        for question in parsed_page.get("questions", [])
        if question.get("question_id")
    }


def option_ids_for_question(question: dict) -> set[str]:
    options = question.get("answer_options", []) or question.get("options", [])
    return {str(option.get("option_id", "")) for option in options if option.get("option_id")}


def validate_manual_review_input(
    manual_input: dict,
    decision: dict,
    parsed_page: dict,
    session: dict,
) -> tuple[dict[str, dict], list[dict], list[dict]]:
    approvals_by_question_id: dict[str, dict] = {}
    issues: list[dict] = []
    warnings: list[dict] = []

    source_decision_id = str(manual_input.get("source_decision_id", ""))
    if source_decision_id != decision.get("decision_id"):
        warnings.append(
            issue(
                "stale_manual_review_input",
                "Ignoring stale manual review input because it does not match latest_answer_decision.json.",
                expected=decision.get("decision_id", ""),
                actual=source_decision_id,
            )
        )
        manual_input = {"approvals": []}

    if source_decision_id == decision.get("decision_id") and manual_input.get("session_id") != decision.get("session_id"):
        issues.append(
            issue(
                "session_mismatch",
                "Manual review input session_id does not match latest_answer_decision.json.",
                expected=decision.get("session_id", ""),
                actual=manual_input.get("session_id", ""),
            )
        )

    if source_decision_id == decision.get("decision_id") and manual_input.get("session_id") != session.get("session_id"):
        issues.append(
            issue(
                "session_state_mismatch",
                "Manual review input session_id does not match latest_survey_session.json.",
                expected=session.get("session_id", ""),
                actual=manual_input.get("session_id", ""),
            )
        )

    if source_decision_id == decision.get("decision_id") and manual_input.get("task_id") != decision.get("task_id"):
        issues.append(
            issue(
                "task_mismatch",
                "Manual review input task_id does not match latest_answer_decision.json.",
                expected=decision.get("task_id", ""),
                actual=manual_input.get("task_id", ""),
            )
        )

    global_issue_count = len(issues)
    questions = question_map(parsed_page)
    decision_question_ids = {
        str(item.get("question_id", ""))
        for item in decision.get("question_decisions", [])
        if item.get("question_id")
    }
    approvals = manual_input.get("approvals", [])
    if not isinstance(approvals, list):
        issues.append(issue("invalid_approvals", "Manual review approvals must be a list."))
        approvals = []

    for approval in approvals:
        if not isinstance(approval, dict):
            issues.append(issue("invalid_approval", "Each approval must be an object."))
            continue

        question_id = str(approval.get("question_id", ""))
        if question_id not in questions:
            issues.append(
                issue(
                    "unknown_question_id",
                    "Manual approval references a question absent from latest_orchestrated_parse.json.",
                    question_id,
                )
            )
            continue
        if question_id not in decision_question_ids:
            issues.append(
                issue(
                    "question_not_in_decision",
                    "Manual approval references a question absent from latest_answer_decision.json.",
                    question_id,
                )
            )
            continue

        question = questions[question_id]
        question_type = question.get("question_type", "unknown")
        approved_option_ids = approval.get("approved_option_ids", [])
        if approved_option_ids is None:
            approved_option_ids = []
        if not isinstance(approved_option_ids, list):
            issues.append(
                issue("invalid_approved_option_ids", "approved_option_ids must be a list.", question_id)
            )
            continue

        approved_option_ids = [str(option_id) for option_id in approved_option_ids if str(option_id)]
        if question_type in CHOICE_QUESTION_TYPES:
            if not approved_option_ids:
                issues.append(
                    issue("missing_approved_option", "Choice approval must include approved_option_ids.", question_id)
                )
                continue
            valid_option_ids = option_ids_for_question(question)
            unknown_option_ids = [option_id for option_id in approved_option_ids if option_id not in valid_option_ids]
            if unknown_option_ids:
                issues.append(
                    issue(
                        "unknown_option_id",
                        "Manual approval references unknown option_id.",
                        question_id,
                        option_ids=unknown_option_ids,
                    )
                )
                continue
            if question_type in {"single_choice", "dropdown"} and len(approved_option_ids) != 1:
                issues.append(
                    issue(
                        "invalid_option_count",
                        "Single-choice approval must include exactly one option_id.",
                        question_id,
                        option_ids=approved_option_ids,
                    )
                )
                continue
        elif question_type in TEXT_QUESTION_TYPES:
            text_answer = str(approval.get("approved_text_answer", ""))
            if not text_answer:
                issues.append(
                    issue("missing_approved_text_answer", "Text approval must include approved_text_answer.", question_id)
                )
                continue
        else:
            issues.append(
                issue(
                    "unsupported_question_type",
                    "Manual approval cannot resolve this question type in the MVP.",
                    question_id,
                    question_type=question_type,
                )
            )
            continue

        approvals_by_question_id[question_id] = approval

    if global_issue_count:
        approvals_by_question_id = {}

    for qd in decision.get("question_decisions", []):
        question_id = str(qd.get("question_id", ""))
        if qd.get("requires_human_review", True) and question_id not in approvals_by_question_id:
            issues.append(
                issue(
                    "missing_approval",
                    "Required human review question has no valid manual approval.",
                    question_id,
                )
            )

    return approvals_by_question_id, issues, warnings
