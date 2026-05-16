from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from modules.parse_orchestrator.input_loader import write_json
from modules.parse_orchestrator.vision_runner import PARSED_PAGE_PATH, VALIDATION_REPORT_PATH
from modules.vision_parser.response_validator import ValidationError, validate_parsed_page_with_report
from modules.vision_parser.schema import empty_bbox


OPTION_RELATIONSHIPS = {
    "possible_option_label",
    "text_labels_element",
    "text_inside_element",
    "nearby_text",
}
OLLAMA_EVIDENCE_DEBUG_PATH = "runtime_state/latest_ollama_evidence_debug.json"


@dataclass
class OllamaEvidenceResult:
    parsed_page: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)
    model_calls_count: int = 0
    validation_passed: bool = False
    warnings: list[str] = field(default_factory=list)
    error: str = ""


def run_ollama_evidence_parse(
    plan: dict[str, Any],
    layout_index: dict[str, Any],
    runtime_context: dict[str, Any],
    config: dict[str, Any],
) -> OllamaEvidenceResult:
    evidence = build_evidence_payload(layout_index, runtime_context, config, plan)
    warnings: list[str] = []
    if not evidence["option_candidates"]:
        warnings.append("Ollama evidence parse found no text-control option candidates.")

    model_config = dict(config.get("ollama_evidence_parse") or {})
    model = str(model_config.get("model") or config.get("ollama_model") or "qwen2.5:14b")
    endpoint = str(
        model_config.get("endpoint")
        or config.get("ollama_endpoint")
        or "http://127.0.0.1:11434/api/generate"
    )
    timeout_seconds = int(model_config.get("timeout_seconds") or config.get("ollama_timeout_seconds") or 90)
    prompt = build_prompt(evidence, plan, runtime_context)
    _write_debug(
        {
            "model": model,
            "endpoint": endpoint,
            "prompt": prompt,
            "evidence": evidence,
        }
    )
    try:
        raw_response = call_ollama(
            endpoint=endpoint,
            model=model,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            num_predict=int(model_config.get("num_predict") or 512),
        )
    except Exception as exc:  # noqa: BLE001 - keep orchestrator fallback path available.
        _write_debug(
            {
                "model": model,
                "endpoint": endpoint,
                "prompt": prompt,
                "evidence": evidence,
                "error": str(exc),
            }
        )
        report = _validation_error_report("ollama_request_failed", str(exc))
        write_json(VALIDATION_REPORT_PATH, report)
        return OllamaEvidenceResult(
            validation_report=report,
            model_calls_count=1,
            warnings=warnings,
            error=f"Ollama evidence parse failed: {exc}",
        )

    try:
        _write_debug(
            {
                "model": model,
                "endpoint": endpoint,
                "prompt": prompt,
                "evidence": evidence,
                "raw_response": raw_response,
            }
        )
        parsed_from_compact = parsed_page_from_compact_response(raw_response, evidence, runtime_context)
        raw_for_validation = json.dumps(parsed_from_compact, ensure_ascii=False)
        parsed, validation = validate_parsed_page_with_report(
            raw_for_validation,
            runtime_context,
            output_level="light",
        )
        id_report = validate_grounded_ids(parsed, layout_index)
        validation["warnings"].extend(id_report["warnings"])
        validation["info"].extend(id_report["info"])
        validation["normalization_applied"].extend(id_report["normalization_applied"])
        if id_report["errors"]:
            validation["validation_passed"] = False
            validation["errors"].extend(id_report["errors"])
    except ValidationError as exc:
        validation = getattr(exc, "report", None) or _validation_error_report(
            "ollama_response_invalid",
            str(exc),
        )
        parsed = {}
        _write_debug(
            {
                "model": model,
                "endpoint": endpoint,
                "prompt": prompt,
                "evidence": evidence,
                "raw_response": raw_response,
                "validation_report": validation,
            }
        )
        write_json(VALIDATION_REPORT_PATH, validation)
        return OllamaEvidenceResult(
            parsed_page=parsed,
            validation_report=validation,
            model_calls_count=1,
            validation_passed=False,
            warnings=warnings,
            error=f"Ollama evidence parse returned invalid JSON: {exc}",
        )

    parsed.setdefault("metadata", {})
    parsed["metadata"].update(
        {
            "source": "ollama_evidence_parse",
            "model": model,
            "evidence_text_count": len(evidence["texts"]),
            "evidence_option_candidate_count": len(evidence["option_candidates"]),
        }
    )
    write_json(PARSED_PAGE_PATH, parsed)
    write_json(VALIDATION_REPORT_PATH, validation)
    return OllamaEvidenceResult(
        parsed_page=parsed,
        validation_report=validation,
        model_calls_count=1,
        validation_passed=bool(validation.get("validation_passed")),
        warnings=warnings,
    )


