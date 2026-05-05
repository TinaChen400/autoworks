from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.kvm_calibration import calibration_store
from modules.kvm_calibration.kvm_calibrator import build_kvm_calibration, run_calibration


def _write_json(path: Path, payload: dict, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding=encoding)


_DEFAULT_ANCHOR_FRAME = object()


def _runtime_context(anchor_frame: dict | object | None = _DEFAULT_ANCHOR_FRAME) -> dict:
    context = {
        "task_id": "tts01",
        "anchor_frame": {"x": 100, "y": 80, "width": 1920, "height": 1080},
        "image_size": {"width": 1920, "height": 1080},
        "raw_screenshot": {"x": 0, "y": 0, "width": 1920, "height": 1080},
        "model_input_region": {"x": 0, "y": 0, "width": 1920, "height": 1080},
        "coordinate_policy": {
            "formula": "screen_x = anchor_frame.x + raw_x; screen_y = anchor_frame.y + raw_y"
        },
    }
    if anchor_frame is None:
        context.pop("anchor_frame")
    elif anchor_frame is _DEFAULT_ANCHOR_FRAME:
        pass
    else:
        context["anchor_frame"] = anchor_frame
    return context


def _resolved_plan(point: dict | None = None) -> dict:
    target = {"question_id": "q1", "option_id": "T21", "option_text": "AmazonCentral"}
    if point is not None:
        target["click_point_screen"] = point
    return {
        "resolved_action_plan_id": "resolved_action_plan_1",
        "task_id": "tts01",
        "session_id": "session_1",
        "status": "ready",
        "actions": [{"action_id": "a1", "skill": "click_option", "target": target}],
    }


def _preview(point: dict | None = None) -> dict:
    record = {
        "record_type": "action",
        "action_id": "a1",
        "skill": "click_option",
        "option_id": "T21",
        "option_text": "AmazonCentral",
        "real_execution": False,
    }
    if point is not None:
        record["click_point_screen"] = point
    return {
        "action_executor_preview_id": "action_executor_preview_1",
        "task_id": "tts01",
        "session_id": "session_1",
        "status": "completed",
        "preview_mode": True,
        "real_execution": False,
        "preview_records": [record],
        "failures": [],
        "block_reasons": [],
    }


def test_valid_runtime_context_produces_calibrated_true() -> None:
    calibration, report = build_kvm_calibration(
        _runtime_context(),
        _resolved_plan({"x": 799, "y": 612}),
        _preview({"x": 799, "y": 612}),
    )

    assert calibration["calibrated"] is True
    assert report["validation_passed"] is True
    assert calibration["anchor_frame"] == {"x": 100, "y": 80, "width": 1920, "height": 1080}
    assert calibration["controlled_screen"] == {"width": 1920, "height": 1080}
    assert calibration["scale"] == {"x": 1.0, "y": 1.0}
    assert calibration["offset"] == {"x": 100, "y": 80}


def test_preview_click_point_inside_viewport_passes() -> None:
    calibration, report = build_kvm_calibration(
        _runtime_context(),
        _resolved_plan({"x": 799, "y": 612}),
        _preview({"x": 799, "y": 612}),
    )

    point = calibration["validated_points"][0]
    assert point["inside_viewport"] is True
    assert point["screen_point"] == {"x": 799, "y": 612}
    assert point["kvm_viewport_point"] == {"x": 699, "y": 532}
    assert point["roundtrip_screen_point"] == {"x": 799, "y": 612}
    assert report["issues"] == []


def test_point_outside_viewport_creates_validation_issue() -> None:
    calibration, report = build_kvm_calibration(
        _runtime_context(),
        _resolved_plan({"x": 2500, "y": 612}),
        _preview({"x": 2500, "y": 612}),
    )

    assert calibration["calibrated"] is False
    assert calibration["validated_points"][0]["inside_viewport"] is False
    assert any(issue["type"] == "point_outside_viewport" for issue in report["issues"])


def test_missing_anchor_frame_blocks_calibration() -> None:
    calibration, report = build_kvm_calibration(
        _runtime_context(anchor_frame=None),
        _resolved_plan({"x": 799, "y": 612}),
        _preview({"x": 799, "y": 612}),
    )

    assert calibration["calibrated"] is False
    assert any(issue["type"] == "missing_anchor_frame" for issue in report["issues"])
    assert calibration["validated_points"] == []


def test_output_json_has_no_utf8_bom(tmp_path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_runtime_context.json", _runtime_context(), encoding="utf-8-sig")
    _write_json(runtime / "latest_resolved_action_plan.json", _resolved_plan({"x": 799, "y": 612}))
    _write_json(runtime / "latest_action_executor_preview.json", _preview({"x": 799, "y": 612}))

    run_calibration("auto", runtime)
    calibration_path = runtime / "latest_kvm_calibration.json"
    report_path = runtime / "latest_kvm_calibration_report.json"

    assert not calibration_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not report_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(calibration_path)],
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


def test_no_real_os_or_mouse_keyboard_calls_are_used() -> None:
    package_dir = Path(calibration_store.__file__).parent
    forbidden = (
        "import win32",
        "from win32",
        "import pyautogui",
        "import ctypes",
        "SendInput(",
        "mouse_event(",
        "keybd_event(",
    )

    for path in package_dir.glob("*.py"):
        content = path.read_text(encoding="utf-8")
        if path.name == "test_kvm_calibration.py":
            continue
        assert not any(token in content for token in forbidden)
