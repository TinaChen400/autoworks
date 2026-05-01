from __future__ import annotations

SUPPORTED_QUESTION_TYPES = [
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
]

PAGE_ELEMENT_TYPES = [
    "question_stem",
    "instruction_text",
    "answer_option",
    "input_field",
    "image_content",
    "image_option",
    "audio_content",
    "navigation_button",
    "form_field",
]


def normalize_question_types(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        if value not in SUPPORTED_QUESTION_TYPES:
            continue
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized
