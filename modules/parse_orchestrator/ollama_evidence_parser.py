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
        text_region = str(text_by_id[text_id].get("associated_region_id") or "")
        element_region = str(element_by_id[element_id].get("region_id") or "")
        if selected_region_ids and text_region not in selected_region_ids and element_region not in selected_region_ids:
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
        and (
            not selected_region_ids
            or str(text.get("associated_region_id") or "") in selected_region_ids
        )
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

    stem_texts = [text_by_id[text_id]["text"] for text_id in question_text_ids if text_id in text_by_id]
    stem_bbox = _union_bbox([text_by_id[text_id].get("bbox_norm") for text_id in question_text_ids])
    options = []
    for text_id in option_text_ids:
        source = option_by_text_id[text_id]
        control_type = str(source.get("control_type") or "unknown")
        options.append(
            {
                "option_id": text_id,
                "text": str(source.get("text") or ""),
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
                "requires_human_review": False,
            }
        ],
        "navigation_buttons": [],
        "uncertainties": [
            item
            for item in uncertainties
            if isinstance(item, dict) and item.get("type") and item.get("message")
        ],
    }


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


def _bbox_y(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    try:
        return float(value["y"])
    except (KeyError, TypeError, ValueError):
        return None


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


def _write_debug(data: dict[str, Any]) -> None:
    write_json(OLLAMA_EVIDENCE_DEBUG_PATH, data)
