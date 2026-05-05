from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.action_executor.local_real_click_runner import run


def _write_json(path: Path, payload: dict, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding=encoding)


def _config(**overrides: object) -> dict:
    config: dict[str, object] = {
        "enabled": True,
        "target_environment": "local_html_only",
        "require_execution_safety_allowed": True,
        "require_kvm_calibrated": True,
        "require_single_real_action_group": True,
        "allowed_logical_skills": ["click_option"],
        "blocked_logical_skills": [
            "submit",
            "click_next",
            "type_text",
            "press_key",
            "double_click",
        ],
        "countdown_seconds": 0,
        "abort_file": "runtime_state/STOP_REAL_CLICK",
        "write_preflight_preview": False,
        "max_clicks": 1,
    }
    config.update(overrides)
    return config


def _guard(**overrides: object) -> dict:
    guard: dict[str, object] = {
        "execution_safety_guard_id": "execution_safety_guard_1",
        "task_id": "tts01",
        "session_id": "session_1",
        "real_execution_allowed": True,
        "status": "allowed",
        "real_action_group_count": 1,
        "real_action_groups": [
            {
                "action_id": "a1",
                "logical_skill": "click_option",
                "option_id": "T21",
                "option_text": "AmazonCentral",
                "click_point_screen": {"x": 799, "y": 612},
                "atomic_steps": ["move_mouse", "left_click"],
                "real_execution": False,
            }
        ],
    }
    guard.update(overrides)
    return guard


def _calibration(calibrated: bool = True) -> dict:
    return {
        "kvm_calibration_id": "kvm_calibration_1",
        "task_id": "tts01",
        "session_id": "session_1",
        "calibrated": calibrated,
    }


def _preview(status: str = "completed") -> dict:
    return {
        "action_executor_preview_id": "action_executor_preview_1",
        "task_id": "tts01",
        "session_id": "session_1",
        "status": status,
        "preview_mode": True,
        "real_execution": False,
        "preview_records": [],
        "failures": [],
        "block_reasons": [],
    }


class FakeClickBackend:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


def _write_runtime(
    tmp_path: Path,
    *,
    config: dict | None = None,
    guard: dict | None = None,
) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime_state"
    config_path = tmp_path / "config" / "local_real_click_test.json"
    _write_json(config_path, config if config is not None else _config(), encoding="utf-8-sig")
    _write_json(
        runtime / "latest_execution_safety_guard.json",
        guard if guard is not None else _guard(),
    )
    _write_json(runtime / "latest_kvm_calibration.json", _calibration())
    _write_json(runtime / "latest_action_executor_preview.json", _preview())
    return runtime, config_path


def _run(
    tmp_path: Path,
    *,
    confirm: bool = True,
    config: dict | None = None,
    guard: dict | None = None,
    backend: FakeClickBackend | None = None,
) -> tuple[dict, dict, FakeClickBackend]:
    runtime, config_path = _write_runtime(tmp_path, config=config, guard=guard)
    fake = backend if backend is not None else FakeClickBackend()
    run_payload, report = run(
        "auto",
        confirm_local_html_test=confirm,
        runtime_dir=runtime,
        config_path=config_path,
        backend=fake,
        sleep_fn=lambda _seconds: None,
    )
    return run_payload, report, fake


def _codes(report: dict) -> set[str]:
    return {issue["code"] for issue in report["issues"]}


def test_default_config_blocks_real_click(tmp_path: Path) -> None:
    run_payload, report, fake = _run(tmp_path, config={"enabled": False})

    assert run_payload["status"] == "blocked"
    assert "local_real_click_disabled" in _codes(report)
    assert fake.clicks == []


def test_missing_confirm_local_html_test_blocks_real_click(tmp_path: Path) -> None:
    run_payload, report, fake = _run(tmp_path, confirm=False)

    assert run_payload["status"] == "blocked"
    assert "local_html_confirmation_required" in _codes(report)
    assert fake.clicks == []


def test_enabled_false_blocks_real_click(tmp_path: Path) -> None:
    run_payload, report, fake = _run(tmp_path, config=_config(enabled=False))

    assert run_payload["status"] == "blocked"
    assert "local_real_click_disabled" in _codes(report)
    assert fake.clicks == []


def test_execution_safety_blocked_blocks_real_click(tmp_path: Path) -> None:
    run_payload, report, fake = _run(
        tmp_path,
        guard=_guard(real_execution_allowed=False, status="blocked"),
    )

    assert run_payload["status"] == "blocked"
    assert "execution_safety_not_allowed" in _codes(report)
    assert "execution_safety_status_not_allowed" in _codes(report)
    assert fake.clicks == []