def build_evidence_payload(
    layout_index: dict[str, Any],
    runtime_context: dict[str, Any],
    config: dict[str, Any],
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    max_text_blocks = int(config.get("ollama_evidence_max_text_blocks", 90))
    selected_region_ids = {
        str(region_id)
        for region_id in ((plan or {}).get("selected_region_ids") or [])
        if str(region_id)
    }
    text_by_id = {
        str(text.get("text_id")): text
        for text in layout_index.get("text_blocks", []) or []
        if isinstance(text, dict) and text.get("text_id")
    }
    element_by_id = {
        str(element.get("element_id")): element
        for element in layout_index.get("elements", []) or []
        if isinstance(element, dict) and element.get("element_id")
    }
    option_candidates = []
    seen_pairs: set[tuple[str, str]] = set()
    for relationship in layout_index.get("relationships", []) or []:
        if not isinstance(relationship, dict):
            continue
        rel_type = str(relationship.get("relationship_type") or "")
        if rel_type not in OPTION_RELATIONSHIPS:
            continue
        text_id = str(relationship.get("source_id") or "")
        element_id = str(relationship.get("target_id") or "")
        if text_id not in text_by_id or element_id not in element_by_id:
            continue
        pair = (text_id, element_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        text = text_by_id[text_id]
        element = element_by_id[element_id]
        option_candidates.append(
            {
                "text_id": text_id,
                "text": _clean_text(str(text.get("text") or "")),
                "control_element_id": element_id,
                "control_type": str(
                    element.get("element_type_hint")
                    or element.get("control_type")
                    or "unknown"
                ),
                "relationship_type": rel_type,
                "confidence": round(float(relationship.get("confidence") or 0.0), 3),
                "text_bbox_norm": text.get("bbox_norm") or empty_bbox(),
                "control_click_point_norm": element.get("click_point_norm") or {},
            }
        )

    text_rows = [
        {
            "text_id": text_id,
            "text": _clean_text(str(text.get("text") or "")),
            "bbox_norm": text.get("bbox_norm") or empty_bbox(),
            "associated_element_id": str(text.get("associated_element_id") or ""),
            "region_id": str(text.get("associated_region_id") or ""),
        }
        for text_id, text in text_by_id.items()
        if _clean_text(str(text.get("text") or ""))
    ]
    text_rows.sort(key=lambda item: (float((item["bbox_norm"] or {}).get("y") or 0.0), float((item["bbox_norm"] or {}).get("x") or 0.0)))
    return {
        "task_id": str(runtime_context.get("task_id") or ""),
        "task_type": str(runtime_context.get("task_type") or ""),
        "layout_hints": layout_index.get("layout_hints") or {},
        "texts": text_rows[:max_text_blocks],
        "option_candidates": option_candidates,
    }


def build_prompt(
    evidence: dict[str, Any],
    plan: dict[str, Any],
    runtime_context: dict[str, Any],
) -> str:
    compact = {
        "task_id": evidence.get("task_id") or plan.get("task_id") or runtime_context.get("task_id") or "",
        "parser_type_hint": plan.get("selected_parser_type", "general"),
        "layout_hints": {
            "possible_page_types": (evidence.get("layout_hints") or {}).get("possible_page_types", []),
            "detector_scores": (evidence.get("layout_hints") or {}).get("detector_scores", {}),
        },
        "texts": evidence.get("texts", []),
        "option_candidates": evidence.get("option_candidates", []),
    }
    return (
        "You are a fast UI page understanding parser. Use ONLY the provided OCR and "
        "text-control evidence. Return ONLY valid compact JSON, no markdown. Preserve "
        "source text_id values exactly. Do not invent IDs. Ignore browser chrome, "
        "debug labels, and unrelated UI text.\n\n"
        "Return exactly this compact JSON shape:\n"
        "{\"page_type\":\"questionnaire|form|unknown\",\"question_type\":\"single_choice|multiple_choice|text_input|unknown\","
        "\"question_text_ids\":[\"T1\"],\"option_text_ids\":[\"T2\"],\"confidence\":0.0,"
        "\"uncertainties\":[{\"type\":\"...\",\"message\":\"...\"}]}\n\n"
        "Rules:\n"
        "- Put instruction/question text IDs in question_text_ids.\n"
        "- Put only real answer option text IDs in option_text_ids.\n"
        "- Prefer option_candidates with relationship_type=possible_option_label for answer options.\n"
        "- Include every real answer option in the same visible answer group, including lower-confidence nearby_text candidates.\n"
        "- Do not include text IDs for concept body text, free-text fields, window titles, or close buttons.\n\n"
        "Evidence JSON:\n"
        f"{json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}"
    )


def parsed_page_from_compact_response(
    raw_response: str,
    evidence: dict[str, Any],
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    compact = _extract_json_object(raw_response)
    compact = _normalize_compact_response(compact, evidence)
    text_by_id = {str(item.get("text_id")): item for item in evidence.get("texts", []) if item.get("text_id")}
    option_by_text_id = {
        str(item.get("text_id")): item
        for item in evidence.get("option_candidates", [])
        if item.get("text_id")
    }
    question_text_ids = _valid_ids(compact.get("question_text_ids"), text_by_id)
    option_text_ids = _expand_option_ids(
        _valid_ids(compact.get("option_text_ids"), option_by_text_id),
        option_by_text_id,
    )
    if not option_text_ids:
        raise ValidationError("Ollama compact parse did not return grounded option_text_ids.")

    question_groups = _infer_yes_no_question_groups_from_evidence(evidence)
    duplicate_yes_no_cards = _has_duplicate_yes_no_card_questions(evidence)
    if question_groups:
        return _parsed_page_from_question_groups(
            compact,
            question_groups,
            evidence,
            runtime_context,
            requires_review=True,
        )

    stem_texts = [text_by_id[text_id]["text"] for text_id in question_text_ids if text_id in text_by_id]
    stem_bbox = _union_bbox([text_by_id[text_id].get("bbox_norm") for text_id in question_text_ids])
    options = []
    for text_id in option_text_ids:
        source = option_by_text_id[text_id]
        control_type = str(source.get("control_type") or "unknown")
        option_text = _clean_option_text(str(source.get("text") or ""))
        options.append(
            {
                "option_id": text_id,
                "text": option_text,
                "raw_text": str(source.get("text") or ""),
                "option_type": "text_option",
                "selection_control": _selection_control_from_type(
                    str(compact.get("question_type") or ""),
                    control_type,
                ),
                "control_element_id": str(source.get("control_element_id") or ""),
                "control_type": control_type,
                "bbox_norm": source.get("text_bbox_norm") or empty_bbox(),
                "control_click_point_norm": source.get("control_click_point_norm") or {},
            }
        )

    uncertainties = compact.get("uncertainties") if isinstance(compact.get("uncertainties"), list) else []
    if duplicate_yes_no_cards:
        uncertainties = list(uncertainties) + [
            {
                "type": "duplicate_yes_no_card_stack",
                "message": "Repeated Yes/No card questions were visible; active card selection requires human review.",
            }
        ]
    confidence = _effective_confidence(compact.get("confidence"), bool(stem_texts), bool(options))
    return {
        "task_id": str(runtime_context.get("task_id") or evidence.get("task_id") or ""),
        "page": {
            "page_type": _enum_or_default(str(compact.get("page_type") or ""), {"questionnaire", "form"}, "unknown"),
            "language": "en",
            "page_status": "active_question_page",
            "confidence": confidence,
        },
        "questions": [
            {
                "question_id": "q1",
                "question_type": _enum_or_default(
                    str(compact.get("question_type") or ""),
                    {"single_choice", "multiple_choice", "text_input", "unknown"},
                    "unknown",
                ),
                "question_stem": {
                    "text": " ".join(stem_texts).strip(),
                    "bbox_norm": stem_bbox,
                },
                "instructions": [],
                "answer_options": options,
                "input_fields": [],
                "media": [],
                "matrix": None,
                "confidence": confidence,
                "requires_human_review": duplicate_yes_no_cards,
            }
        ],
        "navigation_buttons": [],
        "uncertainties": [
            item
            for item in uncertainties
            if isinstance(item, dict) and item.get("type") and item.get("message")
        ],
        "requires_human_review": duplicate_yes_no_cards,
    }


def _parsed_page_from_question_groups(
    compact: dict[str, Any],
    question_groups: list[dict[str, list[str]]],
    evidence: dict[str, Any],
    runtime_context: dict[str, Any],
    requires_review: bool = False,
) -> dict[str, Any]:
    text_by_id = {str(item.get("text_id")): item for item in evidence.get("texts", []) if item.get("text_id")}
    option_by_text_id = {
        str(item.get("text_id")): item
        for item in evidence.get("option_candidates", [])
        if item.get("text_id")
    }
    questions = []
    for index, group in enumerate(question_groups, start=1):
        question_text_ids = _valid_ids(group.get("question_text_ids"), text_by_id)
        option_text_ids = _valid_ids(group.get("option_text_ids"), option_by_text_id)
        stem_texts = [text_by_id[text_id]["text"] for text_id in question_text_ids if text_id in text_by_id]
        options = []
        for text_id in option_text_ids:
            source = option_by_text_id[text_id]
            control_type = str(source.get("control_type") or "unknown")
            options.append(
                {
                    "option_id": text_id,
                    "text": _clean_option_text(str(source.get("text") or "")),
                    "raw_text": str(source.get("text") or ""),
                    "option_type": "text_option",
                    "selection_control": _selection_control_from_type(
                        str(compact.get("question_type") or "single_choice"),
                        control_type,
                    ),
                    "control_element_id": str(source.get("control_element_id") or ""),
                    "control_type": control_type,
                    "bbox_norm": source.get("text_bbox_norm") or empty_bbox(),
                    "control_click_point_norm": source.get("control_click_point_norm") or {},
                }
            )
        confidence = _effective_confidence(compact.get("confidence"), bool(stem_texts), bool(options))
        questions.append(
            {
                "question_id": f"q{index}",
                "question_type": "single_choice",
                "question_stem": {
                    "text": " ".join(stem_texts).strip(),
                    "bbox_norm": _union_bbox([text_by_id[text_id].get("bbox_norm") for text_id in question_text_ids]),
                },
                "instructions": [],
                "answer_options": options,
                "input_fields": [],
                "media": [],
                "matrix": None,
                "confidence": confidence,
                "requires_human_review": requires_review,
            }
        )
    confidence = min([question["confidence"] for question in questions] or [0.0])
    return {
        "task_id": str(runtime_context.get("task_id") or evidence.get("task_id") or ""),
        "page": {
            "page_type": "questionnaire",
            "language": "en",
            "page_status": "active_question_page",
            "confidence": confidence,
        },
        "questions": questions,
        "navigation_buttons": [],
        "uncertainties": [
            {
                "type": "model_format_repair",
                "message": "Recovered repeated Yes/No question groups from grounded OCR evidence.",
            }
        ]
        + (
            [
                {
                    "type": "duplicate_yes_no_card_stack",
                    "message": "Repeated Yes/No card questions were visible; active card selection requires human review.",
                }
            ]
            if requires_review
            else []
        ),
        "requires_human_review": requires_review,
    }


def _normalize_compact_response(compact: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    if _valid_ids(
        compact.get("option_text_ids"),
        {
            str(item.get("text_id")): item
            for item in evidence.get("option_candidates", [])
            if item.get("text_id")
        },
    ):
        return compact
    inferred = _infer_yes_no_compact_from_evidence(evidence)
    if not inferred:
        inferred = _infer_single_choice_compact_from_evidence(evidence)
    if not inferred:
        return compact
    normalized = dict(compact)
    normalized.setdefault("page_type", "questionnaire")
    normalized.setdefault("question_type", "single_choice")
    normalized.setdefault("confidence", 0.65)
    normalized.setdefault(
        "uncertainties",
        [
            {
                "type": "model_format_repair",
                "message": "Recovered answer ids from grounded OCR evidence after compact response drift.",
            }
        ],
    )
    normalized["question_text_ids"] = inferred["question_text_ids"]
    normalized["option_text_ids"] = inferred["option_text_ids"]
    return normalized


def _infer_yes_no_compact_from_evidence(evidence: dict[str, Any]) -> dict[str, list[str]] | None:
    groups = _infer_yes_no_question_groups_from_evidence(evidence)
    if groups:
        return groups[0]
    return None


def _infer_single_choice_compact_from_evidence(evidence: dict[str, Any]) -> dict[str, list[str]] | None:
    text_by_id = {
        str(item.get("text_id")): item
        for item in evidence.get("texts", [])
        if isinstance(item, dict) and item.get("text_id")
    }
    option_by_text_id = {
        str(item.get("text_id")): item
        for item in evidence.get("option_candidates", [])
        if isinstance(item, dict) and item.get("text_id")
    }
    candidates = []
    for text_id, item in option_by_text_id.items():
        if text_id not in text_by_id or not _looks_like_single_choice_option_candidate(item):
            continue
        y = _bbox_y(item.get("text_bbox_norm"))
        x = _bbox_x(item.get("text_bbox_norm"))
        if y is None or x is None:
            continue
        width = _bbox_width(item.get("text_bbox_norm")) or 0.0
        candidates.append((y, x, width, text_id))
    candidates = _remove_concept_body_candidates(candidates, text_by_id, option_by_text_id)
    option_ids = _best_vertical_choice_group(candidates)
    if len(option_ids) < 2:
        return None

    option_top = min(
        _bbox_y((option_by_text_id.get(text_id) or {}).get("text_bbox_norm")) or 1.0
        for text_id in option_ids
    )
    question_ids = _single_choice_question_ids_before_options(text_by_id, option_ids, option_top)
    if not question_ids:
        return None
    return {"question_text_ids": question_ids, "option_text_ids": option_ids}


def _infer_yes_no_question_groups_from_evidence(evidence: dict[str, Any]) -> list[dict[str, list[str]]]:
    text_by_id = {
        str(item.get("text_id")): item
        for item in evidence.get("texts", [])
        if isinstance(item, dict) and item.get("text_id")
    }
    candidates = []
    for item in evidence.get("option_candidates", []):
        if not isinstance(item, dict) or not _looks_like_answer_option(item):
            continue
        label = _normalized_yes_no_label(str(item.get("text") or ""))
        if label not in {"yes", "no"}:
            continue
        y = _bbox_y(item.get("text_bbox_norm"))
        x = _bbox_x(item.get("text_bbox_norm"))
        if y is None or x is None:
            continue
        region_id = _region_for_text_id(text_by_id, str(item.get("text_id") or ""))
        candidates.append((str(item.get("text_id") or ""), label, x, y, region_id))
    candidates.sort(key=lambda item: (item[3], item[2]))
    groups = []
    used_option_ids: set[str] = set()
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if {left[1], right[1]} != {"yes", "no"}:
                continue
            if left[4] and right[4] and left[4] != right[4]:
                continue
            if abs(left[2] - right[2]) > 0.08 or abs(left[3] - right[3]) > 0.08:
                continue
            option_ids = [left[0], right[0]]
            if any(text_id in used_option_ids for text_id in option_ids):
                continue
            option_top = min(left[3], right[3])
            question_ids = _question_ids_before_options(text_by_id, option_ids, option_top)
            if question_ids:
                used_option_ids.update(option_ids)
                groups.append({"question_text_ids": question_ids, "option_text_ids": option_ids})
    return groups


def _has_duplicate_yes_no_card_questions(evidence: dict[str, Any]) -> bool:
    text_rows = []
    yes_no_rows = []
    for item in evidence.get("texts", []):
        if not isinstance(item, dict):
            continue
        text_id = str(item.get("text_id") or "")
        text = _clean_text(str(item.get("text") or ""))
        y = _bbox_y(item.get("bbox_norm"))
        if not text_id or y is None:
            continue
        row = {
            "text_id": text_id,
            "text": text,
            "normalized": _letters_only(text),
            "y": y,
            "region_id": str(item.get("region_id") or ""),
        }
        if _normalized_yes_no_label(text) in {"yes", "no"}:
            yes_no_rows.append(row)
        elif _looks_like_yes_no_question_text(text):
            text_rows.append(row)

    seen_questions: dict[str, int] = {}
    for row in text_rows:
        region_id = row["region_id"]
        has_nearby_yes_no = any(
            (not region_id or not yn["region_id"] or yn["region_id"] == region_id)
            and 0 < yn["y"] - row["y"] <= 0.18
            for yn in yes_no_rows
        )
        if has_nearby_yes_no:
            key = row["normalized"]
            seen_questions[key] = seen_questions.get(key, 0) + 1
    return any(count > 1 for count in seen_questions.values())


def _looks_like_yes_no_question_text(value: str) -> bool:
    normalized = _letters_only(value)
    if not normalized or _looks_like_stop_text(value):
        return False
    return (
        normalized.startswith("doyou")
        or "benefitsdecisionprocess" in normalized
        or "placeofemployment" in normalized
        or "planponsor" in normalized
        or "plansponsor" in normalized
        or "hrorbenefitsmanager" in normalized
    )


def _region_for_text_id(text_by_id: dict[str, dict[str, Any]], text_id: str) -> str:
    return str((text_by_id.get(text_id) or {}).get("region_id") or "")


def _question_ids_before_options(
    text_by_id: dict[str, dict[str, Any]],
    option_ids: list[str],
    option_top: float,
) -> list[str]:
    option_regions = {
        str((text_by_id.get(text_id) or {}).get("region_id") or "")
        for text_id in option_ids
    }
    option_regions.discard("")
    rows = []
    for text_id, item in text_by_id.items():
        if text_id in option_ids:
            continue
        if option_regions and str(item.get("region_id") or "") not in option_regions:
            continue
        y = _bbox_y(item.get("bbox_norm"))
        if y is None or y >= option_top or y < option_top - 0.18:
            continue
        text = _clean_text(str(item.get("text") or ""))
        if not text or _normalized_yes_no_label(text) in {"yes", "no"}:
            continue
        rows.append((y, text_id))
    rows.sort()
    return [text_id for _, text_id in rows[-4:]]


def _single_choice_question_ids_before_options(
    text_by_id: dict[str, dict[str, Any]],
    option_ids: list[str],
    first_option_top: float,
) -> list[str]:
    rows = []
    for text_id, item in text_by_id.items():
        if text_id in option_ids:
            continue
        y = _bbox_y(item.get("bbox_norm"))
        if y is None or y >= first_option_top or y < first_option_top - 0.28:
            continue
        text = str(item.get("text") or "")
        if _looks_like_question_context_text(text):
            rows.append((y, text_id))
    rows.sort()
    return [text_id for _, text_id in rows[-4:]]


def _best_vertical_choice_group(candidates: list[tuple[float, float, float, str]]) -> list[str]:
    if len(candidates) < 2:
        return []
    candidates = sorted(candidates)
    best: list[tuple[float, float, float, str]] = []
    for start_index, start in enumerate(candidates):
        group = [start]
        expected_x = start[1]
        previous_y = start[0]
        for candidate in candidates[start_index + 1 :]:
            y, x, _width, text_id = candidate
            if y - previous_y > 0.12:
                break
            if abs(x - expected_x) > 0.08:
                continue
            if text_id in {item[3] for item in group}:
                continue
            group.append(candidate)
            previous_y = y
            expected_x = sum(item[1] for item in group) / len(group)
        if _vertical_group_score(group) > _vertical_group_score(best):
            best = group
    if len(best) < 2:
        return []
    return [text_id for _y, _x, _width, text_id in sorted(best)]


def _remove_concept_body_candidates(
    candidates: list[tuple[float, float, float, str]],
    text_by_id: dict[str, dict[str, Any]],
    option_by_text_id: dict[str, dict[str, Any]],
) -> list[tuple[float, float, float, str]]:
    concept_tops = [
        _bbox_y(item.get("bbox_norm"))
        for item in text_by_id.values()
        if _letters_only(str(item.get("text") or "")).startswith("concept")
    ]
    concept_tops = [value for value in concept_tops if value is not None]
    if not concept_tops:
        return candidates
    concept_top = min(concept_tops)
    explicit_tops = [
        y
        for y, _x, _width, text_id in candidates
        if y > concept_top
        and _looks_like_explicit_choice_label(
            str((option_by_text_id.get(text_id) or {}).get("text") or "")
        )
    ]
    if not explicit_tops:
        return candidates
    first_explicit_option_top = min(explicit_tops)
    return [
        candidate
        for candidate in candidates
        if candidate[0] >= first_explicit_option_top - 0.005
    ]


def _vertical_group_score(group: list[tuple[float, float, float, str]]) -> float:
    if len(group) < 2:
        return 0.0
    y_values = [item[0] for item in group]
    gaps = [
        y_values[index + 1] - y_values[index]
        for index in range(len(y_values) - 1)
    ]
    if any(gap <= 0 or gap > 0.12 for gap in gaps):
        return 0.0
    average_gap = sum(gaps) / len(gaps)
    gap_variance = sum(abs(gap - average_gap) for gap in gaps) / len(gaps)
    x_values = [item[1] for item in group]
    x_spread = max(x_values) - min(x_values)
    width_signal = min(sum(item[2] for item in group), 1.0)
    return len(group) * 2.0 + width_signal - gap_variance * 10.0 - x_spread * 5.0


def call_ollama(
    *,
    endpoint: str,
    model: str,
    prompt: str,
    timeout_seconds: int,
    num_predict: int,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_predict": num_predict,
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(getattr(exc, "reason", str(exc))) from exc
    text = str(data.get("response") or "").strip()
    if not text:
        raise RuntimeError("Ollama returned an empty response.")
    return text


def _extract_json_object(raw_response: str) -> dict[str, Any]:
    text = raw_response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValidationError("Ollama compact response must be a JSON object.")
    return parsed


def _valid_ids(value: Any, available: dict[str, Any]) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text_id = str(item)
        if text_id in available and text_id not in result:
            result.append(text_id)
    return result


def _expand_option_ids(selected_ids: list[str], option_by_text_id: dict[str, Any]) -> list[str]:
    if len(selected_ids) < 2:
        return selected_ids
    selected_labels = {
        _normalized_yes_no_label(str((option_by_text_id.get(text_id) or {}).get("text") or ""))
        for text_id in selected_ids
    }
    if selected_labels == {"yes", "no"}:
        return selected_ids
    selected_candidates = [
        option_by_text_id[text_id]
        for text_id in selected_ids
        if isinstance(option_by_text_id.get(text_id), dict)
    ]
    y_values = [_bbox_y(candidate.get("text_bbox_norm")) for candidate in selected_candidates]
    y_values = [value for value in y_values if value is not None]
    if len(y_values) < 2:
        return selected_ids
    y_values.sort()
    gaps = [
        y_values[index + 1] - y_values[index]
        for index in range(len(y_values) - 1)
        if y_values[index + 1] > y_values[index]
    ]
    row_gap = min(gaps) if gaps else 0.06
    lower = max(0.0, min(y_values) - max(0.04, row_gap * 1.35))
    upper = min(1.0, max(y_values) + max(0.025, row_gap * 0.75))
    expanded = list(selected_ids)
    candidates = sorted(
        option_by_text_id.items(),
        key=lambda item: (_bbox_y((item[1] or {}).get("text_bbox_norm")) or 0.0),
    )
    for text_id, candidate in candidates:
        if text_id in expanded:
            continue
        y = _bbox_y(candidate.get("text_bbox_norm"))
        if y is None or not lower <= y <= upper:
            continue
        if not _looks_like_answer_option(candidate):
            continue
        expanded.append(text_id)
    return sorted(
        expanded,
        key=lambda text_id: _bbox_y((option_by_text_id.get(text_id) or {}).get("text_bbox_norm")) or 0.0,
    )


def _looks_like_answer_option(candidate: dict[str, Any]) -> bool:
    text = _clean_text(str(candidate.get("text") or "")).casefold()
    if not text:
        return False
    rejected_terms = (
        "concept",
        "explain",
        "type your response",
        "window capture",
        "autoworks",
        "one answer only",
    )
    if any(term in text for term in rejected_terms):
        return False
    control_type = str(candidate.get("control_type") or "").casefold()
    if "input" in control_type or "button" in control_type:
        return False
    relationship = str(candidate.get("relationship_type") or "")
    return relationship in {"possible_option_label", "nearby_text"} or "checkbox" in control_type or "radio" in control_type


def _looks_like_question_context_text(value: str) -> bool:
    normalized = _letters_only(value)
    text = _clean_text(value).casefold()
    if not normalized or _looks_like_stop_text(value):
        return False
    if normalized in {"concept"} or normalized.startswith("concept"):
        return False
    return any(
        term in normalized
        for term in (
            "fromthelistbelow",
            "bestdescribes",
            "comparedto",
            "alreadyexisting",
            "selectoneanswer",
            "oneansweronly",
            "howlikely",
            "howunlikely",
            "howwould",
            "whichbest",
            "whatbest",
            "pleasechoose",
            "select",
            "chooseone",
            "rate",
            "thinkingabout",
        )
    ) or "?" in text


def _looks_like_single_choice_option_candidate(candidate: dict[str, Any]) -> bool:
    value = str(candidate.get("text") or "")
    normalized = _letters_only(value)
    known_short_labels = {
        "unlikely",
        "neutral",
        "likely",
        "agree",
        "disagree",
        "satisfied",
        "dissatisfied",
    }
    if len(normalized) < 10 and normalized not in known_short_labels:
        return False
    if _looks_like_stop_text(value) or _looks_like_question_context_text(value):
        return False
    if _looks_like_non_answer_text(value):
        return False
    relationship = str(candidate.get("relationship_type") or "")
    control_type = str(candidate.get("control_type") or "").casefold()
    has_control_signal = (
        relationship in {"possible_option_label", "nearby_text", "text_labels_element"}
        or any(token in control_type for token in ("radio", "checkbox", "icon", "unknown", "input"))
    )
    if not has_control_signal:
        return False
    return _looks_like_explicit_choice_label(value) or _looks_like_answer_phrase(value, candidate)


def _looks_like_explicit_choice_label(value: str) -> bool:
    normalized = _letters_only(value)
    return any(
        term in normalized
        for term in (
            "donotseeanyreasontouse",
            "reasontouse",
            "existsalreadyisbetter",
            "alreadyisbetter",
            "sameaswhatalreadyexists",
            "slightlybetterthanwhatalreadyexists",
            "muchmoreusefulthanwhatcurrentlyexists",
            "alreadyexists",
            "currentlyexists",
            "veryunlikely",
            "somewhatunlikely",
            "unlikely",
            "neutral",
            "neither",
            "somewhatlikely",
            "verylikely",
            "likely",
            "stronglydisagree",
            "disagree",
            "agree",
            "stronglyagree",
            "satisfied",
            "dissatisfied",
        )
    )


def _looks_like_answer_phrase(value: str, candidate: dict[str, Any]) -> bool:
    words = re.findall(r"[A-Za-z0-9]+", value)
    if not 1 <= len(words) <= 12:
        return False
    normalized = _letters_only(value)
    if not normalized or len(normalized) < 10:
        return False
    if _looks_like_non_answer_text(value) or _looks_like_stop_text(value):
        return False
    control_type = str(candidate.get("control_type") or "").casefold()
    if "input" in control_type or "button" in control_type:
        return False
    if len(words) == 1 and len(normalized) > 34:
        return False
    return True


def _looks_like_non_answer_text(value: str) -> bool:
    normalized = _letters_only(value)
    rejected_terms = (
        "concept",
        "fromthelistbelow",
        "bestdescribes",
        "comparedto",
        "selectoneanswer",
        "oneansweronly",
        "pleaseexplain",
        "typeyourresponse",
        "continue",
        "back",
        "virginmediawebsite",
        "windowcapture",
        "autoworks",
        "referencepages",
        "privacygate",
        "draganddrop",
        "likedislikeprompts",
        "opentext",
        "categories",
        "cards",
    )
    return any(term in normalized for term in rejected_terms)


def _looks_like_stop_text(value: str) -> bool:
    normalized = _letters_only(value)
    return (
        "pleaseexplain" in normalized
        or "explainyouranswer" in normalized
        or "typeyourresponse" in normalized
        or normalized in {"back", "continue", "next", "submit"}
    )


def _bbox_y(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    try:
        return float(value["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _bbox_x(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    try:
        return float(value["x"])
    except (KeyError, TypeError, ValueError):
        return None


def _bbox_width(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    try:
        return float(value["width"])
    except (KeyError, TypeError, ValueError):
        return None


def _normalized_yes_no_label(value: str) -> str:
    text = _letters_only(value)
    if text in {"yes", "no"}:
        return text
    if text in {"oyes", "0yes"}:
        return "yes"
    if text in {"ono", "0no"}:
        return "no"
    return text


def _letters_only(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", value).casefold()


def _union_bbox(items: list[Any]) -> dict[str, float]:
    boxes = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            x = float(item["x"])
            y = float(item["y"])
            width = float(item["width"])
            height = float(item["height"])
        except (KeyError, TypeError, ValueError):
            continue
        boxes.append((x, y, x + width, y + height))
    if not boxes:
        return empty_bbox()
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[2] for box in boxes)
    bottom = max(box[3] for box in boxes)
    return {
        "x": round(left, 6),
        "y": round(top, 6),
        "width": round(right - left, 6),
        "height": round(bottom - top, 6),
    }


def _selection_control_from_type(question_type: str, control_type: str) -> str:
    normalized_control = control_type.casefold()
    if question_type == "multiple_choice":
        return "checkbox"
    if question_type == "single_choice":
        return "radio"
    if "checkbox" in normalized_control:
        return "checkbox"
    if "radio" in normalized_control:
        return "radio"
    return "unknown"


def _enum_or_default(value: str, allowed: set[str], default: str) -> str:
    normalized = value.strip()
    return normalized if normalized in allowed else default


def _confidence(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        return 0.0


def _effective_confidence(value: Any, has_question: bool, has_options: bool) -> float:
    confidence = _confidence(value)
    if confidence > 0:
        return confidence
    if has_question and has_options:
        return 0.78
    return 0.0


def validate_grounded_ids(parsed: dict[str, Any], layout_index: dict[str, Any]) -> dict[str, Any]:
    report = {
        "errors": [],
        "warnings": [],
        "info": [],
        "normalization_applied": [],
    }
    text_ids = {
        str(text.get("text_id"))
        for text in layout_index.get("text_blocks", []) or []
        if isinstance(text, dict) and text.get("text_id")
    }
    element_ids = {
        str(element.get("element_id"))
        for element in layout_index.get("elements", []) or []
        if isinstance(element, dict) and element.get("element_id")
    }
    valid_pairs = {
        (str(rel.get("source_id")), str(rel.get("target_id")))
        for rel in layout_index.get("relationships", []) or []
        if isinstance(rel, dict)
        and str(rel.get("relationship_type") or "") in OPTION_RELATIONSHIPS
    }
    for q_index, question in enumerate(parsed.get("questions", []) or []):
        if not isinstance(question, dict):
            continue
        for o_index, option in enumerate(question.get("answer_options", []) or []):
            if not isinstance(option, dict):
                continue
            path = f"questions[{q_index}].answer_options[{o_index}]"
            option_id = str(option.get("option_id") or "")
            control_id = str(option.get("control_element_id") or "")
            if option_id not in text_ids:
                _append(report, "errors", "unknown_option_text_id", path, f"Unknown option text_id: {option_id}")
            if control_id and control_id not in element_ids:
                _append(report, "errors", "unknown_control_element_id", path, f"Unknown control_element_id: {control_id}")
            if option_id in text_ids and control_id in element_ids and (option_id, control_id) not in valid_pairs:
                _append(
                    report,
                    "warnings",
                    "unverified_text_control_pair",
                    path,
                    f"No option relationship found between {option_id} and {control_id}.",
                )
    return report


def _append(report: dict[str, list[dict[str, str]]], severity: str, code: str, path: str, message: str) -> None:
    item = {"code": code, "path": path, "message": message}
    report[severity].append(item)
    if severity in {"warnings", "info"}:
        report["normalization_applied"].append(item)


def _validation_error_report(code: str, message: str) -> dict[str, Any]:
    return {
        "validation_passed": False,
        "errors": [{"code": code, "path": "$", "message": message}],
        "warnings": [],
        "info": [],
        "normalization_applied": [],
    }


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_option_text(value: str) -> str:
    normalized = _normalized_yes_no_label(value)
    if normalized == "yes":
        return "Yes"
    if normalized == "no":
        return "No"
    value = re.sub(r"^[O0](?=[A-Z])", "", value.strip())
    return _clean_text(value)


def _write_debug(data: dict[str, Any]) -> None:
    write_json(OLLAMA_EVIDENCE_DEBUG_PATH, data)
