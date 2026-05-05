from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.execution_safety import safety_store
from modules.execution_safety.safety_guard import evaluate_execution_safety_guard, run
from modules.execution_safety.schema import DEFAULT_EXECUTION_SAFETY_CONFIG


def _config(**overrides: object) -> dict:
    config = dict(DEFAULT_EXECUTION_SAFETY_CONFIG)
    config.update(overrides)
    return config


def _valid_config(**overrides: object) -> dict:
    config = _config(
        execution_mode="kvm_real",
        allow_real_execution=True,
        manual_start_confirmed=True,
        test_environment_confirmed=True,
    )
    config.update(overrides)
    return config


def _gate(allowed: bool = True) -> dict:
    return {
        "execution_gate_id": "execution_gate_1",
        "task_id": "tts01",
        "session_id": "session_1",
        "execution_allowed": allowed,
        "status": "allowed" if allowed else "blocked",
        "block_reasons": [] if allowed else [{"code": "blocked", "message": "Blocked."}],
    }


def _scheduler(status: str = "completed", skill: str = "left_click") -> dict:
    return {
        "scheduler_run_id": "scheduler_run_1",
        "task_id": "tts01",
        "session_id": "session_1",
        "status": status,
        "dry_run": True,
        "execution_allowed": True,
        "executed_actions": [{"action_id": "a1", "skill": skill, "dry_run": True}],
        "skipped_actions": [],
        "failures": [],
    }


def _preview(status: str = "completed", skill: str = "left_click", count: int = 1) -> dict:
    return {
        "action_executor_preview_id": "action_executor_preview_1",
        "task_id": "tts01",
        "session_id": "session_1",
        "status": status,
        "preview_mode": True,
        "real_execution": False,
        "preview_records": [
            {
                "record_type": "atomic_step",
                "action_id": f"a{index + 1}",
                "skill": skill,
                "click_point_screen": {"x": 100 + index, "y": 200 + index},
                "real_execution": False,
            }
            for index in range(count)
        ],
        "failures": [],
        "block_reasons": [],
    }


def _calibration(calibrated: bool = True) -> dict:
    return {
        "kvm_calibration_id": "kvm_calibration_1",
        "task_id": "tts01",
        "session_id": "session_1",
        "calibrated": calibrated,
        "anchor_frame": {"x": 0, "y": 0, "width": 1920, "height": 1080},
        "controlled_screen": {"width": 1920, "height": 1080},
        "scale": {"x": 1.0, "y": 1.0},
        "offset": {"x": 0, "y": 0},
        "validated_points": [],
        "warnings": [],
    }


def _calibration_report(valid: bool = True) -> dict:
    return {"validation_passed": valid, "issues": [], "warnings": []}


def _evaluate(
    config: dict | None = None,
    gate: dict | None = None,
    scheduler: dict | None = None,
    preview: dict | None = None,
    calibration: dict | None = None,
    calibration_report: dict | None = None,
) -> tuple[dict, dict]:
    return evaluate_execution_safety_guard(
        config if config is not None else _valid_config(),
        gate if gate is not None else _gate(),
        scheduler if scheduler is not None else _scheduler(),
        preview if preview is not None else _preview(),
        calibration if calibration is not None else _calibration(),
        calibration_report if calibration_report is not None else _calibration_report(),
    )


def _codes(guard: dict) -> set[str]:
    return {reason["code"] for reason in guard["block_reasons"]}


def _write_json(path: Path, payload: dict, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding=encoding)


def test_default_config_blocks_real_execution() -> None:
    guard, report = _evaluate(config=_config())

    assert report["validation_passed"] is True
    assert guard["real_execution_allowed"] is False
    assert guard["status"] == "blocked"
    assert "real_execution_disabled" in _codes(guard)


def test_allow_real_execution_false_blocks_even_if_pipeline_valid() -> None:
    guard, _ = _evaluate(config=_valid_config(allow_real_execution=False))

    assert guard["real_execution_allowed"] is False
    assert "real_execution_disabled" in _codes(guard)


def test_preview_mode_blocks_real_execution() -> None:
    guard, _ = _evaluate(config=_valid_config(execution_mode="preview"))

    assert guard["real_execution_allowed"] is False
    assert "execution_mode_not_kvm_real" in _codes(guard)


def test_kvm_real_blocks_if_manual_start_missing() -> None:
    config = _config(
        execution_mode="kvm_real",
        allow_real_execution=True,
        test_environment_confirmed=True,
    )

    guard, _ = _evaluate(config=config)

    assert guard["real_execution_allowed"] is False
    assert "manual_start_not_confirmed" in _codes(guard)


def test_kvm_real_blocks_if_test_environment_missing() -> None:
    config = _config(
        execution_mode="kvm_real",
        allow_real_execution=True,
        manual_start_confirmed=True,
    )

    guard, _ = _evaluate(config=config)

    assert guard["real_execution_allowed"] is False
    assert "test_environment_not_confirmed" in _codes(guard)


def test_missing_or_invalid_kvm_calibration_blocks_real_execution() -> None:
    guard, _ = _evaluate(
        calibration=_calibration(False),
        calibration_report=_calibration_report(False),
    )

    assert guard["real_execution_allowed"] is False
    assert {"kvm_not_calibrated", "kvm_calibration_report_invalid"} <= _codes(guard)


def test_blocked_skills_block_real_execution() -> None:
    blocked = {"submit", "click_next", "type_text", "press_key", "double_click"}

    for skill in blocked:
        guard, _ = _evaluate(scheduler=_scheduler(skill=skill), preview=_preview(skill=skill))
        codes = _codes(guard)
        assert guard["real_execution_allowed"] is False
        assert "mvp_real_skill_blocked" in codes


def test_too_many_candidate_actions_blocks_real_execution() -> None:
    guard, _ = _evaluate(preview=_preview(count=2))

    assert guard["real_execution_allowed"] is False
    assert "too_many_real_candidate_actions" in _codes(guard)


def test_one_allowed_click_candidate_passes_only_when_all_safety_flags_true() -> None:
    guard, report = _evaluate()

    assert report["validation_passed"] is True
    assert guard["real_execution_allowed"] is True
    assert guard["status"] == "allowed"
    assert guard["block_reasons"] == []
    assert guard["real_candidate_actions"][0]["skill"] == "left_click"


def test_output_json_has_no_utf8_bom(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    config_path = tmp_path / "execution_safety.json"
    _write_json(config_path, _config(), encoding="utf-8-sig")
    _write_json(runtime / "latest_execution_gate.json", _gate(), encoding="utf-8-sig")
    _write_json(runtime / "latest_scheduler_run.json", _scheduler())
    _write_json(runtime / "latest_action_executor_preview.json", _preview())
    _write_json(runtime / "latest_kvm_calibration.json", _calibration())
    _write_json(runtime / "latest_kvm_calibration_report.json", _calibration_report())

    run("auto", runtime, config_path)
    guard_path = runtime / "latest_execution_safety_guard.json"
    report_path = runtime / "latest_execution_safety_guard_report.json"

    assert not guard_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not report_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(guard_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(report_path)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_no_real_execution_calls_are_imported_or_used() -> None:
    package_dir = Path(safety_store.__file__).parent
    forbidden = (
        "import win32",
        "from win32",
        "import pyautogui",
        "SendInput",
        "SetCursorPos",
        "mouse_event",
        "import keyboard",
        "from keyboard",
    )

    for path in package_dir.glob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert not any(token in content for token in forbidden), path.name
