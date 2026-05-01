# Architecture

Autoworks is a Windows-based assistant for visually completing surveys shown through a KVM display. The system treats the KVM window as the source of truth and uses a gated workflow so that automated actions are never executed without review.

## Workflow

1. Window capture locates the target KVM window and records a screenshot plus window bounds.
2. Image preprocessing crops and enhances the screenshot so downstream vision and OCR components receive a clean representation of the active survey area.
3. The multimodal vision parser receives the prepared screenshot and extracts the visible question, options, layout hints, and confidence signals.
4. Optional OCR helper output can be used to cross-check text extraction when the visual model is uncertain or when small text needs validation.
5. The knowledge base retrieves relevant local reference material, prior instructions, or domain-specific notes that may inform the answer.
6. The answer engine combines parsed question data, options, confidence, and retrieved context to produce an answer decision.
7. The coordinate mapper converts the selected option or control into a click target in window-relative and screen-relative coordinates.
8. The review panel presents the screenshot, parsed question, candidate answer, evidence, and intended click target for human confirmation.
9. The action executor performs mouse or keyboard interaction only after the safety guard verifies the target and the human has confirmed the action.

## Data Flow

`KVM window screenshot -> image preprocessing -> multimodal model -> parsed question -> knowledge base retrieval -> answer decision -> coordinate mapping -> human confirmation -> mouse action`

## Safety Gates

- Model calls do not directly control the mouse.
- Coordinate mapping does not execute clicks.
- The review panel must expose the intended action before execution.
- The action executor must reject actions that lack explicit confirmation or fail safety validation.
