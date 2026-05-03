from __future__ import annotations

import re
from typing import Any

from modules.parse_orchestrator.fallback_policy import BUSINESS_REGION_TYPES, is_severely_unsafe

SURVEY_PHRASES = {
    "which of the following",
    "select all that apply",
    "please select",
    "choose one",
    "choose all",
    "how would you describe",
    "what is your",
    "which option",
}
COMPACT_SURVEY_PHRASES = {re.sub(r"[^a-z0-9?]+", "", phrase) for phrase in SURVEY_PHRASES}

NAV_WORDS = {"next", "continue", "submit", "back", "previous", "skip"}
MOJIBAKE_MARKERS = {"鏍", "鎼", "鏃", "锛", "塃", "涓", "辫", "爜", "宸", "綔", "敞"}


def is_garbled_or_system_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    normalized = _normalize_text(value)
    compact = _compact_text(value)
    if len(compact) <= 1:
        return True
    if any(marker in value for marker in MOJIBAKE_MARKERS):
        return True
    cjk_chars = [char for char in value if "\u4e00" <= char <= "\u9fff"]
    ascii_alnum = [char for char in value if char.isascii() and char.isalnum()]
    if cjk_chars and ascii_alnum and len(ascii_alnum) / max(len(value), 1) <= 0.5:
        return True
    if re.search(r"(https?://|www\.|\.com/|app\.usertesting\.com)", value, re.IGNORECASE):
        return True
    if re.match(r"^\s*(\d{1,2}:\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\s*$", value):
        return True
    if normalized in {"x", "close", "minimize", "maximize"}:
        return True
    letters = [char for char in value if char.isalpha()]
    ascii_letters = [char for char in letters if char.isascii()]
    if letters and len(ascii_letters) / max(len(letters), 1) < 0.75:
        return True
    return False


def detect_survey_signals(layout_index: dict[str, Any]) -> dict[str, Any]:
    text_blocks = sorted(
        list(layout_index.get("text_blocks") or []),
        key=lambda item: _bbox_key(dict(item.get("bbox_norm") or {})),
    )
    normalized_texts = [_normalize_text(str(block.get("text", ""))) for block in text_blocks]
    joined = " ".join(normalized_texts)
    compact_joined = _compact_text(joined)
    phrase_hits = [
        phrase
        for phrase in SURVEY_PHRASES
        if phrase in joined or _compact_text(phrase) in compact_joined
    ]
    question_mark_text_ids = [
        str(block.get("text_id", ""))
        for block in text_blocks
        if "?" in str(block.get("text", ""))
    ]
    option_rows = _stacked_option_rows(text_blocks)
    option_like_elements = [
        element
        for element in layout_index.get("elements", [])
        if element.get("element_type_hint") in {"checkbox_like", "radio_like"}
    ]
    has_signals = bool(
        phrase_hits
        or question_mark_text_ids
        or len(option_rows) >= 3
        or len(option_like_elements) >= 3
    )
    return {
        "present": has_signals,
        "phrase_hits": phrase_hits,
        "compact_phrase_hits": [
            phrase for phrase in COMPACT_SURVEY_PHRASES if phrase in compact_joined
        ],
        "question_mark_text_ids": question_mark_text_ids,
        "stacked_option_texts": [
            str(block.get("text", "")).strip()
            for block in option_rows
            if not is_garbled_or_system_text(str(block.get("text", "")))
        ],
        "option_like_element_count": len(option_like_elements),
    }


def detect_local_page_signals(layout_index: dict[str, Any]) -> dict[str, Any]:
    survey_signals = detect_survey_signals(layout_index)
    form_signals = detect_form_signals(layout_index)
    detector_scores = dict(dict(layout_index.get("layout_hints") or {}).get("detector_scores") or {})
    form_score = float(detector_scores.get("form", 0.0) or 0.0)
    survey_score = float(detector_scores.get("survey", 0.0) or 0.0)
    detector_override_applied = bool(survey_signals["present"] and form_score >= survey_score)
    if survey_signals["present"]:
        detected = "questionnaire"
        selected = "survey"
    elif form_signals["present"]:
        detected = "form"
        selected = "form"
    else:
        detected = "unknown"
        selected = ""
    return {
        "detected_local_page_type": detected,
        "selected_local_parser": selected,
        "survey_signals": survey_signals,
        "form_signals": form_signals,
        "detector_override_applied": detector_override_applied,
        "detector_scores": {"form": form_score, "survey": survey_score},
        "warnings": ["form_detector_overridden_by_survey_signals"]
        if detector_override_applied
        else [],
    }


