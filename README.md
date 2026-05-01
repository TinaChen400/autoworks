# Autoworks

Autoworks is a Windows-based KVM visual survey automation assistant. The project is intended to observe a KVM-displayed survey screen, parse the visual question state, decide an answer with knowledge-base support, map the answer back to screen coordinates, request human confirmation, and only then execute a mouse action.

This repository currently contains only the initial architecture scaffold. Business logic, model calls, OCR calls, GUI implementation, and mouse/keyboard execution are intentionally not implemented yet.

## Current Scope

- Project folders and Python module boundaries.
- Initial architecture and contract documentation.
- Agent role prompts for architecture, implementation, and review work.
- Empty Python files for future implementation.

## Safety Principles

- No API keys or secrets belong in the repository.
- Mouse and keyboard actions must remain gated behind safety checks and human confirmation.
- Frozen modules may be read or imported, but cannot be modified without explicit approval.

## Layout

- `app/`: application entrypoint and configuration surface.
- `modules/`: bounded implementation areas for capture, parsing, OCR, retrieval, answering, coordinate mapping, action execution, and review UI.
- `docs/`: architecture, contracts, module boundaries, frozen-module policy, changelog, and agent prompts.
- `tests/`: integration tests and fixtures.
