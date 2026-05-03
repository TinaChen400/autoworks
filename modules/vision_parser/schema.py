from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

PAGE_TYPES = {"questionnaire", "form", "image_task", "audio_task", "unknown"}
LANGUAGES = {"en", "zh", "unknown"}
PAGE_STATUSES = {"active_question_page", "form_page", "unknown"}

ELEMENT_TYPES = {
    "page_title",
    "section_title",
    "question_stem",
    "instruction_text",
    "answer_option",
    "input_field",
    "button",
    "image_content",
    "image_option",
    "audio_content",
    "draggable_item",
    "drop_zone",
    "matrix_cell",
    "card",
    "text",
    "unknown",
    "navigation_button",
    "form_field",
}

ELEMENT_ROLES = ELEMENT_TYPES

QUESTION_TYPES = {
    "single_choice",
    "multiple_choice",
    "text_input",
    "number_input",
    "dropdown",
    "rating_scale",
    "matrix_single",
    "matrix_multiple",
    "image_choice",
    "image_reasoning",
    "audio_choice",
    "audio_input",
    "form_field",
    "date_input",
    "file_upload",
    "unknown",
}

OPTION_TYPES = {"text_option", "image_option", "button_option", "unknown"}
SELECTION_CONTROLS = {"radio", "checkbox", "button", "none", "unknown"}
FIELD_TYPES = {"text", "number", "date", "email", "textarea", "dropdown", "unknown"}
MEDIA_TYPES = {"image", "audio", "video", "unknown"}
MEDIA_ROLES = {"question_media", "answer_option_media", "instruction_media", "unknown"}
NAV_ACTIONS = {"next_page", "previous_page", "submit", "continue", "skip", "unknown"}


def empty_bbox() -> dict[str, float]:
    return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}


def empty_point() -> dict[str, float]:
    return {"x": 0.0, "y": 0.0}


def sample_parsed_page(task_id: str = "") -> dict[str, Any]:
    return {
        "parse_id": f"parse_{uuid.uuid4().hex}",
        "task_id": task_id,
        "page": {
            "page_type": "unknown",
            "language": "unknown",
            "page_status": "unknown",
            "confidence": 0.1,
        },
        "questions": [
            {
                "question_id": "q1",
                "question_type": "unknown",
                "question_stem": {"text": "", "bbox_norm": empty_bbox()},
                "instructions": [],
                "answer_options": [],
                "input_fields": [],
                "media": [],
                "matrix": None,
                "confidence": 0.1,
                "requires_human_review": True,
            }
        ],
        "navigation_buttons": [],
        "uncertainties": [
            {
                "type": "fake_mode",
                "message": "Fake mode returns a schema-valid placeholder parse only.",
                "related_question_id": "q1",
            }
        ],
    }


def normalize_parsed_page(data: dict[str, Any], task_id: str = "") -> dict[str, Any]:
    normalized = deepcopy(data)
    normalized.setdefault("parse_id", f"parse_{uuid.uuid4().hex}")
    normalized.setdefault("task_id", task_id)
    normalized.setdefault(
        "page",
        {
            "page_type": "unknown",
            "language": "unknown",
            "page_status": "unknown",
            "confidence": 0.0,
        },
    )
    normalized.setdefault("questions", [])
    normalized.setdefault("navigation_buttons", [])
    normalized.setdefault("visual_elements", [])
    normalized.setdefault("uncertainties", [])
    return normalized