def detect_form_signals(layout_index: dict[str, Any], parsed_page: dict[str, Any] | None = None) -> dict[str, Any]:
    regions = list(layout_index.get("regions") or [])
    text_blocks = list(layout_index.get("text_blocks") or [])
    elements = list(layout_index.get("elements") or [])
    section_titles = [
        block
        for block in text_blocks
        if str(dict(block.get("metadata") or {}).get("text_role", "")) == "section_title"
    ]
    input_like = [
        element
        for element in elements
        if element.get("element_type_hint") in {"input_like", "dropdown_like"}
    ]
    business_regions = [
        region for region in regions if region.get("region_type_hint") in BUSINESS_REGION_TYPES
    ]
    parsed_page = parsed_page or {}
    form_sections = list(parsed_page.get("form_sections") or [])
    fields = [
        field
        for section in form_sections
        for field in list(section.get("input_fields") or [])
    ]
    titled_sections = [section for section in form_sections if str(section.get("title", "")).strip()]
    return {
        "present": bool((section_titles or titled_sections) and (input_like or fields)),
        "business_region_count": len(business_regions),
        "section_title_count": len(section_titles) or len(titled_sections),
        "input_like_count": len(input_like),
        "parsed_field_count": len(fields),
    }


def score_local_parse(
    layout_index: dict[str, Any],
    parsed_page: dict[str, Any],
    *,
    page_type: str,
    detector_score: float,
    min_confidence: float = 0.7,
) -> dict[str, Any]:
    regions = list(layout_index.get("regions") or [])
    text_blocks = list(layout_index.get("text_blocks") or [])
    elements = list(layout_index.get("elements") or [])
    reasons: list[str] = []
    survey_signals = detect_survey_signals(layout_index)
    form_signals = detect_form_signals(layout_index, parsed_page)

    business_regions = [
        region for region in regions if region.get("region_type_hint") in BUSINESS_REGION_TYPES
    ]
    if not business_regions:
        reasons.append("No business/card regions found.")

    if not text_blocks:
        reasons.append("OCR text_blocks are empty.")

    useful_hints = {"input_like", "dropdown_like", "button_like", "checkbox_like", "radio_like"}
    useful_elements = [
        element for element in elements if element.get("element_type_hint") in useful_hints
    ]
    if not useful_elements:
        reasons.append("No input-like, button-like, or option-like elements found.")

    severe_regions = [
        str(region.get("region_id", ""))
        for region in business_regions
        if is_severely_unsafe(dict(region.get("crop_quality") or {}), True)
    ]
    if severe_regions:
        reasons.append(f"Severe crop quality warnings for regions: {', '.join(severe_regions)}.")

    form_sections = list(parsed_page.get("form_sections") or [])
    fields = [
        field
        for section in form_sections
        for field in list(section.get("input_fields") or [])
    ]
    buttons = list(parsed_page.get("navigation_buttons") or [])
    buttons.extend(
        button for section in form_sections for button in list(section.get("buttons") or [])
    )
    questions = list(parsed_page.get("questions") or [])
    options = [
        option
        for question in questions
        for option in list(question.get("answer_options") or [])
    ]

    if page_type == "form" and not form_sections:
        reasons.append("Local form parse found no form_sections.")
    if page_type == "form" and useful_elements and not fields and not buttons:
        reasons.append("Local form parse found no fields or buttons.")
    if page_type in {"survey", "questionnaire"} and not questions:
        reasons.append("Local survey parse found no questions.")

    labeled_fields = [field for field in fields if str(field.get("label", "")).strip()]
    labeled_buttons = [
        button
        for button in buttons
        if str(button.get("label", button.get("text", ""))).strip()
    ]
    labeled_options = [option for option in options if str(option.get("text", "")).strip()]
    question_with_stem = [
        question
        for question in questions
        if str(dict(question.get("question_stem") or {}).get("text", "")).strip()
    ]
    true_titled_sections = [
        section for section in form_sections if str(section.get("title", "")).strip()
    ]

    score = 0.0
    score += min(max(detector_score, 0.0), 1.0) * 0.3
    score += 0.18 if business_regions else 0.0
    score += 0.18 if text_blocks else 0.0
    score += 0.14 if useful_elements else 0.0
    score += 0.1 if not severe_regions else 0.0

    if page_type == "form":
        if survey_signals["present"]:
            reasons.append("Survey/questionnaire OCR signals are present; form parse is not final.")
        if not true_titled_sections:
            reasons.append("Local form parse found no true section titles.")
        score += 0.05 if true_titled_sections else 0.0
        score += 0.08 if fields and true_titled_sections else 0.0
        score += 0.05 if fields and len(labeled_fields) / max(len(fields), 1) >= 0.5 else 0.0
        score += 0.02 if not buttons or len(labeled_buttons) / max(len(buttons), 1) >= 0.5 else 0.0
    elif page_type in {"survey", "questionnaire"}:
        if not question_with_stem:
            reasons.append("Local survey parse found no question stem.")
        if len(options) < 2:
            reasons.append("Local survey parse found fewer than two answer options.")
        score += 0.08 if question_with_stem else 0.0
        score += 0.09 if len(options) >= 2 else 0.0
        score += 0.04 if options and len(labeled_options) / max(len(options), 1) >= 0.5 else 0.0

    if not text_blocks:
        score = min(score, 0.45)
    if page_type == "form" and survey_signals["present"]:
        score = min(score, min_confidence - 0.05)
    if page_type == "form" and (not true_titled_sections or not fields):
        score = min(score, min_confidence - 0.05)
    if page_type in {"survey", "questionnaire"} and (not question_with_stem or len(options) < 2):
        score = min(score, min_confidence - 0.05)
    confidence = round(min(score, 1.0), 3)
    if confidence < min_confidence:
        reasons.append(
            f"Local parse confidence {confidence:.2f} is below threshold {min_confidence:.2f}."
        )
    return {
        "confidence": confidence,
        "requires_remote_parse": confidence < min_confidence,
        "reasons": reasons,
        "survey_signals": survey_signals,
        "form_signals": form_signals,
        "detected_local_page_type": _detected_page_type(survey_signals, form_signals),
    }


