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

## Window Capture Panel

Run the first module on Windows with:

```powershell
python -m modules.window_capture.panel
```

The panel lists visible windows, excluding the current foreground window at refresh time. When several windows have the same title, use the `hwnd`, `class_name`, `process_id`, and current `x,y,width,height` columns to choose the correct target. Anchor sizing is fixed from `config/anchor_profile.json` as `base_width/base_height * scale`; supported scales are `1`, `1.25`, and `1.5`.

- `Scale`: choose the fixed AnchorFrame multiplier.
- `Use Current Window Position as Anchor Origin`: save only the selected hwnd's current `x/y` origin to `config/anchor_profile.json`, and save its title/class identity to `config/target_profile.json`.
- `Select Saved Target`: select the visible window that uniquely matches `config/target_profile.json`.
- `Snap`: move and resize the selected hwnd to the saved AnchorFrame from `config/anchor_profile.json`.
- `Lock`: snap the selected hwnd and keep restoring only that hwnd if it moves or resizes.
- `Unlock`: stop the restore loop.
- `Capture`: save the saved AnchorFrame region to `tests/fixtures/latest_capture.png`.

The always-on-top AnchorFrame overlay is blue when an AnchorFrame exists but no target is locked, and green when the selected target hwnd is locked and being enforced inside the AnchorFrame.
