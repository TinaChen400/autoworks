from __future__ import annotations

from .evidence_matcher import is_all_of_the_above


PERSONAL_CATEGORIES = {
    "personal_experience",
    "account_ownership",
    "device_capability",
    "language_proficiency",
    "demographic",
    "preference",
    "screening_question",
}


def _option_by_id(question: dict) -> dict[str, dict]:
    return {option.get("option_id", ""): option for option in question.get("answer_options", [])}


def validate_decision(decision: dict, parsed_page: dict, config: dict, session: dict | None = None) -> dict:
    issues = []
    warnings = []
    question_map = {question.get("question_id", ""): question for question in parsed_page.get("questions", [])}
    threshold = config.get("minimum_confidence_without_review", 0.85)

    for qd in decision.get("question_decisions", []):
        question = question_map.get(qd.get("question_id", ""), {})
        answer_mode = str(qd.get("answer_mode") or "strict_private")
        if qd.get("question_category") in PERSONAL_CATEGORIES:
            has_answer = bool(qd.get("recommended_option_ids") or qd.get("recommended_text_answer"))
            if has_answer and answer_mode == "strict_private" and not qd.get("evidence"):
                issues.append(
                    {
                        "type": "unsupported_personal_claim",
                        "question_id": qd.get("question_id", ""),
                        "message": "Personal answer has no supporting evidence.",
                    }
                )
            if has_answer and answer_mode in {"representative_persona", "professional_judgement"} and not qd.get("basis"):
                issues.append(
                    {
                        "type": "missing_answer_basis",
                        "question_id": qd.get("question_id", ""),
                        "message": "Representative/professional answer has no basis.",
                    }
                )

        options = _option_by_id(question)
        selected_ids = qd.get("recommended_option_ids", [])
        all_selected = [options[option_id] for option_id in selected_ids if is_all_of_the_above(options.get(option_id, {}))]
        if all_selected:
            substantive_count = len([option for option in options.values() if not is_all_of_the_above(option)])
            evidence_text = " ".join(str(item.get("matched_text", "")) for item in qd.get("evidence", []))
            if substantive_count and len({item.get("matched_text", "") for item in qd.get("evidence", [])}) < substantive_count:
                issues.append(
                    {
                        "type": "unsupported_all_of_the_above",
                        "question_id": qd.get("question_id", ""),
                        "message": "'All of the above' lacks evidence for every substantive option.",
                        "evidence_text": evidence_text,
                    }
                )

        if selected_ids and qd.get("confidence", 0.0) < threshold:
            issues.append(
                {
                    "type": "confidence_below_threshold",
                    "question_id": qd.get("question_id", ""),
                    "confidence": qd.get("confidence", 0.0),
                    "threshold": threshold,
                }
            )

        if selected_ids:
            target_ids = {target.get("option_id", "") for target in qd.get("click_targets", [])}
            missing = [option_id for option_id in selected_ids if option_id not in target_ids]
            if missing:
                issues.append(
                    {
                        "type": "missing_click_targets",
                        "question_id": qd.get("question_id", ""),
                        "option_ids": missing,
                    }
                )

    page_confidence = (parsed_page.get("page") or {}).get("confidence", 1.0)
    if page_confidence < 0.8 or parsed_page.get("uncertainties"):
        warnings.append(
            {
                "type": "partial_or_uncertain_parse",
                "message": "Parse confidence is low or uncertainties are present; human review is required.",
            }
        )

    requires_review = bool(issues or warnings or decision.get("requires_human_review", True))
    return {
        "validation_passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "requires_human_review": requires_review,
    }