def _detected_page_type(survey_signals: dict[str, Any], form_signals: dict[str, Any]) -> str:
    if survey_signals.get("present"):
        return "questionnaire"
    if form_signals.get("present"):
        return "form"
    return "unknown"


def _stacked_option_rows(text_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for block in text_blocks:
        text = str(block.get("text", "")).strip()
        normalized = _normalize_text(text)
        role = str(dict(block.get("metadata") or {}).get("text_role", "unknown"))
        if not normalized or normalized in NAV_WORDS:
            continue
        if is_garbled_or_system_text(text):
            continue
        if role in {"section_title", "instruction_text", "field_label", "button_text"}:
            continue
        if "?" in text or any(phrase in normalized for phrase in SURVEY_PHRASES):
            continue
        if 1 <= len(normalized.split()) <= 5 and len(normalized) <= 45:
            candidates.append(block)
    if len(candidates) < 3:
        return []
    rows = []
    previous_y = -1.0
    previous_x = None
    for block in candidates:
        bbox = dict(block.get("bbox_norm") or {})
        x = float(bbox.get("x", 0.0) or 0.0)
        y = float(bbox.get("y", 0.0) or 0.0)
        if previous_x is None or (y > previous_y and abs(x - previous_x) <= 0.12):
            rows.append(block)
            previous_y = y
            previous_x = x if previous_x is None else previous_x
    return rows if len(rows) >= 3 else []


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9?]+", " ", text.lower())).strip()


def _compact_text(text: str) -> str:
    return re.sub(r"[^a-z0-9?]+", "", text.lower())


def _bbox_key(bbox: dict[str, Any]) -> tuple[float, float]:
    return (float(bbox.get("y", 0.0) or 0.0), float(bbox.get("x", 0.0) or 0.0))