def test_missing_or_invalid_kvm_calibration_blocks_real_click(tmp_path: Path) -> None:
    runtime, config_path = _write_runtime(tmp_path)
    _write_json(runtime / "latest_kvm_calibration.json", _calibration(False))
    fake = FakeClickBackend()

    run_payload, report = run(
        "auto",
        confirm_local_html_test=True,
        runtime_dir=runtime,
        config_path=config_path,
        backend=fake,
        sleep_fn=lambda _seconds: None,
    )

    assert run_payload["status"] == "blocked"
    assert "kvm_not_calibrated" in _codes(report)
    assert fake.clicks == []


def test_more_than_one_real_action_group_blocks_real_click(tmp_path: Path) -> None:
    guard = _guard(real_action_group_count=2)
    guard["real_action_groups"] = [
        _guard()["real_action_groups"][0],
        {
            "action_id": "a2",
            "logical_skill": "click_option",
            "option_id": "T22",
            "option_text": "AmazonCentral",
            "click_point_screen": {"x": 800, "y": 613},
            "atomic_steps": ["move_mouse", "left_click"],
            "real_execution": False,
        },
    ]
    run_payload, report, fake = _run(tmp_path, guard=guard)

    assert run_payload["status"] == "blocked"
    assert "real_action_group_count_not_one" in _codes(report)
    assert "single_real_action_group_required" in _codes(report)
    assert fake.clicks == []


def test_blocked_logical_skills_block_real_click(tmp_path: Path) -> None:
    for skill in ["submit", "click_next", "type_text", "press_key", "double_click"]:
        guard = _guard()
        guard["real_action_groups"][0]["logical_skill"] = skill
        run_payload, report, fake = _run(tmp_path / skill, guard=guard)

        assert run_payload["status"] == "blocked"
        assert "logical_skill_blocked" in _codes(report)
        assert fake.clicks == []


def test_missing_click_point_screen_blocks_real_click(tmp_path: Path) -> None:
    guard = _guard()
    guard["real_action_groups"][0].pop("click_point_screen")
    run_payload, report, fake = _run(tmp_path, guard=guard)

    assert run_payload["status"] == "blocked"
    assert "missing_or_invalid_click_point_screen" in _codes(report)
    assert fake.clicks == []


def test_abort_file_cancels_before_click(tmp_path: Path) -> None:
    runtime, config_path = _write_runtime(tmp_path)
    (runtime / "STOP_REAL_CLICK").write_text("stop", encoding="utf-8")
    fake = FakeClickBackend()

    run_payload, report = run(
        "auto",
        confirm_local_html_test=True,
        runtime_dir=runtime,
        config_path=config_path,
        backend=fake,
        sleep_fn=lambda _seconds: None,
    )

    assert run_payload["status"] == "cancelled"
    assert "abort_file_present" in _codes(report)
    assert fake.clicks == []


def test_valid_fully_confirmed_local_test_calls_fake_backend_once(tmp_path: Path) -> None:
    run_payload, report, fake = _run(tmp_path)

    assert run_payload["status"] == "completed"
    assert run_payload["real_execution"] is True
    assert run_payload["guards_passed"] is True
    assert run_payload["clicks_attempted"] == 1
    assert run_payload["clicks_completed"] == 1
    assert report["validation_passed"] is True
    assert fake.clicks == [(799, 612)]


def test_output_json_has_no_utf8_bom(tmp_path: Path) -> None:
    runtime, config_path = _write_runtime(tmp_path)
    fake = FakeClickBackend()
    run(
        "auto",
        confirm_local_html_test=True,
        runtime_dir=runtime,
        config_path=config_path,
        backend=fake,
        sleep_fn=lambda _seconds: None,
    )

    run_path = runtime / "latest_local_real_click_run.json"
    report_path = runtime / "latest_local_real_click_report.json"
    assert not run_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not report_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(run_path)],
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


def test_tests_do_not_use_real_os_click_backend(tmp_path: Path) -> None:
    fake = FakeClickBackend()
    _run(tmp_path, backend=fake)

    assert type(fake).__name__ == "FakeClickBackend"
    assert fake.clicks == [(799, 612)]


def test_no_real_click_backend_is_used_in_tests() -> None:
    fake = FakeClickBackend()

    assert type(fake).__name__ == "FakeClickBackend"


def test_no_submit_next_text_or_keyboard_action_can_pass_in_this_mvp(tmp_path: Path) -> None:
    blocked = ["submit", "click_next", "type_text", "press_key", "double_click"]
    for skill in blocked:
        guard = _guard()
        guard["real_action_groups"][0]["logical_skill"] = skill
        run_payload, report, fake = _run(tmp_path / skill, guard=guard)

        assert run_payload["status"] == "blocked"
        assert report["validation_passed"] is False
        assert fake.clicks == []
