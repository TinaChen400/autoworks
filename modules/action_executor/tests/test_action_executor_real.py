from __future__ import annotations

import json
from pathlib import Path

from modules.action_executor.action_executor import run


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class FakeMouse:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []
        self.typed: list[str] = []

    def click_screen_point(self, x: int, y: int, pause_ms: int = 120) -> dict[str, int]:
        self.calls.append((x, y, pause_ms))
        return {"x": x, "y": y}

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def drag_screen_points(self, start_point: dict, end_point: dict, pause_ms: int = 120) -> dict:
        self.calls.append((start_point["x"], start_point["y"], pause_ms))
        self.calls.append((end_point["x"], end_point["y"], pause_ms))
        return {"start_position": start_point, "end_position": end_point}

    def scroll(self, amount: int, x: int | None = None, y: int | None = None) -> dict:
        self.calls.append((x or 0, amount, 0))
        return {"x": x or 0, "y": y or 0}


class FakeCapture:
    def __init__(self, runtime: Path) -> None:
        self.runtime = runtime
        self.calls = 0

    def capture_locked_target(self, runtime_state_dir: Path) -> tuple[Path, dict]:
        self.calls += 1
        path = runtime_state_dir / f"capture_{self.calls}.png"
        path.write_bytes(b"fake")
        return path, {"capture_index": self.calls}


class FakeAfterClickCapture:
    def __init__(self, runtime: Path) -> None:
        self.runtime = runtime
        self.calls = 0

    def capture_after_click(self, runtime_state_dir: Path) -> tuple[Path, dict]:
        self.calls += 1
        path = runtime_state_dir / f"after_click_{self.calls}.png"
        path.write_bytes(b"fake")
        return path, {"capture_index": self.calls, "capture_source": "after_click"}


def _action(
    skill: str = "click_option",
    include_click_point: bool = True,
    requires_review: bool = False,
) -> dict:
    target = {
        "question_id": "q1",
        "option_id": "o1",
        "option_text": "Retail Central",
    }
    if include_click_point:
        target["click_point_screen"] = {"x": 160, "y": 270}
        target["click_point_raw"] = {"x": 60, "y": 70}
        target["click_candidates"] = [
            {
                "source": "primary",
                "is_primary": True,
                "click_point_screen": {"x": 160, "y": 270},
                "click_point_raw": {"x": 60, "y": 70},
            },
            {
                "source": "fallback",
                "click_point_screen": {"x": 170, "y": 280},
                "click_point_raw": {"x": 70, "y": 80},
            },
        ]
    return {
        "action_id": "a1",
        "skill": skill,
        "target": target,
        "params": {},
        "requires_review": requires_review,
    }


def _navigation_action() -> dict:
    return {
        "action_id": "a2",
        "skill": "click_navigation",
        "target": {
            "button_id": "nav_next",
            "action": "next_page",
            "text": "Next",
            "click_point_screen": {"x": 260, "y": 290},
        },
        "params": {},
        "requires_review": False,
    }


def _text_action() -> dict:
    action = _action(skill="type_text")
    action["params"] = {"text": "Helpful setup guidance."}
    return action


def _drag_action() -> dict:
    return {
        "action_id": "a3",
        "skill": "drag",
        "target": {
            "start_point_screen": {"x": 100, "y": 120},
            "end_point_screen": {"x": 300, "y": 320},
        },
        "params": {},
        "requires_review": False,
    }


def _scroll_action() -> dict:
    return {
        "action_id": "a4",
        "skill": "scroll",
        "target": {"click_point_screen": {"x": 400, "y": 500}},
        "params": {"direction": "down", "amount": 4},
        "requires_review": False,
    }


def _gate(allowed: bool = True, actions: list[dict] | None = None) -> dict:
    return {
        "execution_gate_id": "execution_gate_1",
        "task_id": "task1",
        "session_id": "session_1",
        "source_resolved_action_plan_id": "resolved_action_plan_1",
        "execution_allowed": allowed,
        "status": "allowed" if allowed else "blocked",
        "block_reasons": [] if allowed else [{"code": "human_review_required"}],
        "executable_actions": actions if actions is not None else [_action()],
    }


