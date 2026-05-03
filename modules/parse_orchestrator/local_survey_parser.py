from __future__ import annotations

import re
import uuid
from typing import Any

from modules.parse_orchestrator.local_form_parser import (
    _action_for_label,
    _bbox,
    _bbox_key,
    _element_label,
    _language,
    _point,
)
from modules.parse_orchestrator.local_parse_quality import (
    detect_survey_signals,
    is_garbled_or_system_text,
    score_local_parse,
)

OPTION_HINTS = {"checkbox_like", "radio_like", "input_like", "button_like"}
BANNED_REGION_TYPES = {
    "browser_bar",
    "header",
    "footer",
    "left_sidebar",
    "right_sidebar",
    "desktop",
    "taskbar",
}
URL_RE = re.compile(r"(https?://|www\.|\.com/|app\.usertesting\.com)", re.IGNORECASE)
TIME_DATE_RE = re.compile(r"^\s*(\d{1,2}:\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\s*$")


def parse_survey_layout(
    layout_index: dict[str, Any],
    runtime_context: dict[str, Any] | None = None,
    *,
    detector_score: float = 0.0,
    min_confidence: float = 0.7,
) -> dict[str, Any]:
    runtime_context = runtime_context or {}
    text_blocks = sorted(list(layout_index.get("text_blocks") or []), key=lambda item: _bbox_key(item.get("bbox_norm")))
    text_by_id = {
        str(block.get("text_id")): block
        for block in text_blocks
        if block.get("text_id")
    }
    survey_signals = detect_survey_signals(layout_index)
    stem_block = _question_stem_block(text_blocks)
    question_stem = (
        {"text": str(stem_block.get("text", "")).strip(), "bbox_norm": _bbox(stem_block)}
        if stem_block
        else None
    )
    scope = _current_question_scope(layout_index, stem_block)
    diagnostics = {
        "current_question_scope": scope.get("bbox"),
        "excluded_option_candidates": [],
        "selected_option_candidate_ids": [],
        "next_question_boundary": scope.get("next_question_boundary"),
    }
    instructions = [
        {"text": str(block.get("text", "")).strip(), "bbox_norm": _bbox(block), "source": "local_layout_index"}
        for block in text_blocks
        if scope.get("isolated") and _in_scope(block, scope) and _is_instruction_text(block, question_stem)
    ]
    navigation_buttons = _navigation_buttons(layout_index, text_blocks, text_by_id, scope)
    options = _answer_options(layout_index, text_blocks, text_by_id, question_stem, scope, diagnostics)

    questions = []
    if question_stem or options:
        questions.append(
            {
                "question_id": "q1",
                "question_type": _question_type(layout_index, survey_signals),
                "question_stem": question_stem or {"text": "", "bbox_norm": _empty_bbox()},
                "instructions": instructions,
                "answer_options": options,
                "input_fields": [],
                "media": [],
                "matrix": None,
                "confidence": 0.0,
                "requires_human_review": False,
            }
        )

    parsed_page = {
        "parse_id": f"local_{uuid.uuid4().hex}",
        "task_id": str(runtime_context.get("task_id", "")),
        "page": {
            "page_type": "questionnaire",
            "language": _language(text_blocks),
            "page_status": "active_question_page",
            "confidence": 0.0,
        },
        "visual_elements": [],
        "questions": questions,
        "form_sections": [],
        "navigation_buttons": navigation_buttons,
        "uncertainties": [],
        "metadata": {"source": "local_layout_index", "answers_decided": False, "clicks_planned": False},
    }
    quality = score_local_parse(
        layout_index,
        parsed_page,
        page_type="questionnaire",
        detector_score=detector_score,
        min_confidence=min_confidence,
    )
    if not scope.get("isolated"):
        quality["confidence"] = min(float(quality.get("confidence", 0.0) or 0.0), min_confidence - 0.05)
        quality["requires_remote_parse"] = True
        quality.setdefault("reasons", []).append("unable_to_isolate_current_question_scope")
    parsed_page["page"]["confidence"] = quality["confidence"]
    for question in parsed_page["questions"]:
        question["confidence"] = quality["confidence"]
        question["requires_human_review"] = quality["requires_remote_parse"]
    if quality["requires_remote_parse"]:
        parsed_page["uncertainties"].append(
            {
                "type": "local_low_confidence",
                "message": "Local survey parse requires remote verification.",
                "reasons": quality["reasons"],
            }
        )
    return {
        "parsed_page": parsed_page,
        "quality": quality,
        "requires_remote_parse": quality["requires_remote_parse"],
        "fallback_reason": "; ".join(quality.get("reasons", [])),
        "diagnostics": diagnostics,
        "source": "local_fast_parse",
    }


