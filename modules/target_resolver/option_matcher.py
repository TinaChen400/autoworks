from __future__ import annotations

import re
from typing import Any


CONTROL_RELATIONSHIP_TYPES = {
    "possible_option_label": 0,
    "text_labels_element": 1,
    "text_inside_element": 2,
    "nearby_text": 3,
}


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def parsed_page(orchestrated_parse: dict[str, Any]) -> dict[str, Any]:
    page = orchestrated_parse.get("parsed_page")
    if isinstance(page, dict) and isinstance(page.get("parsed_page"), dict):
        return page["parsed_page"]
    if isinstance(page, dict):
        return page
    return orchestrated_parse


def find_option(orchestrated_parse: dict[str, Any], question_id: str, option_id: str) -> dict[str, Any] | None:
    page = parsed_page(orchestrated_parse)
    for question in page.get("questions", []):
        if str(question.get("question_id", "")) != question_id:
            continue
        for key in ("answer_options", "options"):
            for option in question.get(key, []) or []:
                if str(option.get("option_id", "")) == option_id:
                    return option
    return None


def option_text(option: dict[str, Any]) -> str:
    return str(option.get("text") or option.get("option_text") or option.get("label") or "")


def find_control(option: dict[str, Any], layout_index: dict[str, Any]) -> dict[str, Any] | None:
    element_by_id = {
        str(element.get("element_id")): element
        for element in layout_index.get("elements", [])
        if element.get("element_id")
    }
    text_by_id = {
        str(text.get("text_id")): text
        for text in layout_index.get("text_blocks", [])
        if text.get("text_id")
    }

    explicit_element_id = str(
        option.get("control_element_id")
        or option.get("element_id")
        or (option.get("metadata") or {}).get("control_element_id")
        or ""
    )
    if explicit_element_id in element_by_id:
        return _result(element_by_id[explicit_element_id], 0.95, "explicit_control_element_id")

    option_id = str(option.get("option_id", ""))
    if option_id in element_by_id:
        return _result(element_by_id[option_id], 0.92, "option_id_element")

    candidate_text_ids = []
    if option_id in text_by_id:
        candidate_text_ids.append(option_id)

    wanted_text = _normalized_text(option_text(option))
    for text_id, text_block in text_by_id.items():
        if wanted_text and _normalized_text(str(text_block.get("text", ""))) == wanted_text:
            candidate_text_ids.append(text_id)

    best = None
    for relationship in layout_index.get("relationships", []):
        source_id = str(relationship.get("source_id", ""))
        target_id = str(relationship.get("target_id", ""))
        rel_type = str(relationship.get("relationship_type", ""))
        if source_id not in candidate_text_ids or target_id not in element_by_id:
            continue
        if rel_type not in CONTROL_RELATIONSHIP_TYPES:
            continue
        priority = CONTROL_RELATIONSHIP_TYPES[rel_type]
        confidence = float(relationship.get("confidence", 0.0) or 0.0)
        score = confidence - (priority * 0.05)
        if best is None or score > best["score"]:
            best = {
                "score": score,
                "element": element_by_id[target_id],
                "confidence": confidence,
                "source": rel_type,
            }

    if best is not None:
        return _result(best["element"], best["confidence"], best["source"])

    if isinstance(option.get("click_point_norm"), dict):
        return {
            "control_element_id": "",
            "control_type": str(option.get("selection_control") or "unknown"),
            "click_point_norm": option["click_point_norm"],
            "resolver_confidence": 0.45,
            "match_source": "parsed_option_click_point",
        }

    return None


def _result(element: dict[str, Any], confidence: float, source: str) -> dict[str, Any]:
    return {
        "control_element_id": str(element.get("element_id", "")),
        "control_type": str(element.get("element_type_hint") or element.get("control_type") or "unknown"),
        "click_point_norm": element.get("click_point_norm") or {},
        "click_point_raw": element.get("click_point_raw") or {},
        "resolver_confidence": round(max(0.0, min(1.0, confidence)), 3),
        "match_source": source,
    }

