# Autoworks

Autoworks is a Windows-based KVM visual survey automation assistant. The project is intended to observe a KVM-displayed survey screen, parse the visual question state, decide an answer with knowledge-base support, map the answer back to screen coordinates, request human confirmation, and only then execute a mouse action.

This repository is being implemented module by module. Model calls, OCR calls, answer generation, knowledge-base retrieval, and questionnaire mouse/keyboard execution are intentionally not implemented yet.

## Current Scope

- `window_capture`: implemented MVP for selecting, snapping, locking and capturing a fixed AnchorFrame.
- `context_mapper`: implemented MVP for task context loading, prompt preparation, screenshot region metadata and coordinate conversion.
- Model calls, OCR calls, answer generation, knowledge-base retrieval and questionnaire mouse/keyboard execution are not implemented yet.

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

The panel lists visible top-level windows. It does not exclude the current foreground window; it only excludes the Autoworks panel itself, invisible windows, and unsuitable child/internal windows where possible. When several windows have the same title, use the `hwnd`, `class_name`, `process_id`, and current `x,y,width,height` columns to choose the correct target. Anchor sizing is fixed from `config/anchor_profile.json` as `base_width/base_height * scale`; supported scales are `1`, `1.25`, and `1.5`.

- `Scale`: choose the fixed AnchorFrame multiplier.
- `Use Current Window Position as Anchor Origin`: save only the selected hwnd's current `x/y` origin to `config/anchor_profile.json`, and save its title/class identity to `config/target_profile.json`.
- `Select Saved Target`: select the visible window that uniquely matches `config/target_profile.json`.
- `Snap`: move and resize the selected hwnd to the saved AnchorFrame from `config/anchor_profile.json`.
- `Lock`: snap the selected hwnd and keep restoring only that hwnd if it moves or resizes.
- `Unlock`: stop the restore loop.
- `Capture`: save the saved AnchorFrame region to `tests/fixtures/latest_capture.png`.

The always-on-top AnchorFrame overlay is blue when an AnchorFrame exists but no target is locked, and green when the selected target hwnd is locked and being enforced inside the AnchorFrame.

## Context Mapper

The second module prepares reusable task context, prompt sections, page-region metadata, and coordinate conversion. It does not call Doubao, OCR, or any external model, and it does not click the mouse.

Load the sample learned task:

```powershell
python -m modules.context_mapper.task_context_loader --task tts01
```

Generate runtime context from the saved AnchorFrame profile and the latest fixture capture when available:

```powershell
python -m modules.context_mapper.capture_context --task tts01
```

Test model-normalized coordinate conversion using `runtime_state/latest_runtime_context.json`:

```powershell
python -m modules.context_mapper.coordinate_mapper --x 0.5 --y 0.5
```

Open the Tkinter panel:

```powershell
python -m modules.context_mapper.panel
```

Run the lightweight tests:

```powershell
python -m pytest modules/context_mapper/tests
```

`context_mapper` stores configurable screenshot crop margins in task context data and writes derived regions to `runtime_state/latest_runtime_context.json`:

- `RawScreenshot`: the full captured AnchorFrame image.
- `ContentRegion`: useful remote/page content after configured margins.
- `IgnoreRegion`: margins such as borders or toolbars.
- `ModelInputRegion`: the region later intended for multimodal parsing.

Future task learning can reuse this module by creating a draft task context from a reviewed screenshot parse, extracting reusable layout and answer rules, selecting a task family, and saving only general rules. Fixed answer coordinates are intentionally rejected from reusable task memory.
