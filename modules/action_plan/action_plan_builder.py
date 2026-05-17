from __future__ import annotations

import argparse
from pathlib import Path

from . import action_plan_store
from .action_plan_validator import validate_action_plan
from .schema import action, new_action_plan


HUMAN_REVIEW_TYPES = {"unknown", "matrix", "image", "image_task"}
NAVIGATION_ACTIONS = {"next_page", "continue", "submit"}
ACTION_PLAN_ARTIFACT_PATH = "runtime_state/latest_action_plan.json"
RAW_DECISION_ARTIFACT_PATH = "runtime_state/latest_answer_decision.json"
REVIEWED_DECISION_ARTIFACT_PATH = "runtime_state/latest_reviewed_answer_decision.json"


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


def _question_by_id(page: dict, question_id: str) -> dict:
    for question in page.get("questions", []):
        if question.get("question_id") == question_id:
            return question
    return {}


def _extract_parsed_page(payload: dict) -> dict:
    if isinstance(payload.get("parsed_page"), dict):
        return payload["parsed_page"]
    return payload


def _load_source_parse_page(decision: dict) -> dict:
    source_parse = str(decision.get("source_parse") or "").strip()
    if not source_parse:
        return {}

    source_path = Path(source_parse)
    if source_path.is_absolute():
        candidates = [source_path]
    else:
        candidates = [
            action_plan_store.RUNTIME_DIR.parent / source_path,
            action_plan_store.RUNTIME_DIR / source_path.name,
        ]

    for candidate in candidates:
        if candidate.exists():
            return _extract_parsed_page(action_plan_store.load_json(candidate))
    return {}


def _question_has_options(question: dict) -> bool:
    return bool(question.get("answer_options") or question.get("options"))


def _question_for_decision(page: dict, source_page: dict, question_id: str) -> dict:
    session_question = _question_by_id(page, question_id)
    source_question = _question_by_id(source_page, question_id)
    if _question_has_options(session_question):
        return session_question
    if source_question:
        return source_question
    return session_question


def _option_text(question: dict, option_id: str) -> str:
    for key in ("answer_options", "options"):
        for option in question.get(key, []):
            if option.get("option_id") == option_id:
                return option.get("text") or option.get("option_text", "")
    return ""


def _target(question_id: str, option_id: str = "", option_text: str = "") -> dict:
    target = {"question_id": question_id}
    if option_id:
        target["option_id"] = option_id
    if option_text:
        target["option_text"] = option_text
    return target


def _navigation_target(button: dict) -> dict:
    text = button.get("text") or button.get("label") or ""
    action_name = _normalized_navigation_action(button)
    return {
        "button_id": button.get("button_id", ""),
        "action": action_name,
        "text": text,
    }


def _normalized_navigation_action(button: dict) -> str:
    action_name = str(button.get("action") or "")
    if action_name in NAVIGATION_ACTIONS:
        return action_name
    raw_action = str(button.get("raw_action") or "")
    if raw_action in {"navigate_forward", "next", "continue"}:
        return "continue"
    label = str(button.get("text") or button.get("label") or "").strip().casefold()
    if label in {"next", "continue", "submit"}:
        return "submit" if label == "submit" else "continue"
    return action_name


def _navigation_button(source_page: dict) -> dict:
    buttons = source_page.get("navigation_buttons", [])
    if not isinstance(buttons, list):
        return {}
    for preferred in ("next_page", "continue", "submit"):
        for button in buttons:
            if isinstance(button, dict) and _normalized_navigation_action(button) == preferred:
                return button
    return {}


def _available_options(question: dict) -> list[dict]:
    options = question.get("answer_options", []) or question.get("options", [])
    return [
        {
            "option_id": option.get("option_id", ""),
            "option_text": option.get("text") or option.get("option_text", ""),
        }
        for option in options
    ]


def _review_action(action_id: str, qd: dict, question: dict, reason: str = "") -> dict:
    return action(
        action_id=action_id,
        skill="request_human_review",
        target=_target(qd.get("question_id", "")),
        params={
            "reason": reason
            or qd.get("human_review_reason")
            or "Answer decision requires human review.",
            "available_options": _available_options(question),
        },
        requires_review=True,
    )


def _valid_reviewed_decision(raw_decision: dict) -> tuple[dict | None, dict | None]:
    reviewed_path = action_plan_store.REVIEWED_DECISION_PATH
    review_report_path = action_plan_store.HUMAN_REVIEW_REPORT_PATH
    if not reviewed_path.exists() or not review_report_path.exists():
        return None, None

    reviewed_decision = action_plan_store.load_json(reviewed_path)
    review_report = action_plan_store.load_json(review_report_path)
    if review_report.get("validation_passed") is not True:
        return None, None
    if review_report.get("requires_human_review") is not False:
        return None, None
    if reviewed_decision.get("requires_human_review") is not False:
        return None, None
    if reviewed_decision.get("source_decision_id") != raw_decision.get("decision_id"):
        return None, None
    return reviewed_decision, review_report


def _load_inputs(source: str) -> tuple[dict, dict, dict, dict]:
    session, raw_decision, answer_report = action_plan_store.load_inputs()
    meta = {
        "human_review_applied": False,
        "source_decision_type": "answer_decision",
        "source_decision_path": RAW_DECISION_ARTIFACT_PATH,
        "source_raw_decision_id": raw_decision.get("decision_id", ""),
    }

    if source == "auto":
        reviewed_decision, review_report = _valid_reviewed_decision(raw_decision)
        if reviewed_decision is not None and review_report is not None:
            meta.update(
                {
                    "human_review_applied": True,
                    "source_decision_type": "reviewed_answer_decision",
                    "source_decision_path": REVIEWED_DECISION_ARTIFACT_PATH,
                    "source_raw_decision_id": reviewed_decision.get(
                        "source_decision_id", raw_decision.get("decision_id", "")
                    ),
                }
            )
            return session, reviewed_decision, review_report, meta

    return session, raw_decision, answer_report, meta


