# Module Boundaries

Each module owns one part of the workflow. Modules should communicate through documented contracts rather than shared mutable state.

## `window_capture`

Can locate KVM windows and capture screenshots with window bounds.
Cannot parse survey content, decide answers, or perform input actions.

## `image_preprocess`

Can crop, normalize, and enhance captured images for downstream consumers.
Cannot call vision models, OCR services, or decide which answer is correct.

## `vision_parser`

Can define prompts, schemas, and client integration points for multimodal parsing.
Cannot store API secrets, execute UI actions, or make final answer decisions without the answer engine.

## `ocr_helper`

Can provide OCR extraction support and confidence hints.
Cannot be the sole authority for answer selection or click execution.

## `knowledge_base`

Can embed, index, and retrieve reference material.
Cannot inspect the live screen, call mouse actions, or override safety gates.

## `answer_engine`

Can combine parsed question data, options, confidence, and retrieved context into an answer decision.
Cannot map pixels, perform clicks, or bypass human confirmation.

## `coordinate_mapper`

Can map parsed visual locations to window-relative and screen-relative click targets.
Cannot choose answers or execute mouse input.

## `action_executor`

Can perform confirmed mouse and keyboard actions after safety validation.
Cannot parse screenshots, choose answers, or act without confirmation.

## `review_panel`

Can present screenshots, parsed data, proposed decisions, and click targets to the human reviewer.
Cannot silently execute actions or mutate model decisions without recording the reviewer choice.
