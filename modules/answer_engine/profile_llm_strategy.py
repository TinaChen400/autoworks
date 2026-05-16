from __future__ import annotations

import json
import re
from typing import Any

from .answer_context_loader import load_relevant_answer_notes
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
    answer_notes = load_relevant_answer_notes(question)
    options_by_id = _options_by_id(question)
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
        decision["used_answer_notes"] = []
        decision["answer_source"] = "profile_llm_profile_only"
        return decision
    try:
        raw = call_ollama_answerer(
            endpoint=str(config.get("profile_llm_endpoint") or DEFAULT_ENDPOINT),
            model=str(config.get("profile_llm_model") or "qwen2.5:14b"),
            prompt=build_prompt(question, category, profile, session, config, answer_mode, answer_notes),
            timeout_seconds=int(config.get("profile_llm_timeout_seconds", 90)),
            num_predict=int(config.get("profile_llm_num_predict", 512)),
        )
        response = extract_json_object(raw)
        stale_references = _stale_option_references(response, options_by_id)
        if stale_references:
            retry_raw = call_ollama_answerer(
                endpoint=str(config.get("profile_llm_endpoint") or DEFAULT_ENDPOINT),
                model=str(config.get("profile_llm_model") or "qwen2.5:14b"),
                prompt=build_prompt(
                    question,
                    category,
                    profile,
                    session,
                    config,
                    answer_mode,
                    answer_notes,
                    stale_option_ids=stale_references,
                ),
                timeout_seconds=int(config.get("profile_llm_timeout_seconds", 90)),
                num_predict=int(config.get("profile_llm_num_predict", 512)),
            )
            response = extract_json_object(retry_raw)
    except Exception as exc:  # noqa: BLE001 - fall back to human review cleanly.
        decision = question_decision(
            question,
            category,
            "profile_llm_strategy",
            confidence=0.0,
            reason=f"Profile LLM answer failed: {exc}",
            requires_human_review=True,
            human_review_reason="Profile LLM answerer failed.",
        )
        decision["answer_mode"] = answer_mode
        decision["used_answer_notes"] = []
        decision["answer_source"] = "profile_llm_profile_only"
        return decision

    return decision_from_response(question, category, question_type, response, config, answer_mode, answer_notes)


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
    answer_notes: list[dict[str, Any]] | None = None,
    stale_option_ids: list[str] | None = None,
) -> str:
    _ = session
    stale_option_ids = stale_option_ids or []
    payload = {
        "answer_mode": answer_mode,
        "user_profile": profile,
        "external_reference_notes": answer_notes or [],
        "current_page_only": True,
        "retry_context": {
            "is_retry_after_non_current_option_reference": bool(stale_option_ids),
            "rejected_non_current_option_ids": stale_option_ids,
        },
        "answer_policy": {
            "answer_as_user": True,
            "do_not_invent_private_facts": True,
            "strict_private_requires_profile_evidence": True,
            "do_not_use_prior_page_memory": True,
            "option_ids_are_current_page_only": True,
            "reason_basis_and_evidence_must_not_reference_non_current_option_ids": True,
            "representative_persona_may_answer_low_risk_questions": True,
            "professional_judgement_may_use_allowed_professional_range": True,
            "used_answer_notes_must_be_from_external_reference_notes": True,
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
        "For strict_private, use only explicit user_profile evidence; otherwise require human review. "
        "Use only the current question and current answer_options. Do not use prior page memory, old option IDs, or session history. "
        "Use external_reference_notes only when they are relevant, and list only their ids in used_answer_notes. "
        "Do not invent private facts, credentials, exact addresses, named institutions, or medical/financial details. "
        + (
            "This is a retry because your previous response referenced option IDs that do not exist on the current page: "
            f"{', '.join(stale_option_ids)}. Re-answer using only current answer_options and do not mention those IDs anywhere. "
            if stale_option_ids
            else ""
        )
        + "\n\n"
        "Return this shape:\n"
        "{\"answer_mode\":\"representative_persona|professional_judgement|strict_private\","
        "\"recommended_option_ids\":[\"option_id\"],\"recommended_text_answer\":\"\","
        "\"confidence\":0.0,\"basis\":\"...\",\"reason\":\"...\",\"evidence\":[{\"source\":\"user_profile.notes\","
        "\"value\":\"...\",\"matched_text\":\"...\",\"match_type\":\"profile_llm\"}],"
        "\"used_answer_notes\":[\"note_id\"],"
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
    answer_notes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    options_by_id = _options_by_id(question)
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
    used_answer_notes = _used_answer_notes(response.get("used_answer_notes"), answer_notes or [])
    evidence.extend(_note_evidence(used_answer_notes, answer_notes or []))
    answer_mode = _answer_mode(response.get("answer_mode"), default_answer_mode)
    basis = str(response.get("basis") or "").strip()
    requires_review = bool(response.get("requires_human_review", True))
    human_review_reason = str(response.get("human_review_reason") or "")
    stale_references = _stale_option_references(response, options_by_id)
    if stale_references:
        requires_review = True
        human_review_reason = human_review_reason or "Profile LLM referenced non-current option IDs."
        selected_ids = []
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
    decision["used_answer_notes"] = used_answer_notes
    decision["answer_source"] = "profile_llm_with_answer_notes" if used_answer_notes else "profile_llm_profile_only"
    if stale_references:
        decision.setdefault("warnings", []).append(
            "Profile LLM referenced non-current option IDs: " + ", ".join(stale_references)
        )
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


def _options_by_id(question: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(option.get("option_id")): option
        for option in question.get("answer_options", []) or []
        if option.get("option_id")
    }


def _evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        evidence_value = str(item.get("value") or "").strip()
        if source == "session_memory" or source.startswith("session."):
            continue
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


def _used_answer_notes(value: Any, answer_notes: list[dict[str, Any]]) -> list[str]:
    if not isinstance(value, list):
        return []
    allowed = {str(note.get("id") or "") for note in answer_notes}
    used = []
    for item in value:
        note_id = str(item)
        if note_id in allowed and note_id not in used:
            used.append(note_id)
    return used


def _note_evidence(used_answer_notes: list[str], answer_notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    notes_by_id = {str(note.get("id") or ""): note for note in answer_notes}
    evidence = []
    for note_id in used_answer_notes:
        note = notes_by_id.get(note_id)
        if not note:
            continue
        evidence.append(
            {
                "source": "answer_notes",
                "id": note_id,
                "value": str(note.get("text") or ""),
                "matched_text": note_id,
                "match_type": "answer_note",
            }
        )
    return evidence


def _stale_option_references(response: dict[str, Any], options_by_id: dict[str, dict[str, Any]]) -> list[str]:
    current_ids = set(options_by_id)
    text_parts = [
        str(response.get("reason") or ""),
        str(response.get("basis") or ""),
    ]
    for item in response.get("evidence", []) if isinstance(response.get("evidence"), list) else []:
        if not isinstance(item, dict):
            continue
        text_parts.extend(
            [
                str(item.get("value") or ""),
                str(item.get("matched_text") or ""),
            ]
        )
    text = " ".join(text_parts)
    prefixes = {
        match.group(1)
        for option_id in current_ids
        for match in [re.match(r"^([A-Za-z]{1,3})\d+$", option_id)]
        if match
    }
    if not prefixes:
        return []
    referenced = set()
    for prefix in prefixes:
        referenced.update(re.findall(rf"\b{re.escape(prefix)}\d+\b", text))
    return sorted(option_id for option_id in referenced if option_id not in current_ids)


def _confidence(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        return 0.0


def _answer_mode(value: Any, default: str) -> str:
    answer_mode = str(value or default)
    return answer_mode if answer_mode in ANSWER_MODES else default
