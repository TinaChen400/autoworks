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

## Perception Indexer

The fourth module builds a local visual radar map from the latest captured screenshot. It uses local image processing only: no Doubao calls, no multimodal model calls, no answer decisions, and no mouse actions. The output gives later `parse_orchestrator` and `vision_parser` stable region, element, and optional OCR text IDs to refer to instead of relying only on model-estimated coordinates.

Run the CLI after `context_mapper` has written `runtime_state/latest_runtime_context.json`:

```powershell
python -m modules.perception_indexer.indexer --ocr disabled
```

Open the Tkinter panel:

```powershell
python -m modules.perception_indexer.panel
```

Runtime outputs:

- `runtime_state/latest_layout_index.json`: structured layout index with `R*` region IDs, `E*` element IDs, optional `T*` OCR text IDs, relationships, layout hints, and crop safety metadata.
- `runtime_state/latest_annotated_overview.png`: full screenshot overview annotated with region, element, and text IDs.
- `runtime_state/crops/`: focused region crops and annotated crop variants.
- `runtime_state/latest_perception_report.json`: counts, warnings, OCR backend, and output paths.

The indexer detects a conservative `web_viewport` region and then creates card or form-section regions when local geometry suggests business sections. With OCR disabled these card labels are heuristic; with OCR enabled, section titles and field labels can produce `T*` text blocks and stronger text-to-region or text-to-element relationships.

`parse_orchestrator` can later use this index to choose whether to send the full screenshot, annotated overview, or a focused crop to a parser. Crops are only acceleration inputs; the full screenshot is always preserved and referenced. Each crop includes safety hints for the risk of cropping out question context, answer options, input fields, or navigation buttons.

Known limitations:

- MVP element detection is heuristic and local-image based.
- OCR is optional and may be inaccurate depending on the backend.
- Candidate boxes are hints, not final semantic truth.
- Crops do not replace the full screenshot.
- No answers are decided.
- No mouse or keyboard actions are executed.

## Parse Orchestrator

The fifth module is the strategy layer between `perception_indexer` and `vision_parser`. It reads the latest runtime context, layout index, annotated overview, and region crops, then decides which parser type and image inputs should be used for a single parse. It does not decide answers, click, call OCR, or call Doubao directly.

Run fake mode:

```powershell
python -m modules.parse_orchestrator.orchestrator --mode fake
```

Run Doubao mode through `vision_parser`:

```powershell
python -m modules.parse_orchestrator.orchestrator --mode doubao
```

Open the local Tkinter panel:

```powershell
python -m modules.parse_orchestrator.panel
```

Runtime outputs:

- `runtime_state/latest_parse_plan.json`: selected strategy, parser type, selected regions, crop paths, fallback policy, detector scores, and crop safety summary.
- `runtime_state/latest_parse_metrics.json`: model-call count, elapsed time, validation status, fallback use, final page type/confidence, warnings, and image inputs used.
- `runtime_state/latest_orchestrated_parse.json`: downstream contract for later `answer_engine`, including `parsed_page`, region references when available, parse plan, metrics, review flag, and warnings.
- `runtime_state/latest_parse_orchestrator_report.json`: concise CLI/panel report.

For the current form/card fixture, `perception_indexer` recommends business card regions `R9` through `R13`. `parse_orchestrator` selects those regions for direct form parsing when the form detector is strongest, prefers annotated card crops when they are available, marks unsafe crops in the plan, and preserves a full screenshot fallback.

Known limitations:

- MVP does not decide answers.
- MVP does not click.
- MVP depends on `perception_indexer` layout-index quality.
- If `vision_parser` cannot yet consume custom crop inputs, the plan still records selected crop paths but the parser may use the existing runtime context.
- Automatic retry is minimal.
- Complex survey, image, drag-drop, and matrix strategies are stub-level until detectors are implemented.
