from __future__ import annotations

import re
import uuid
from typing import Any

from modules.parse_orchestrator.fallback_policy import BUSINESS_REGION_TYPES
from modules.parse_orchestrator.local_parse_quality import detect_survey_signals, score_local_parse

INPUT_HINTS = {"input_like", "dropdown_like"}
BUTTON_HINTS = {"button_like"}
NAV_ACTION_WORDS = {
    "next": "next_page",
    "continue": "continue",
    "submit": "submit",
    "save": "save",
    "finish": "submit",
}


def parse_form_layout(
    layout_index: dict[str, Any],
    runtime_context: dict[str, Any] | None = None,
    *,
    detector_score: float = 0.0,
    min_confidence: float = 0.7,
) -> dict[str, Any]:
    runtime_context = runtime_context or {}
    text_by_id = {
        str(block.get("text_id")): block
        for block in layout_index.get("text_blocks", [])
        if block.get("text_id")
    }
    survey_signals = detect_survey_signals(layout_index)
    elements = list(layout_index.get("elements") or [])
    elements_by_region: dict[str, list[dict[str, Any]]] = {}
    for element in elements:
        elements_by_region.setdefault(str(element.get("region_id", "")), []).append(element)

    sections = []
    for region in _business_regions(layout_index):
        region_id = str(region.get("region_id", ""))
        section_texts = _texts_for_region(region, text_by_id)
        region_elements = sorted(
            elements_by_region.get(region_id, []), key=lambda item: _bbox_key(item.get("bbox_norm"))
        )
        section = {
            "section_id": region_id,
            "title": _section_title(region, section_texts),
            "region_id": region_id,
            "instructions": _instruction_texts(section_texts),
            "input_fields": [],
            "buttons": [],
        }
        for element in region_elements:
            hint = str(element.get("element_type_hint", ""))
            if hint in INPUT_HINTS:
                field = _input_field(element, text_by_id, section_texts)
                if not (
                    survey_signals["present"] and _looks_like_survey_answer_option(field["label"])
                ):
                    section["input_fields"].append(field)
            elif hint in BUTTON_HINTS:
                button = _button(element, text_by_id, section_texts)
                if _is_navigation_button(button):
                    continue
                section["buttons"].append(button)
        if section["title"] or section["instructions"] or section["input_fields"] or section["buttons"]:
            sections.append(section)

    navigation_buttons = _navigation_buttons(layout_index, text_by_id)
    parsed_page = {
        "parse_id": f"local_{uuid.uuid4().hex}",
        "task_id": str(runtime_context.get("task_id", "")),
        "page": {
            "page_type": "form",
            "language": _language(layout_index.get("text_blocks", [])),
            "page_status": "form_page",
            "confidence": 0.0,
        },
        "visual_elements": [],
        "questions": [],
        "form_sections": sections,
        "navigation_buttons": navigation_buttons,
        "uncertainties": [],
        "metadata": {"source": "local_layout_index", "answers_decided": False, "clicks_planned": False},
    }
    quality = score_local_parse(
        layout_index,
        parsed_page,
        page_type="form",
        detector_score=detector_score,
        min_confidence=min_confidence,
    )
    parsed_page["page"]["confidence"] = quality["confidence"]
    if quality["requires_remote_parse"]:
        parsed_page["uncertainties"].append(
            {
                "type": "local_low_confidence",
                "message": "Local layout_index parse requires remote verification.",
                "reasons": quality["reasons"],
            }
        )
    return {
        "parsed_page": parsed_page,
        "quality": quality,
        "requires_remote_parse": quality["requires_remote_parse"],
        "source": "local_fast_parse",
    }


def _business_regions(layout_index: dict[str, Any]) -> list[dict[str, Any]]:
    regions = [
        region
        for region in layout_index.get("regions", [])
        if region.get("region_type_hint") in BUSINESS_REGION_TYPES
    ]
    return sorted(regions, key=lambda item: _bbox_key(item.get("bbox_norm")))


