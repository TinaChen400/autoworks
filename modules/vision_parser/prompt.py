from __future__ import annotations

from modules.vision_parser.schema import ELEMENT_TYPES, QUESTION_TYPES

STRICT_INSTRUCTIONS = [
    "Do not answer the task.",
    "Do not click anything.",
    "Do not call OCR.",
    "Do not reuse previous coordinates.",
    "Return JSON only.",
    "Use normalized coordinates relative to the model input screenshot region.",
    "Distinguish all required page elements.",
    "Include uncertainties when something is unclear.",
]

PARSED_PAGE_SCHEMA_PROMPT = """
Required ParsedPage JSON shape:
{
  "parse_id": "string",
  "task_id": "string",
  "page": {
    "page_type": "questionnaire|form|image_task|audio_task|unknown",
    "language": "en|zh|unknown",
    "page_status": "active_question_page|form_page|unknown",
    "confidence": 0.0
  },
  "questions": [
    {
      "question_id": "q1",
      "question_type": "single_choice|multiple_choice|text_input|number_input|dropdown|...",
      "question_stem": {
        "text": "",
        "bbox_norm": {"x": 0, "y": 0, "width": 0, "height": 0}
      },
      "instructions": [],
      "answer_options": [],
      "input_fields": [],
      "media": [],
      "matrix": null,
      "confidence": 0.0,
      "requires_human_review": false
    }
  ],
  "navigation_buttons": [],
  "uncertainties": []
}
""".strip()


def get_supported_question_types(runtime_context: dict) -> list[str]:
    configured = runtime_context.get("supported_question_types") or []
    supported = [value for value in configured if value in QUESTION_TYPES]
    return supported or sorted(QUESTION_TYPES)


def build_final_prompt(runtime_context: dict) -> str:
    base_prompt = str(runtime_context.get("vision_prompt", "")).strip()
    supported = ", ".join(get_supported_question_types(runtime_context))
    elements = ", ".join(sorted(ELEMENT_TYPES))
    strict = "\n".join(f"- {line}" for line in STRICT_INSTRUCTIONS)
    task_id = runtime_context.get("task_id", "")

    return f"""
{base_prompt}

Strict vision_parser instructions:
{strict}

Task id: {task_id}
Supported question types for this runtime context: {supported}
Required page element types: {elements}

Keep navigation buttons out of answer_options. Every answer option must belong to exactly one
question. If visible media is too small, cropped, ambiguous, or may require audio understanding,
add an uncertainty and set the relevant review flag.

{PARSED_PAGE_SCHEMA_PROMPT}
""".strip()
