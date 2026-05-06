from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from modules.parse_orchestrator.schema import new_id

OPTION_PATTERN = re.compile(r"^[oO0\u25cb\u25ef]\s*(yes|no)$", re.IGNORECASE)
NAVIGATION_TEXTS = {"next", "back", "previous", "submit", "continue"}


@dataclass
class LocalParseResult:
    parsed_page: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)
    model_calls_count: int = 0
    confidence: float = 0.0
    validation_passed: bool = False
    warnings: list[str] = field(default_factory=list)
    error: str = ""


def parse_local_survey_page(
    layout_index: dict[str, Any],
    runtime_context: dict[str, Any],
) -> LocalParseResult:
    blocks = _usable_text_blocks(layout_index)
    if len(blocks) < 3:
        return _failure("OCR text_blocks are missing or too few.", runtime_context)

    questions = _extract_single_choice_questions(blocks)
    if not questions:
        return _failure("No clear local Yes/No option labels found.", runtime_context)

    confidence = _confidence_for_questions(questions)
    parsed_page = {
        "parse_id": new_id("local_parse"),
        "task_id": str(runtime_context.get("task_id", "")),
        "page": {
            "page_type": "questionnaire",
            "language": "en",
            "page_status": "active_question_page",
            "confidence": confidence,
        },
        "questions": questions,
        "navigation_buttons": [],
        "uncertainties": [],
        "visual_elements": [],
        "metadata": {
            "source": "rapidocr_local_parser",
            "ocr_backend": "rapidocr",
        },
    }
    parsed_page, validation_report = _validate_local_parsed_page(parsed_page, runtime_context)
    return LocalParseResult(
        parsed_page=parsed_page,
        validation_report=validation_report,
        confidence=confidence,
        validation_passed=bool(validation_report.get("validation_passed", False)),
    )


def normalize_yes_no_option(text: str) -> str | None:
    normalized = " ".join(str(text or "").strip().split())
    match = OPTION_PATTERN.match(normalized)
    if not match:
        return None
    value = match.group(1).lower()
    return "Yes" if value == "yes" else "No"


def _usable_text_blocks(layout_index: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = []
    for block in layout_index.get("text_blocks", []):
        if not isinstance(block, dict):
            continue
        text = str(block.get("text", "")).strip()
        bbox_norm = block.get("bbox_norm")
        bbox_raw = block.get("bbox_raw")
        if not text or not isinstance(bbox_norm, dict) or not isinstance(bbox_raw, dict):
            continue
        blocks.append(block)
    return sorted(blocks, key=lambda item: (_bbox(item)["y"], _bbox(item)["x"]))


def _extract_single_choice_questions(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    questions = []
    cursor = 0
    index = 0
    while index < len(blocks) - 1:
        first_label = normalize_yes_no_option(str(blocks[index].get("text", "")))
        second_label = normalize_yes_no_option(str(blocks[index + 1].get("text", "")))
        if first_label == "Yes" and second_label == "No" and _same_option_group(blocks[index], blocks[index + 1]):
            stem_blocks = _stem_blocks(blocks[cursor:index])
            if stem_blocks:
                questions.append(_question_from_blocks(len(questions) + 1, stem_blocks, [blocks[index], blocks[index + 1]]))
            cursor = _skip_following_navigation(blocks, index + 2)
            index = cursor
            continue
        index += 1
    return questions


def _same_option_group(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_box = _bbox(first)
    second_box = _bbox(second)
    vertical_gap = second_box["y"] - (first_box["y"] + first_box["height"])
    horizontal_delta = abs(second_box["x"] - first_box["x"])
    return vertical_gap <= 0.08 and horizontal_delta <= 0.2


def _stem_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        block
        for block in blocks
        if normalize_yes_no_option(str(block.get("text", ""))) is None
        and str(block.get("text", "")).strip().lower() not in NAVIGATION_TEXTS
    ]


def _skip_following_navigation(blocks: list[dict[str, Any]], start: int) -> int:
    cursor = start
    while cursor < len(blocks):
        text = str(blocks[cursor].get("text", "")).strip().lower()
        if text not in NAVIGATION_TEXTS:
            break
        cursor += 1
    return cursor


def _question_from_blocks(
    question_number: int,
    stem_blocks: list[dict[str, Any]],
    option_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "question_id": f"q{question_number}",
        "question_type": "single_choice",
        "question_stem": {
            "text": _join_stem_text(stem_blocks),
            "bbox_norm": _union_bbox_norm(stem_blocks),
        },
        "instructions": [],
        "answer_options": [
            _option_from_block(question_number, option_index + 1, block)
            for option_index, block in enumerate(option_blocks)
        ],
        "input_fields": [],
        "media": [],
        "matrix": None,
        "confidence": 0.86,
    }


def _option_from_block(question_number: int, option_number: int, block: dict[str, Any]) -> dict[str, Any]:
    label = normalize_yes_no_option(str(block.get("text", ""))) or str(block.get("text", "")).strip()
    bbox = dict(block.get("bbox_norm") or {})
    return {
        "option_id": f"a{option_number}",
        "label": label,
        "text": label,
        "bbox_norm": bbox,
        "option_type": "text_option",
        "selection_control": "radio",
        "click_point_norm": _center_point_norm(bbox),
    }


def _join_stem_text(blocks: list[dict[str, Any]]) -> str:
    return " ".join(str(block.get("text", "")).strip() for block in blocks if str(block.get("text", "")).strip())


def _bbox(block: dict[str, Any]) -> dict[str, float]:
    bbox = block.get("bbox_norm") or {}
    return {
        "x": float(bbox.get("x", 0.0) or 0.0),
        "y": float(bbox.get("y", 0.0) or 0.0),
        "width": float(bbox.get("width", 0.0) or 0.0),
        "height": float(bbox.get("height", 0.0) or 0.0),
    }


def _union_bbox_norm(blocks: list[dict[str, Any]]) -> dict[str, float]:
    boxes = [_bbox(block) for block in blocks]
    left = min(box["x"] for box in boxes)
    top = min(box["y"] for box in boxes)
    right = max(box["x"] + box["width"] for box in boxes)
    bottom = max(box["y"] + box["height"] for box in boxes)
    return {
        "x": round(max(0.0, min(1.0, left)), 6),
        "y": round(max(0.0, min(1.0, top)), 6),
        "width": round(max(0.0, min(1.0, right) - max(0.0, min(1.0, left))), 6),
        "height": round(max(0.0, min(1.0, bottom) - max(0.0, min(1.0, top))), 6),
    }


def _center_point_norm(bbox: dict[str, Any]) -> dict[str, float]:
    x = float(bbox.get("x", 0.0) or 0.0) + float(bbox.get("width", 0.0) or 0.0) / 2
    y = float(bbox.get("y", 0.0) or 0.0) + float(bbox.get("height", 0.0) or 0.0) / 2
    return {
        "x": round(max(0.0, min(1.0, x)), 6),
        "y": round(max(0.0, min(1.0, y)), 6),
    }


def _confidence_for_questions(questions: list[dict[str, Any]]) -> float:
    if not questions:
        return 0.0
    option_count = sum(len(question.get("answer_options", [])) for question in questions)
    if option_count >= len(questions) * 2:
        return 0.86
    return 0.7


def _validate_local_parsed_page(
    parsed_page: dict[str, Any],
    runtime_context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from modules.vision_parser.response_validator import validate_parsed_page_with_report

        validation_context = dict(runtime_context)
        supported_question_types = set(validation_context.get("supported_question_types") or [])
        supported_question_types.add("single_choice")
        validation_context["supported_question_types"] = sorted(supported_question_types)
        return validate_parsed_page_with_report(
            json.dumps(parsed_page),
            validation_context,
            output_level="standard",
        )
    except Exception as exc:  # noqa: BLE001 - local parsing must fail safely.
        return parsed_page, {
            "validation_passed": False,
            "errors": [
                {
                    "code": "local_parse_validation_failed",
                    "path": "$",
                    "message": str(exc),
                }
            ],
            "warnings": [],
            "info": [],
            "normalization_applied": [],
        }


def _failure(message: str, runtime_context: dict[str, Any]) -> LocalParseResult:
    return LocalParseResult(
        parsed_page={
            "parse_id": new_id("local_parse_failed"),
            "task_id": str(runtime_context.get("task_id", "")),
            "page": {
                "page_type": "unknown",
                "language": "unknown",
                "page_status": "parse_failed",
                "confidence": 0.0,
            },
            "questions": [],
            "navigation_buttons": [],
            "uncertainties": [
                {
                    "type": "local_parse_failed",
                    "message": message,
                    "related_question_id": "",
                }
            ],
            "visual_elements": [],
            "metadata": {
                "source": "rapidocr_local_parser",
                "ocr_backend": "rapidocr",
                "parse_failed": True,
            },
        },
        validation_report={
            "validation_passed": False,
            "errors": [
                {
                    "code": "local_parse_failed",
                    "path": "$",
                    "message": message,
                }
            ],
            "warnings": [],
            "info": [],
            "normalization_applied": [],
        },
        warnings=[message],
        error=message,
    )