def _actions_for_decision(qd: dict, question: dict) -> list[dict]:
    question_id = qd.get("question_id", "")
    question_type = qd.get("question_type") or question.get("question_type", "unknown")

    if question_type == "single_choice":
        option_ids = qd.get("recommended_option_ids", [])
        if option_ids:
            option_id = option_ids[0]
            return [
                action(
                    "a1",
                    "click_option",
                    _target(question_id, option_id, _option_text(question, option_id)),
                )
            ]
    elif question_type == "multiple_choice":
        actions = []
        for index, option_id in enumerate(qd.get("recommended_option_ids", []), start=1):
            actions.append(
                action(
                    f"a{index}",
                    "click_option",
                    _target(question_id, option_id, _option_text(question, option_id)),
                )
            )
        if actions:
            return actions
    elif question_type in {"text_input", "number_input"} and qd.get("recommended_text_answer"):
        return [
            action(
                "a1",
                "type_text",
                _target(question_id),
                params={"text": qd.get("recommended_text_answer", "")},
            )
        ]
    elif question_type == "dropdown":
        option_ids = qd.get("recommended_option_ids", [])
        if option_ids:
            option_id = option_ids[0]
            return [
                action(
                    "a1",
                    "select_dropdown",
                    _target(question_id, option_id, _option_text(question, option_id)),
                )
            ]
    elif question_type in HUMAN_REVIEW_TYPES:
        return [_review_action("a1", qd, question, f"Unsupported question type: {question_type}")]

    return [_review_action("a1", qd, question, "No executable recommendation was available.")]


def build_action_plan(source: str = "auto") -> tuple[dict, dict]:
    session, decision, answer_report, input_meta = _load_inputs(source)
    page = _current_page(session, decision)
    source_page = _load_source_parse_page(decision)

    validation_passed = answer_report.get("validation_passed", False)
    requires_human_review = bool(
        decision.get("requires_human_review") or answer_report.get("requires_human_review")
    )

    if not validation_passed:
        status = "invalid"
        actions = []
        for index, qd in enumerate(decision.get("question_decisions", []), start=1):
            question = _question_for_decision(page, source_page, qd.get("question_id", ""))
            actions.append(_review_action(f"a{index}", qd, question, "Answer decision validation failed."))
    elif decision.get("flow_status") in {"finished", "kicked_out"}:
        status = "no_action"
        actions = []
    elif requires_human_review:
        status = "human_review_required"
        actions = []
        for index, qd in enumerate(decision.get("question_decisions", []), start=1):
            question = _question_for_decision(page, source_page, qd.get("question_id", ""))
            actions.append(_review_action(f"a{index}", qd, question))
    else:
        status = "ready"
        actions = []
        for qd in decision.get("question_decisions", []):
            question = _question_for_decision(page, source_page, qd.get("question_id", ""))
            for built in _actions_for_decision(qd, question):
                built["action_id"] = f"a{len(actions) + 1}"
                actions.append(built)
        button = _navigation_button(source_page)
        if button and not any(item.get("skill") == "request_human_review" for item in actions):
            actions.append(
                action(
                    f"a{len(actions) + 1}",
                    "click_navigation",
                    _navigation_target(button),
                )
            )

    plan = new_action_plan(
        task_id=decision.get("task_id") or session.get("task_id", ""),
        session_id=session.get("session_id", ""),
        source_decision_id=decision.get("decision_id", ""),
        source_session_id=decision.get("session_id", ""),
        status=status,
        actions=actions,
        warnings=list(decision.get("warnings", [])) + list(answer_report.get("warnings", [])),
    )
    plan.update(input_meta)

    report = validate_action_plan(plan)
    request_human_review_count = sum(
        1 for item in plan.get("actions", []) if item.get("skill") == "request_human_review"
    )
    report.update(
        {
            "source_decision_type": input_meta["source_decision_type"],
            "human_review_applied": input_meta["human_review_applied"],
            "decision_requires_human_review": bool(decision.get("requires_human_review")),
            "request_human_review_count": request_human_review_count,
            "executable_action_count": sum(
                1
                for item in plan.get("actions", [])
                if item.get("skill") != "request_human_review"
            ),
            "warnings": list(report.get("warnings", []))
            + list(decision.get("warnings", []))
            + list(answer_report.get("warnings", [])),
            "errors": list(report.get("issues", [])),
        }
    )
    if not report["validation_passed"]:
        plan["status"] = "invalid"

    action_plan_store.save_action_plan(plan)
    _write_action_plan_link(session)
    action_plan_store.save_report(report)
    return plan, report


def _write_action_plan_link(session: dict) -> None:
    pages = session.get("pages", [])
    current_page_index = session.get("current_page_index")
    page = next((item for item in pages if item.get("page_index") == current_page_index), None)
    if page is None and pages:
        page = pages[-1]
    if page is not None:
        page.setdefault("linked_artifacts", {})["action_plan"] = ACTION_PLAN_ARTIFACT_PATH
        action_plan_store.save_json(action_plan_store.SESSION_PATH, session)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build a logical action plan without execution.")
    parser.add_argument("--source", choices=["auto"], default="auto")
    args = parser.parse_args(argv)
    plan, report = build_action_plan(args.source)
    print(
        "Saved runtime_state/latest_action_plan.json "
        f"(status={plan.get('status')}, actions={len(plan.get('actions', []))})."
    )
    print(
        "Saved runtime_state/latest_action_plan_report.json "
        f"(validation_passed={report.get('validation_passed')})."
    )


if __name__ == "__main__":
    main()