def test_dry_run_does_not_call_real_mouse_api(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    fake_mouse = FakeMouse()

    run_payload, report = run("auto", dry_run=True, runtime_dir=runtime, mouse_api=fake_mouse)

    assert fake_mouse.calls == []
    assert report["validation_passed"] is True
    assert report["real_execution"] is False
    assert report["execution_attempted"] is True
    assert report["executed_action_count"] == 1
    assert report["action_records"][0]["status"] == "would_click"
    assert run_payload["dry_run"] is True


def test_click_navigation_executes_without_selection_verification(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True, [_navigation_action()]))
    fake_mouse = FakeMouse()
    fake_capture = FakeAfterClickCapture(runtime)

    _run_payload, report = run(
        "auto",
        runtime_dir=runtime,
        mouse_api=fake_mouse,
        capture_api=fake_capture,
    )

    assert fake_mouse.calls == [(260, 290, 120)]
    assert fake_capture.calls == 0
    assert report["validation_passed"] is True
    assert report["executed_action_count"] == 1
    assert report["action_records"][0]["skill"] == "click_navigation"
    assert report["action_records"][0]["status"] == "clicked"


def test_gate_not_allowed_blocks_execution(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(False, []))
    fake_mouse = FakeMouse()

    _run_payload, report = run("auto", runtime_dir=runtime, mouse_api=fake_mouse)

    assert fake_mouse.calls == []
    assert report["validation_passed"] is False
    assert report["execution_attempted"] is False
    assert report["errors"][0]["code"] == "gate_not_allowed"


def test_gate_missing_blocks_execution_and_writes_report(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    fake_mouse = FakeMouse()

    _run_payload, report = run("auto", runtime_dir=runtime, mouse_api=fake_mouse)

    assert fake_mouse.calls == []
    assert report["validation_passed"] is False
    assert report["execution_attempted"] is False
    assert report["errors"][0]["code"] == "gate_missing"
    assert (runtime / "latest_action_executor_report.json").exists()


def test_missing_click_point_screen_blocks_execution(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(
        runtime / "latest_execution_gate.json",
        _gate(True, [_action(include_click_point=False)]),
    )
    fake_mouse = FakeMouse()

    _run_payload, report = run("auto", runtime_dir=runtime, mouse_api=fake_mouse)

    assert fake_mouse.calls == []
    assert report["validation_passed"] is False
    assert report["execution_attempted"] is False
    assert report["errors"][0]["code"] == "missing_click_point_screen"


def test_allowed_click_option_creates_executable_records(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    fake_mouse = FakeMouse()

    _run_payload, report = run(
        "auto",
        runtime_dir=runtime,
        mouse_api=fake_mouse,
        pause_ms=5,
        verify_click=False,
    )

    assert fake_mouse.calls == [(160, 270, 5)]
    assert report["validation_passed"] is True
    assert report["real_execution"] is True
    assert report["execution_attempted"] is True
    assert report["executed_action_count"] == 1
    assert report["action_records"][0]["click_point_screen"] == {"x": 160, "y": 270}
    assert report["action_records"][0]["actual_cursor_position"] == {"x": 160, "y": 270}
    assert report["action_records"][0]["status"] == "clicked"
    assert (runtime / "latest_action_executor_run.json").exists()
    assert (runtime / "latest_action_executor_report.json").exists()


def test_type_text_clicks_field_and_types_text(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True, [_text_action()]))
    fake_mouse = FakeMouse()

    _run_payload, report = run(
        "auto",
        runtime_dir=runtime,
        mouse_api=fake_mouse,
        pause_ms=5,
        verify_click=False,
    )

    assert fake_mouse.calls == [(160, 270, 5)]
    assert fake_mouse.typed == ["Helpful setup guidance."]
    assert report["validation_passed"] is True
    assert report["executed_action_count"] == 1
    assert report["action_records"][0]["status"] == "typed"


def test_drag_executes_start_to_end_points(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True, [_drag_action()]))
    fake_mouse = FakeMouse()

    _run_payload, report = run("auto", runtime_dir=runtime, mouse_api=fake_mouse, pause_ms=5)

    assert fake_mouse.calls == [(100, 120, 5), (300, 320, 5)]
    assert report["validation_passed"] is True
    assert report["action_records"][0]["status"] == "dragged"


def test_scroll_executes_and_counts_as_action(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True, [_scroll_action()]))
    fake_mouse = FakeMouse()

    _run_payload, report = run("auto", runtime_dir=runtime, mouse_api=fake_mouse)

    assert fake_mouse.calls == [(400, -4, 0)]
    assert report["validation_passed"] is True
    assert report["executed_action_count"] == 1
    assert report["action_records"][0]["status"] == "scrolled"


