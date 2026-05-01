# API Contracts

All module boundaries should use explicit, JSON-serializable contracts. Field names are stable unless changed through architecture review.

## WindowBox

```json
{
  "window_id": "string",
  "title": "string",
  "left": 0,
  "top": 0,
  "width": 0,
  "height": 0,
  "dpi_scale": 1.0,
  "captured_at": "2026-05-01T00:00:00Z"
}
```

## ParsedQuestion

```json
{
  "question_id": "string",
  "question_text": "string",
  "question_type": "single_choice",
  "options": [],
  "visual_regions": [],
  "confidence": 0.0,
  "source": "vision_parser"
}
```

## Option

```json
{
  "option_id": "string",
  "label": "A",
  "text": "string",
  "bounding_box": {
    "left": 0,
    "top": 0,
    "width": 0,
    "height": 0
  },
  "confidence": 0.0
}
```

## AnswerDecision

```json
{
  "decision_id": "string",
  "question_id": "string",
  "selected_option_id": "string",
  "answer_text": "string",
  "confidence": 0.0,
  "rationale": "string",
  "evidence_refs": [],
  "requires_human_review": true
}
```

## ClickTarget

```json
{
  "target_id": "string",
  "question_id": "string",
  "option_id": "string",
  "window_x": 0,
  "window_y": 0,
  "screen_x": 0,
  "screen_y": 0,
  "safety_state": "pending_review"
}
```
