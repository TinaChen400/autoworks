from __future__ import annotations

PAGE_STRUCTURE_SCHEMA = {
    "page": {
        "questions": [
            {
                "question_id": "string",
                "question_type": "supported question type",
                "question_stem": {"text": "string", "bbox_norm": "BoundingBox"},
                "instructions": [{"text": "string", "bbox_norm": "BoundingBox"}],
                "answer_options": [
                    {
                        "option_id": "string",
                        "label": "string",
                        "text": "string",
                        "bbox_norm": "BoundingBox",
                        "media_refs": ["string"],
                    }
                ],
                "input_fields": [
                    {
                        "field_id": "string",
                        "field_type": "string",
                        "label": "string",
                        "bbox_norm": "BoundingBox",
                    }
                ],
                "media": [
                    {
                        "media_id": "string",
                        "media_type": "image|audio",
                        "role": "content|option",
                        "bbox_norm": "BoundingBox",
                    }
                ],
            }
        ],
        "navigation_buttons": [
            {"label": "string", "action": "string", "bbox_norm": "BoundingBox"}
        ],
    }
}

PROMPT_SCHEMA_TEXT = """
Return JSON only using this structure:
{
  "questions": [
    {
      "question_id": "q1",
      "question_type": "single_choice|multiple_choice|text_input|number_input|dropdown|...",
      "question_stem": {"text": "", "bbox_norm": {"x": 0, "y": 0, "width": 0, "height": 0}},
      "instructions": [{"text": "", "bbox_norm": {"x": 0, "y": 0, "width": 0, "height": 0}}],
      "answer_options": [
        {"option_id": "a1", "label": "", "text": "", "bbox_norm": "BoundingBox"}
      ],
      "input_fields": [
        {"field_id": "f1", "field_type": "", "label": "", "bbox_norm": "BoundingBox"}
      ],
      "media": [
        {"media_id": "m1", "media_type": "image|audio", "bbox_norm": "BoundingBox"}
      ]
    }
  ],
  "navigation_buttons": [
    {"label": "", "action": "", "bbox_norm": {"x": 0, "y": 0, "width": 0, "height": 0}}
  ],
  "uncertainties": []
}
""".strip()
