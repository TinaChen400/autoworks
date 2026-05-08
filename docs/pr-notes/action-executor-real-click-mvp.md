# Action Executor Real Click MVP

## Summary

Adds the minimal gated real click executor for Windows and fixes the capture/provenance and radio click coordinate issues needed to validate click-once execution end to end.

## Included Changes

- Real action executor reads only `runtime_state/latest_execution_gate.json`.
- Real execution is blocked unless the gate is allowed and each action is a reviewed `click_option`.
- Windows click execution uses `SendInput`.
- Executor records `actual_cursor_position` for real clicks.
- Panel capture refreshes runtime context and capture provenance.
- `run_once` preserves locked capture provenance instead of overwriting it with existing-capture provenance.
- Target resolver adjusts inferred radio/checkbox fallback click y so the point lands on the control instead of below it.

## Manual Validation

Manual click-once validation completed on Windows/KVM flow.

Branch: `feature/action-executor-real-click-mvp`

Verified pipeline state:

- `execution_gate.status = allowed`
- `execution_gate.execution_allowed = true`
- `executable_actions = 2`

Resolved click points after target resolver fix:

- q1 No: `click_point_screen = (721,573)`
- q2 No: `click_point_screen = (721,843)`

Real executor result:

- `real_execution = true`
- `executed_action_count = 2`
- q1 `actual_cursor_position = (721,573)`
- q2 `actual_cursor_position = (721,843)`
- errors: `[]`

Manual visual result:

- q1 No was selected on the target page.
- q2 No was selected on the target page.

## Regression Tests

```powershell
D:\Dev\autoworks\.venv\Scripts\python.exe -m pytest modules\action_executor\tests\test_action_executor_real.py modules\action_executor\tests\test_action_executor_preview.py modules\target_resolver\tests\test_target_resolver.py tests\test_autoworks_runner.py -q
```

Result:

```text
61 passed in 0.91s
```

## OCR-Guided Control Validation

Manual validation completed on `feature/ocr-guided-control-detection`.

Scenario:

- New single-choice page.
- Human review selected `q1 -> a3`.
- Perception was run with `--ocr rapidocr`.

Resolved OCR/control path:

- OCR option text: `T24`
- Detected control: `E93`
- `resolver_source = possible_option_label`
- `control_type = checkbox_like`
- `click_point_raw = (647,665)`
- `click_point_screen = (747,745)`

Real executor result:

- `option_id = a3`
- `status = clicked`
- `actual_cursor_position = (747,745)`

Manual visual result:

- Click landed in the correct target area.
- Page selected the intended option.

Regression tests after OCR-guided control detection:

```text
90 passed in 0.93s
```

## Follow-Up

The current radio y adjustment is a fallback, not the long-term targeting strategy. The next improvement should make target resolution generate multiple click candidates from visual control detection, then add closed-loop execution:

- click candidate
- capture after click
- verify selected state
- retry next candidate if needed
- stop safely if all candidates fail
