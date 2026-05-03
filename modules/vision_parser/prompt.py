from __future__ import annotations

from modules.vision_parser.schema import ELEMENT_TYPES, QUESTION_TYPES

SUPPORTED_PARSER_TYPES = {
    "form",
    "survey",
    "image_task",
    "drag_drop",
    "matrix",
    "modal",
    "general",
    "scene_scan",
}

SUPPORTED_OUTPUT_LEVELS = {"light", "standard"}

STRICT_INSTRUCTIONS = [
    "Return useful recognition first.",
    "Do not answer the task.",
    "Do not click anything.",
    "Do not call OCR.",
    "Do not reuse previous coordinates.",
    "Return JSON only.",
    "Use normalized coordinates relative to the model input screenshot region.",
    "Do not force every page into questions.",
    "Use visual_elements for any visible important UI elements.",
    "For unknown pages, return page summary plus visual_elements.",
    "If enum fields are unclear, use unknown; the local parser also tolerates missing optional fields.",
    "Include uncertainties when something is unclear.",
]

PARSED_PAGE_SCHEMA_PROMPT = """
Preferred ParsedPage JSON shape:
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
  "visual_elements": [
    {
      "element_id": "",
      "element_role": "page_title|section_title|question_stem|instruction_text|answer_option|input_field|form_field|button|navigation_button|image_content|image_option|audio_content|draggable_item|drop_zone|matrix_cell|card|text|unknown",
      "text": "",
      "label": "",
      "bbox_norm": {"x": 0, "y": 0, "width": 0, "height": 0},
      "click_point_norm": {"x": 0, "y": 0},
      "raw_type": "",
      "confidence": 0.0,
      "metadata": {}
    }
  ],
  "navigation_buttons": [],
  "uncertainties": []
}
""".strip()

LIGHT_FORM_PROMPT = """
Return JSON only. Do not answer the task or click.
Use normalized bbox coordinates for visible items when possible.

Parser type: form
Return compact JSON with only:
- page_summary: page_type, language, summary
- visual_elements: important visible text/cards/sections/buttons
- input_fields: labels/values/empty fields if visible
- navigation_buttons: visible next/submit/continue/back buttons
- uncertainties: unclear or cropped content

Shape:
{
  "page_summary": {"page_type": "form|unknown", "language": "en|zh|unknown", "summary": ""},
  "visual_elements": [{"element_role": "", "text": "", "bbox_norm": {"x": 0, "y": 0, "width": 0, "height": 0}}],
  "input_fields": [],
  "navigation_buttons": [],
  "uncertainties": []
}
""".strip()

LIGHT_SURVEY_PROMPT = """
Return JSON only. Do not answer the task or click.
Use normalized bbox coordinates for visible items when possible.

Parser type: survey
Return compact JSON with only:
- page_summary: page_type, language, summary
- questions: question stem, instructions, answer options, visible controls
- navigation_buttons: visible next/submit/continue/back buttons
- visual_elements: important visible UI/text
- uncertainties: unclear or cropped content

Shape may include:
{
  "page_summary": {"page_type": "questionnaire|unknown", "language": "en|zh|unknown", "summary": ""},
  "questions": [{"question_stem": {"text": "", "bbox_norm": {}}, "instructions": [], "answer_options": [], "controls": []}],
  "navigation_buttons": [],
  "visual_elements": [],
  "uncertainties": []
}
""".strip()

SCENE_SCAN_SCHEMA_PROMPT = """
Required scene_scan JSON shape:
{
  "detected_page_type": "string",
  "layout_type": "string",
  "detected_interaction_types": [],
  "recommended_parser": "form|survey|image_task|drag_drop|matrix|modal|general|scene_scan",
  "confidence": 0.0,
  "reason": "string"
}
""".strip()

PARSER_SPECIFIC_INSTRUCTIONS = {
    "form": [
        "Focus on form sections, fields, labels, values, action links, and buttons.",
        "Prefer element_id and region_id if visible in the annotated image.",
        "Do not answer questions.",
        "Do not click.",
    ],
    "survey": [
        "Focus on question stem, instructions, answer options, radio or checkbox controls, and navigation buttons.",
        "Prefer element_id and region_id if visible.",
        "Do not answer.",
    ],
    "image_task": [
        "Focus on image content, image options, question text, and answer options.",
        "Identify ambiguity, but do not answer.",
    ],
    "drag_drop": [
        "Focus on draggable items, source areas, target or drop zones, and matching relationships.",
        "Do not decide final drag actions.",
    ],
    "matrix": [
        "Focus on row labels, column labels, matrix cells, and radio or checkbox matrix controls.",
    ],
    "modal": [
        "Focus on modal title, body text, close buttons, confirm buttons, and cancel buttons.",
    ],
    "general": [
        "Use general page parsing behavior and identify all visible task-relevant page elements.",
    ],
    "scene_scan": [
        "Return short classification JSON only.",
        "Classify the visible page type, layout type, interaction types, recommended parser, confidence, and reason.",
    ],
}


def get_supported_question_types(runtime_context: dict) -> list[str]:
    configured = runtime_context.get("supported_question_types") or []
    supported = [value for value in configured if value in QUESTION_TYPES]
    return supported or sorted(QUESTION_TYPES)


def build_final_prompt(
    runtime_context: dict,
    parser_type: str = "general",
    output_level: str = "standard",
) -> str:
    selected_parser_type = parser_type if parser_type in SUPPORTED_PARSER_TYPES else "general"
    selected_output_level = output_level if output_level in SUPPORTED_OUTPUT_LEVELS else "standard"
    if selected_output_level == "light" and selected_parser_type in {"form", "survey"}:
        task_id = runtime_context.get("task_id", "")
        task_type = runtime_context.get("task_type") or runtime_context.get("page_type") or ""
        light_prompt = LIGHT_FORM_PROMPT if selected_parser_type == "form" else LIGHT_SURVEY_PROMPT
        return f"""
Task id: {task_id}
Task hint: {task_type}
Output level: light

{light_prompt}
""".strip()

    base_prompt = str(runtime_context.get("vision_prompt", "")).strip()
    supported = ", ".join(get_supported_question_types(runtime_context))
    elements = ", ".join(sorted(ELEMENT_TYPES))
    strict = "\n".join(f"- {line}" for line in STRICT_INSTRUCTIONS)
    parser_specific = "\n".join(
        f"- {line}" for line in PARSER_SPECIFIC_INSTRUCTIONS[selected_parser_type]
    )
    task_id = runtime_context.get("task_id", "")
    schema_prompt = (
        SCENE_SCAN_SCHEMA_PROMPT
        if selected_parser_type == "scene_scan"
        else PARSED_PAGE_SCHEMA_PROMPT
    )

    return f"""
{base_prompt}

Strict vision_parser instructions:
{strict}

Parser type: {selected_parser_type}
Parser-specific instructions:
{parser_specific}

Task id: {task_id}
Supported question types for this runtime context: {supported}
Required page element types: {elements}

Keep navigation buttons out of answer_options. Every answer option must belong to exactly one
question. If visible media is too small, cropped, ambiguous, or may require audio understanding,
add an uncertainty and set the relevant review flag.

{schema_prompt}
""".strip()
