from __future__ import annotations

import json
from typing import Any

from .ollama_answer_client import call_ollama_answerer, extract_json_object
from .question_classifier import classify_category
from .schema import click_target_from_option, get_question_text, question_decision
from .strategies.multiple_choice_strategy import PERSONAL_CATEGORIES


SUPPORTED_TYPES = {"single_choice", "multiple_choice", "text_input", "number_input"}
DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/generate"
ANSWER_MODES = {"representative_persona", "professional_judgement", "strict_private"}


def should_use_profile_llm(config: dict[str, Any], question_type: str) -> bool:
    if not bool(config.get("allow_profile_llm_answerer", False)):
        return False
    allowed = set(config.get("profile_llm_supported_question_types", list(SUPPORTED_TYPES)))
    return question_type in SUPPORTED_TYPES and question_type in allowed


def decide(
    question: dict[str, Any],
    category: str,
    profile: dict[str, Any],
    profile_exists: bool,
    session: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    question_type = str(question.get("question_type") or "unknown")
    answer_mode = determine_answer_mode(question, category, profile)
    if not profile_exists and answer_mode == "strict_private":
        decision = question_decision(
            question,
            category,
            "profile_llm_strategy",
            confidence=0.0,
            reason="Strict private answer requires user_profile.json.",
            missing_information=["user_profile.json"],
            requires_human_review=True,
            human_review_reason="Strict private answer requires user_profile.json.",
            warnings=["user_profile missing"],
        )
        decision["answer_mode"] = answer_mode
        return decision
    try:
        raw = call_ollama_answerer(
            endpoint=str(config.get("profile_llm_endpoint") or DEFAULT_ENDPOINT),
            model=str(config.get("profile_llm_model") or "qwen2.5:14b"),
            prompt=build_prompt(question, category, profile, session, config, answer_mode),
            timeout_seconds=int(config.get("profile_llm_timeout_seconds", 90)),
            num_predict=int(config.get("profile_llm_num_predict", 512)),
        )
        response = extract_json_object(raw)
    except Exception as exc:  # noqa: BLE001 - fall back to human review cleanly.
        return question_decision(
            question,
            category,
            "profile_llm_strategy",
            confidence=0.0,
            reason=f"Profile LLM answer failed: {exc}",
            requires_human_review=True,
            human_review_reason="Profile LLM answerer failed.",
        )

    return decision_from_response(question, category, question_type, response, config, answer_mode)


def determine_answer_mode(question: dict[str, Any], category: str, profile: dict[str, Any]) -> str:
    text = f"{get_question_text(question)} " + " ".join(
        str(option.get("text") or "") for option in question.get("answer_options", []) or []
    )
    normalized = text.casefold()
    policy = dict(profile.get("answering_mode_policy") or {})
    strict_terms = [
        str(item).casefold()
        for item in (
            policy.get("strict_private_requires_review")
            or [
                "password",
                "login credentials",
                "bank details",
                "government id",
                "medical diagnosis",
                "exact address",
                "phone number",
                "email address",
            ]
        )
    ]
    if any(term and term in normalized for term in strict_terms):
        return "strict_private"

    identity_policy = dict(profile.get("professional_identity_policy") or {})
    asks_research_identity = any(
        term in normalized
        for term in (
            "researcher",
            "research",
            "research institution",
            "university",
            "lab",
            "laboratory",
            "employer",
            "organisation",
            "organization",
        )
    )
    requires_named_org = any(
        term in normalized
        for term in (
            "which university",
            "which organisation",
            "which organization",
            "which company",
            "name of your employer",
            "name your employer",
            "specific institution",
        )
    )
    if asks_research_identity:
        if requires_named_org:
            return "strict_private"
        if bool(identity_policy.get("allow_representative_professional_identity", False)):
            return "professional_judgement"

    professional_domains = [
        str(item).casefold()
        for item in (
            policy.get("professional_domains")
            or (profile.get("professional_persona") or {}).get("domains")
            or []
        )
    ]
    if category == "objective_task" and any(domain and domain in normalized for domain in professional_domains):
        return "professional_judgement"
    return str(policy.get("default_answer_mode") or "representative_persona")


def build_prompt(
    question: dict[str, Any],
    category: str,
    profile: dict[str, Any],
    session: dict[str, Any] | None,
    config: dict[str, Any],
    answer_mode: str,
) -> str:
    payload = {
        "answer_mode": answer_mode,
        "user_profile": profile,
        "session_memory": _compact_session(session),
        "answer_policy": {
            "answer_as_user": True,
            "do_not_invent_private_facts": True,
            "strict_private_requires_profile_evidence": True,
            "representative_persona_may_answer_low_risk_questions": True,
            "professional_judgement_may_use_allowed_professional_range": True,
            "tone": config.get("answer_tone", "honest, concise, natural"),
            "language": config.get("language", "English"),
            "style": config.get("style", "simple British English"),
        },
        "question": {
            "question_id": question.get("question_id", ""),
            "question_type": question.get("question_type", "unknown"),
            "question_category": category,
            "question_text": get_question_text(question),
            "answer_options": [
                {
                    "option_id": option.get("option_id", ""),
                    "text": option.get("text", ""),
                }
                for option in question.get("answer_options", []) or []
            ],
        },
    }
    return (
        "You answer survey/form questions according to answer_mode. Return ONLY valid JSON. "
        "For representative_persona, answer as a plausible mainstream practical consumer using the provided principles. "
        "For professional_judgement, answer from the allowed professional range without claiming named employers, universities, or institutions. "
        "For strict_private, use only explicit true_profile_facts/session evidence; otherwise require human review. "
        "Do not invent private facts, credentials, exact addresses, named institutions, or medical/financial details.\n\n"
        "Return this shape:\n"
        "{\"answer_mode\":\"representative_persona|professional_judgement|strict_private\","
        "\"recommended_option_ids\":[\"option_id\"],\"recommended_text_answer\":\"\","
        "\"confidence\":0.0,\"basis\":\"...\",\"reason\":\"...\",\"evidence\":[{\"source\":\"user_profile.notes\","
        "\"value\":\"...\",\"matched_text\":\"...\",\"match_type\":\"profile_llm\"}],"
        "\"requires_human_review\":false,\"human_review_reason\":\"\"}\n\n"
        "Input JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def decision_from_response(
    question: dict[str, Any],
    category: str,
    question_type: str,
    response: dict[str, Any],
    config: dict[str, Any],
    default_answer_mode: str = "representative_persona",
) -> dict[str, Any]:
    options_by_id = {
        str(option.get("option_id")): option
        for option in question.get("answer_options", []) or []
        if option.get("option_id")
    }
    selected_ids = _selected_option_ids(response.get("recommended_option_ids"), options_by_id)
    if question_type == "single_choice":
        selected_ids = selected_ids[:1]
    text_answer = str(response.get("recommended_text_answer") or "").strip()
    if question_type in {"single_choice", "multiple_choice"}:
        text_answer = ""
    if question_type in {"text_input", "number_input"}:
        selected_ids = []

    confidence = _confidence(response.get("confidence"))
    evidence = _evidence(response.get("evidence"))
    answer_mode = _answer_mode(response.get("answer_mode"), default_answer_mode)
    basis = str(response.get("basis") or "").strip()
    requires_review = bool(response.get("requires_human_review", True))
    human_review_reason = str(response.get("human_review_reason") or "")
    if answer_mode == "strict_private" and category in PERSONAL_CATEGORIES and not evidence:
        requires_review = True
        human_review_reason = human_review_reason or "Profile LLM answer has no supporting evidence."
    if answer_mode in {"representative_persona", "professional_judgement"} and not basis:
        requires_review = True
        human_review_reason = human_review_reason or "Profile LLM answer has no representative/professional basis."
    if selected_ids and confidence < float(config.get("minimum_confidence_without_review", 0.85)):
        requires_review = True
        human_review_reason = human_review_reason or "Confidence below threshold."
    if question_type in {"text_input", "number_input"} and not text_answer:
        requires_review = True
        human_review_reason = human_review_reason or "Text answer is empty."
    if question_type in {"single_choice", "multiple_choice"} and not selected_ids:
        requires_review = True
        human_review_reason = human_review_reason or "No valid option_id was selected."

    selected_options = [options_by_id[option_id] for option_id in selected_ids if option_id in options_by_id]
    decision = question_decision(
        question,
        category,
        "profile_llm_strategy",
        recommended_option_ids=selected_ids,
        recommended_text_answer=text_answer,
        confidence=confidence,
        reason=str(response.get("reason") or "Profile LLM selected an answer."),
        evidence=evidence,
        requires_human_review=requires_review,
        human_review_reason=human_review_reason,
        click_targets=[click_target_from_option(option) for option in selected_options],
    )
    decision["answer_mode"] = answer_mode
    decision["basis"] = basis
    return decision


def _selected_option_ids(value: Any, options_by_id: dict[str, dict[str, Any]]) -> list[str]:
    if not isinstance(value, list):
        return []
    selected = []
    for item in value:
        option_id = str(item)
        if option_id in options_by_id and option_id not in selected:
            selected.append(option_id)
    return selected


def _evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        evidence_value = str(item.get("value") or "").strip()
        if source and evidence_value:
            result.append(
                {
                    "source": source,
                    "value": evidence_value,
                    "matched_text": str(item.get("matched_text") or evidence_value),
                    "match_type": str(item.get("match_type") or "profile_llm"),
                }
            )
    return result


def _confidence(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        return 0.0


def _answer_mode(value: Any, default: str) -> str:
    answer_mode = str(value or default)
    return answer_mode if answer_mode in ANSWER_MODES else default


def _compact_session(session: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(session, dict):
        return {}
    return {
        "session_id": session.get("session_id", ""),
        "current_page_index": session.get("current_page_index", 0),
        "consistency_memory": session.get("consistency_memory", []),
    }