def _texts_for_region(
    region: dict[str, Any], text_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    text_ids = [str(item) for item in region.get("text_ids", [])]
    texts = [text_by_id[text_id] for text_id in text_ids if text_id in text_by_id]
    return sorted(texts, key=lambda item: _bbox_key(item.get("bbox_norm")))


def _section_title(region: dict[str, Any], texts: list[dict[str, Any]]) -> str:
    metadata = dict(region.get("metadata") or {})
    title = str(metadata.get("section_title_text", "")).strip()
    if title:
        return title
    for text in texts:
        if _text_role(text) == "section_title":
            return str(text.get("text", "")).strip()
    return ""


def _instruction_texts(texts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    instructions = []
    for text in texts:
        if _text_role(text) == "instruction_text":
            instructions.append(
                {
                    "text": str(text.get("text", "")).strip(),
                    "bbox_norm": _bbox(text),
                    "source": "local_layout_index",
                }
            )
    return instructions


def _input_field(
    element: dict[str, Any],
    text_by_id: dict[str, dict[str, Any]],
    region_texts: list[dict[str, Any]],
) -> dict[str, Any]:
    label = _element_label(element, text_by_id) or _nearby_text_label(
        element, region_texts, {"field_label", "unknown", "field_value"}
    )
    hint = str(element.get("element_type_hint", ""))
    return {
        "field_id": str(element.get("element_id", "")),
        "field_type": "dropdown" if hint == "dropdown_like" else _infer_field_type(label),
        "label": label,
        "value_text": "",
        "region_id": str(element.get("region_id", "")),
        "bbox_norm": _bbox(element),
        "click_point_norm": _point(element),
        "source": "local_layout_index",
    }


def _button(
    element: dict[str, Any],
    text_by_id: dict[str, dict[str, Any]],
    region_texts: list[dict[str, Any]],
) -> dict[str, Any]:
    label = _element_label(element, text_by_id) or _nearby_text_label(
        element, region_texts, {"button_text", "action_link", "unknown"}
    )
    return {
        "button_id": str(element.get("element_id", "")),
        "label": label,
        "action": _action_for_label(label),
        "region_id": str(element.get("region_id", "")),
        "bbox_norm": _bbox(element),
        "click_point_norm": _point(element),
        "source": "local_layout_index",
    }


def _navigation_buttons(
    layout_index: dict[str, Any], text_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    region_types = {
        str(region.get("region_id", "")): str(region.get("region_type_hint", ""))
        for region in layout_index.get("regions", [])
    }
    buttons = []
    for element in layout_index.get("elements", []):
        if element.get("element_type_hint") != "button_like":
            continue
        label = _element_label(element, text_by_id)
        action = _action_for_label(label)
        region_type = region_types.get(str(element.get("region_id", "")), "")
        if action == "unknown" and region_type in BUSINESS_REGION_TYPES:
            continue
        buttons.append(
            {
                "button_id": str(element.get("element_id", "")),
                "label": label,
                "text": label,
                "action": action,
                "region_id": str(element.get("region_id", "")),
                "bbox_norm": _bbox(element),
                "click_point_norm": _point(element),
                "source": "local_layout_index",
            }
        )
    return buttons


def _is_navigation_button(button: dict[str, Any]) -> bool:
    return button.get("action") in {"next_page", "continue", "submit"}


def _element_label(element: dict[str, Any], text_by_id: dict[str, dict[str, Any]]) -> str:
    label = str(element.get("label_text", "")).strip()
    if label:
        return label
    parts = []
    for text_id in element.get("associated_text_ids", []):
        text = text_by_id.get(str(text_id), {})
        value = str(text.get("text", "")).strip()
        if value:
            parts.append(value)
    return " ".join(parts).strip()


def _nearby_text_label(
    element: dict[str, Any], texts: list[dict[str, Any]], allowed_roles: set[str]
) -> str:
    element_box = _bbox(element)
    candidates = []
    for text in texts:
        if _text_role(text) not in allowed_roles:
            continue
        text_value = str(text.get("text", "")).strip()
        if not text_value:
            continue
        text_box = _bbox(text)
        dy = abs(_center_y(text_box) - _center_y(element_box))
        is_left = _center_x(text_box) <= _center_x(element_box) + 0.04
        is_above = text_box["y"] + text_box["height"] <= element_box["y"] + 0.02
        if (dy < 0.045 and is_left) or is_above:
            distance = abs(_center_x(text_box) - _center_x(element_box)) + dy
            candidates.append((distance, text_value))
    if not candidates:
        return ""
    return sorted(candidates, key=lambda item: item[0])[0][1]


def _infer_field_type(label: str) -> str:
    normalized = label.lower()
    if "email" in normalized:
        return "email"
    if "date" in normalized or "dob" in normalized:
        return "date"
    if any(word in normalized for word in ["age", "number", "count", "amount", "zip"]):
        return "number"
    return "text" if label else "unknown"


def _looks_like_survey_answer_option(label: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
    if not normalized:
        return False
    explicit_options = {
        "amazon central",
        "amazon seller",
        "seller central",
        "supplier central",
        "vendor central",
        "all of the above",
    }
    if normalized in explicit_options:
        return True
    return 1 <= len(normalized.split()) <= 5 and not any(
        token in normalized for token in ["email", "name", "address", "phone", "date"]
    )


def _action_for_label(label: str) -> str:
    normalized = re.sub(r"[^a-z]+", " ", label.lower()).strip()
    for word, action in NAV_ACTION_WORDS.items():
        if word in normalized.split():
            return action
    return "unknown"


def _text_role(text: dict[str, Any]) -> str:
    return str(dict(text.get("metadata") or {}).get("text_role", "unknown"))


def _bbox(item: dict[str, Any]) -> dict[str, float]:
    bbox = dict(item.get("bbox_norm") or {})
    return {
        "x": float(bbox.get("x", 0.0) or 0.0),
        "y": float(bbox.get("y", 0.0) or 0.0),
        "width": float(bbox.get("width", 0.0) or 0.0),
        "height": float(bbox.get("height", 0.0) or 0.0),
    }


def _point(item: dict[str, Any]) -> dict[str, float]:
    point = dict(item.get("click_point_norm") or {})
    if point:
        return {"x": float(point.get("x", 0.0) or 0.0), "y": float(point.get("y", 0.0) or 0.0)}
    bbox = _bbox(item)
    return {"x": bbox["x"] + bbox["width"] / 2, "y": bbox["y"] + bbox["height"] / 2}


def _bbox_key(bbox: dict[str, Any] | None) -> tuple[float, float]:
    box = bbox or {}
    return (float(box.get("y", 0.0) or 0.0), float(box.get("x", 0.0) or 0.0))


def _center_x(bbox: dict[str, float]) -> float:
    return bbox["x"] + bbox["width"] / 2


def _center_y(bbox: dict[str, float]) -> float:
    return bbox["y"] + bbox["height"] / 2


def _language(text_blocks: list[dict[str, Any]]) -> str:
    text = " ".join(str(block.get("text", "")) for block in text_blocks)
    letters = sum(1 for char in text if char.isalpha())
    ascii_letters = sum(1 for char in text if char.isascii() and char.isalpha())
    if letters and ascii_letters / max(letters, 1) > 0.8:
        return "en"
    return "unknown"
