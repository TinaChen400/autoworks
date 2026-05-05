# Local Real Click Test

This test page is the only intended target for the guarded real-click MVP.

## Safety Defaults

- `config/local_real_click_test.json` is committed with `"enabled": false`.
- The runner refuses to click without `--confirm-local-html-test`.
- The runner requires `latest_execution_safety_guard.json` to be allowed.
- The runner requires `latest_kvm_calibration.json` to have `"calibrated": true`.
- The runner accepts exactly one real action group with `logical_skill: "click_option"`.
- The runner never submits, clicks next, types text, presses keys, or performs more than one click.

## Manual Local Run

Open `tools/local_html_click_test.html` locally in a browser, position it so the calibrated click point targets the checkbox, and only then enable the local test config.

```powershell
python -m modules.action_executor.local_real_click_runner --source auto --confirm-local-html-test
```

Create `runtime_state/STOP_REAL_CLICK` before or during the countdown to cancel safely.