def _question_stem_block(text_blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for block in text_blocks:
        if _text_role(block) == "question_stem" and not _is_noise_text(block, {}):
            return block
    question_phrases = [
        "which of the following",
        "how would you describe",
        "what is your",
        "which option",
        "choose one",
        "choose all",
    ]
    for block in text_blocks:
        normalized = _normalize(str(block.get("text", "")))
        compact = _compact(normalized)
        if any(phrase in normalized or _compact(phrase) in compact for phrase in question_phrases):
            return block
    candidates = [
        block
        for block in text_blocks
        if "?" in str(block.get("text", "")) and _text_role(block) != "button_text"
    ]
    if candidates:
        return candidates[0]
    return None


def _current_question_scope(
    layout_index: dict[str, Any], stem_block: dict[str, Any] | None
) -> dict[str, Any]:
    if not stem_block:
        return {"isolated": False, "bbox": None, "next_question_boundary": None}
    stem_box = _bbox(stem_block)
    stem_y = stem_box["y"]
    stem_bottom = stem_y + stem_box["height"]
    text_blocks = sorted(
        list(layout_index.get("text_blocks") or []), key=lambda item: _bbox_key(item.get("bbox_norm"))
    )
    nav_y = _first_navigation_y_below(layout_index, stem_bottom)
    next_question = _next_question_below(text_blocks, stem_block, stem_bottom)
    next_y = _bbox(next_question)["y"] if next_question else None
    candidates = [value for value in [nav_y, next_y] if value is not None and value > stem_bottom]
    y_max = min(candidates) if candidates else min(0.95, stem_y + 0.68)
    if y_max <= stem_bottom + 0.08:
        return {"isolated": False, "bbox": None, "next_question_boundary": None}
    x_min = max(0.18, min(stem_box["x"] - 0.08, 0.35))
    x_max = min(0.92, max(stem_box["x"] + stem_box["width"] + 0.08, 0.72))
    return {
        "isolated": True,
        "bbox": {
            "x": round(x_min, 6),
            "y": round(max(0.0, stem_y - 0.02), 6),
            "width": round(x_max - x_min, 6),
            "height": round(y_max - max(0.0, stem_y - 0.02), 6),
        },
        "next_question_boundary": {
            "text_id": str(next_question.get("text_id", "")),
            "text": str(next_question.get("text", "")),
            "y": next_y,
        }
        if next_question
        else None,
    }


def _answer_options(
    layout_index: dict[str, Any],
    text_blocks: list[dict[str, Any]],
    text_by_id: dict[str, dict[str, Any]],
    question_stem: dict[str, Any] | None,
    scope: dict[str, Any],
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    if not scope.get("isolated"):
        return []
    controls = [
        element
        for element in layout_index.get("elements", [])
        if element.get("element_type_hint") in OPTION_HINTS and _element_in_scope(element, scope)
    ]
    rows = _option_text_rows(text_blocks, question_stem, scope, diagnostics)
    options = []
    seen: set[str] = set()
    for block in rows:
        text = str(block.get("text", "")).strip()
        key = _dedupe_key(text)
        if not key or key in seen:
            _append_excluded_candidate(diagnostics, str(block.get("text_id", "")), text, "duplicate_option")
            continue
        control = _nearest_control(block, controls, text_by_id)
        options.append(
            {
                "option_id": str(block.get("text_id", "")),
                "text": text,
                "option_type": "text_option",
                "selection_control": _selection_control(control or {}),
                "bbox_norm": _bbox(block),
                "click_point_norm": _point(control) if control else _point(block),
                "source": "local_layout_index",
            }
        )
        diagnostics["selected_option_candidate_ids"].append(str(block.get("text_id", "")))
        seen.add(key)
    for element in controls:
        label = _element_label(element, text_by_id)
        key = _dedupe_key(label)
        if not label or key in seen or _action_for_label(label) != "unknown":
            continue
        _append_excluded_candidate(
            diagnostics,
            str(element.get("element_id", "")),
            label,
            "duplicate_or_nav_element",
        )
    return options


def _option_text_rows(
    text_blocks: list[dict[str, Any]],
    question_stem: dict[str, Any] | None,
    scope: dict[str, Any],
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = []
    for block in text_blocks:
        text = str(block.get("text", "")).strip()
        normalized = _normalize(text)
        if not normalized:
            continue
        if not _in_scope(block, scope):
            _exclude(diagnostics, block, "outside_current_question_scope")
            continue
        if _is_noise_text(block, scope):
            reason = (
                "garbled_or_system_text_filtered"
                if is_garbled_or_system_text(text)
                else "noise_or_system_text"
            )
            _exclude(diagnostics, block, reason)
            continue
        if _text_role(block) == "answer_option":
            candidates.append(block)
            continue
        if _action_for_label(text) != "unknown":
            _exclude(diagnostics, block, "navigation_text")
            continue
        if _is_question_text(block) or _is_instruction_text(block, question_stem):
            _exclude(diagnostics, block, "question_or_instruction_text")
            continue
        if 1 <= len(normalized.split()) <= 5 and len(normalized) <= 45:
            candidates.append(block)
        else:
            _exclude(diagnostics, block, "not_option_like")
    return _dedupe_row_candidates(candidates)


def _navigation_buttons(
    layout_index: dict[str, Any],
    text_blocks: list[dict[str, Any]],
    text_by_id: dict[str, dict[str, Any]],
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    buttons = []
    seen = set()
    for element in layout_index.get("elements", []):
        if element.get("element_type_hint") != "button_like" or not _element_in_scope(element, scope):
            continue
        label = _element_label(element, text_by_id)
        action = _action_for_label(label)
        if action == "unknown":
            continue
        buttons.append(_nav_button(str(element.get("element_id", "")), label, action, element))
        seen.add(_dedupe_key(label))
    for block in text_blocks:
        if not _in_scope(block, scope):
            continue
        text = str(block.get("text", "")).strip()
        action = _action_for_label(text)
        key = _dedupe_key(text)
        if action == "unknown" or key in seen:
            continue
        buttons.append(_nav_button(str(block.get("text_id", "")), text, action, block))
        seen.add(key)
    return buttons


def _question_type(layout_index: dict[str, Any], survey_signals: dict[str, Any]) -> str:
    joined = _normalize(" ".join(str(block.get("text", "")) for block in layout_index.get("text_blocks", [])))
    compact = _compact(joined)
    if (
        "select all that apply" in joined
        or "choose all" in joined
        or "selectallthatapply" in compact
        or "chooseall" in compact
    ):
        return "multiple_choice"
    if "choose one" in joined or "chooseone" in compact:
        return "single_choice"
    if any(element.get("element_type_hint") == "radio_like" for element in layout_index.get("elements", [])):
        return "single_choice"
    if survey_signals.get("option_like_element_count", 0) >= 2:
        return "multiple_choice"
    return "unknown"


def _is_question_text(block: dict[str, Any]) -> bool:
    text = str(block.get("text", ""))
    normalized = _normalize(text)
    compact = _compact(normalized)
    return "?" in text or any(
        phrase in normalized or _compact(phrase) in compact
        for phrase in [
            "which of the following",
            "how would you describe",
            "what is your",
            "which option",
        ]
    )


def _is_instruction_text(
    block: dict[str, Any], question_stem: dict[str, Any] | None = None
) -> bool:
    text = str(block.get("text", "")).strip()
    if question_stem and text == str(question_stem.get("text", "")).strip():
        return False
    normalized = _normalize(text)
    compact = _compact(normalized)
    return _text_role(block) == "instruction_text" or any(
        phrase in normalized or _compact(phrase) in compact
        for phrase in ["please select", "select all that apply", "choose one", "choose all"]
    )


def _selection_control(element: dict[str, Any]) -> str:
    hint = str(element.get("element_type_hint", ""))
    if hint == "checkbox_like":
        return "checkbox"
    if hint == "radio_like":
        return "radio"
    if hint == "button_like":
        return "button"
    return "unknown"


def _first_navigation_y_below(layout_index: dict[str, Any], stem_bottom: float) -> float | None:
    candidates: list[float] = []
    text_by_id = {
        str(block.get("text_id")): block
        for block in layout_index.get("text_blocks", [])
        if block.get("text_id")
    }
    for element in layout_index.get("elements", []):
        label = _element_label(element, text_by_id)
        if _action_for_label(label) == "unknown":
            continue
        y = _bbox(element)["y"]
        if y > stem_bottom:
            candidates.append(y)
    for block in layout_index.get("text_blocks", []):
        text = str(block.get("text", "")).strip()
        if _action_for_label(text) == "unknown":
            continue
        y = _bbox(block)["y"]
        if y > stem_bottom:
            candidates.append(y)
    return min(candidates) if candidates else None


def _next_question_below(
    text_blocks: list[dict[str, Any]], stem_block: dict[str, Any], stem_bottom: float
) -> dict[str, Any] | None:
    stem_id = str(stem_block.get("text_id", ""))
    for block in text_blocks:
        if str(block.get("text_id", "")) == stem_id:
            continue
        if _bbox(block)["y"] <= stem_bottom + 0.05:
            continue
        if _is_noise_text(block, {}) or _is_instruction_text(block):
            continue
        if _is_question_text(block):
            return block
    return None


def _in_scope(item: dict[str, Any], scope: dict[str, Any]) -> bool:
    box = dict(scope.get("bbox") or {})
    if not box:
        return False
    bbox = _bbox(item)
    cx = bbox["x"] + bbox["width"] / 2
    cy = bbox["y"] + bbox["height"] / 2
    return (
        float(box["x"]) <= cx <= float(box["x"]) + float(box["width"])
        and float(box["y"]) <= cy <= float(box["y"]) + float(box["height"])
    )


def _element_in_scope(element: dict[str, Any], scope: dict[str, Any]) -> bool:
    return _in_scope(element, scope)


def _is_noise_text(block: dict[str, Any], _scope: dict[str, Any]) -> bool:
    text = str(block.get("text", "")).strip()
    if not text:
        return True
    normalized = _normalize(text)
    compact = _compact(text)
    bbox = _bbox(block)
    if URL_RE.search(text) or TIME_DATE_RE.match(text):
        return True
    if is_garbled_or_system_text(text):
        return True
    if len(compact) <= 1:
        return True
    if bbox["y"] < 0.12 or bbox["y"] > 0.9:
        return True
    if normalized in {"x", "close", "minimize", "maximize"}:
        return True
    letters = [char for char in text if char.isalpha()]
    ascii_letters = [char for char in letters if char.isascii()]
    if letters and len(ascii_letters) / max(len(letters), 1) < 0.75:
        return True
    return False


def _nearest_control(
    block: dict[str, Any],
    controls: list[dict[str, Any]],
    text_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    text_box = _bbox(block)
    text_cy = text_box["y"] + text_box["height"] / 2
    candidates = []
    for control in controls:
        label = _element_label(control, text_by_id)
        if _action_for_label(label) != "unknown":
            continue
        control_box = _bbox(control)
        control_cy = control_box["y"] + control_box["height"] / 2
        dy = abs(control_cy - text_cy)
        horizontally_near = control_box["x"] <= text_box["x"] + 0.08
        if dy <= 0.035 and horizontally_near:
            candidates.append((dy + abs(control_box["x"] - text_box["x"]), control))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[0][1]


def _dedupe_row_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for block in sorted(candidates, key=lambda item: _bbox_key(item.get("bbox_norm"))):
        for row in rows:
            if _same_option_row(row[0], block):
                row.append(block)
                break
        else:
            rows.append([block])
    merged = []
    for row in rows:
        row = sorted(row, key=lambda item: _bbox(item)["x"])
        if len(row) == 1:
            merged.append(row[0])
            continue
        if not _should_merge_row_fragments(row):
            merged.extend(row)
            continue
        text = " ".join(str(item.get("text", "")).strip() for item in row if item.get("text"))
        first = dict(_best_row_candidate(row))
        first["text"] = text
        first["text_id"] = "+".join(str(item.get("text_id", "")) for item in row)
        merged.append(first)
    return merged


def _same_option_row(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_box = _bbox(left)
    right_box = _bbox(right)
    left_cy = left_box["y"] + left_box["height"] / 2
    right_cy = right_box["y"] + right_box["height"] / 2
    tolerance = max(0.012, 0.5 * min(left_box["height"], right_box["height"]))
    return abs(left_cy - right_cy) <= tolerance


def _should_merge_row_fragments(row: list[dict[str, Any]]) -> bool:
    if len(row) < 2:
        return False
    sorted_row = sorted(row, key=lambda item: _bbox(item)["x"])
    previous_right = None
    for item in sorted_row:
        text = str(item.get("text", "")).strip()
        box = _bbox(item)
        if previous_right is not None:
            gap = box["x"] - previous_right
            if gap < -0.01 or gap > 0.04:
                return False
        previous_right = box["x"] + box["width"]
        if len(_normalize(text).split()) > 2:
            return False
    return True


def _best_row_candidate(row: list[dict[str, Any]]) -> dict[str, Any]:
    def score(item: dict[str, Any]) -> tuple[int, int, float]:
        text = str(item.get("text", "")).strip()
        normalized = _normalize(text)
        has_space = 1 if " " in text else 0
        return (has_space, len(normalized), -_bbox(item)["x"])

    return sorted(row, key=score, reverse=True)[0]


def _dedupe_key(text: str) -> str:
    return _compact(text)


def _nav_button(button_id: str, label: str, action: str, source: dict[str, Any]) -> dict[str, Any]:
    return {
        "button_id": button_id,
        "label": label,
        "text": label,
        "action": action,
        "region_id": str(source.get("region_id", source.get("associated_region_id", ""))),
        "bbox_norm": _bbox(source),
        "click_point_norm": _point(source),
        "source": "local_layout_index",
    }


def _exclude(diagnostics: dict[str, Any], block: dict[str, Any], reason: str) -> None:
    text = str(block.get("text", "")).strip()
    if not text:
        return
    _append_excluded_candidate(diagnostics, str(block.get("text_id", "")), text, reason)


def _append_excluded_candidate(
    diagnostics: dict[str, Any], candidate_id: str, text: str, reason: str
) -> None:
    diagnostics["excluded_option_candidates"].append(
        make_excluded_candidate(candidate_id, text, reason)
    )


def make_excluded_candidate(candidate_id: str, text: str, reason: str) -> dict[str, str]:
    if is_garbled_or_system_text(text):
        text = "[filtered_system_or_garbled_text]"
        reason = "garbled_or_system_text_filtered"
    return {"id": candidate_id, "text": text, "reason": reason}


def _text_role(text: dict[str, Any]) -> str:
    return str(dict(text.get("metadata") or {}).get("text_role", "unknown"))


def _empty_bbox() -> dict[str, float]:
    return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}


def _normalize(text: str) -> str:
    return " ".join("".join(char.lower() if char.isalnum() else " " for char in text).split())


def _compact(text: str) -> str:
    return "".join(char.lower() for char in text if char.isalnum())