def test_verified_click_stops_after_selected_candidate(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    fake_mouse = FakeMouse()
    fake_capture = FakeCapture(runtime)

    def verifier(_record: dict, _candidate: dict, _capture_path: Path, _provenance: dict) -> dict:
        return {"status": "selected", "reason": "test"}

    _run_payload, report = run(
        "auto",
        runtime_dir=runtime,
        mouse_api=fake_mouse,
        capture_api=fake_capture,
        verifier_api=verifier,
        pause_ms=5,
        post_click_pause_ms=0,
    )

    record = report["action_records"][0]
    assert fake_mouse.calls == [(160, 270, 5)]
    assert fake_capture.calls == 1
    assert report["validation_passed"] is True
    assert report["executed_action_count"] == 1
    assert record["status"] == "clicked_verified"
    assert record["verified_candidate_index"] == 0


def test_verified_click_accepts_after_click_capture_api(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    fake_mouse = FakeMouse()
    fake_capture = FakeAfterClickCapture(runtime)

    def verifier(_record: dict, _candidate: dict, _capture_path: Path, _provenance: dict) -> dict:
        return {"status": "selected", "reason": "test"}

    _run_payload, report = run(
        "auto",
        runtime_dir=runtime,
        mouse_api=fake_mouse,
        capture_api=fake_capture,
        verifier_api=verifier,
        post_click_pause_ms=0,
    )

    assert fake_capture.calls == 1
    assert report["validation_passed"] is True
    assert report["action_records"][0]["status"] == "clicked_verified"


def test_click_verification_retries_next_candidate(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    fake_mouse = FakeMouse()
    fake_capture = FakeCapture(runtime)
    statuses = iter(["not_selected", "selected"])

    def verifier(_record: dict, _candidate: dict, _capture_path: Path, _provenance: dict) -> dict:
        return {"status": next(statuses), "reason": "test"}

    _run_payload, report = run(
        "auto",
        runtime_dir=runtime,
        mouse_api=fake_mouse,
        capture_api=fake_capture,
        verifier_api=verifier,
        pause_ms=5,
        post_click_pause_ms=0,
    )

    record = report["action_records"][0]
    assert fake_mouse.calls == [(160, 270, 5), (170, 280, 5)]
    assert fake_capture.calls == 2
    assert report["validation_passed"] is True
    assert record["status"] == "clicked_verified"
    assert record["verified_candidate_index"] == 1
    assert [attempt["status"] for attempt in record["click_attempts"]] == [
        "not_selected",
        "clicked_verified",
    ]


def test_inconclusive_click_verification_stops_safely(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True))
    fake_mouse = FakeMouse()
    fake_capture = FakeCapture(runtime)

    def verifier(_record: dict, _candidate: dict, _capture_path: Path, _provenance: dict) -> dict:
        return {"status": "inconclusive", "reason": "ambiguous"}

    _run_payload, report = run(
        "auto",
        runtime_dir=runtime,
        mouse_api=fake_mouse,
        capture_api=fake_capture,
        verifier_api=verifier,
        post_click_pause_ms=0,
    )

    assert fake_mouse.calls == [(160, 270, 120)]
    assert report["validation_passed"] is False
    assert report["executed_action_count"] == 0
    assert report["action_records"][0]["status"] == "verification_blocked"
    assert report["errors"][0]["code"] == "click_verification_inconclusive"


def test_unsupported_skill_blocks_execution(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_execution_gate.json", _gate(True, [_action(skill="select_dropdown")]))
    fake_mouse = FakeMouse()

    _run_payload, report = run("auto", runtime_dir=runtime, mouse_api=fake_mouse)

    assert fake_mouse.calls == []
    assert report["validation_passed"] is False
    assert report["execution_attempted"] is False
    assert report["errors"][0]["code"] == "unsupported_skill"
