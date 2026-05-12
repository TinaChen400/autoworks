from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from modules.window_capture import target_lock
from modules.window_capture.window_controller import WindowPlacement
from modules.window_capture.window_locator import WindowInfo


class FakeShot:
    size = (1920, 1080)
    rgb = b"\xff\xff\xff" * 1920 * 1080


class FakeMss:
    def __init__(self, calls: list[dict]) -> None:
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def grab(self, monitor: dict) -> FakeShot:
        self.calls.append(monitor)
        return FakeShot()


def test_lock_blocks_when_target_window_does_not_match_anchor_frame(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime_state"
    requested_capture = WindowPlacement(left=100, top=80, width=1920, height=1080)
    actual_window = WindowPlacement(left=100, top=80, width=1440, height=1080)
    window = WindowInfo(
        hwnd=123,
        title="Tina",
        class_name="FlutterMultiWindow",
        process_id=42,
        box=actual_window,
    )
    monkeypatch.setattr(target_lock, "list_visible_windows", lambda exclude_foreground: [window])
    monkeypatch.setattr(
        target_lock,
        "ensure_anchor_profile",
        lambda: {
            "x": 100,
            "y": 80,
            "base_width": 1280,
            "base_height": 720,
            "scale": 1.5,
        },
    )
    monkeypatch.setattr(target_lock, "snap_to_anchor", lambda _hwnd, _anchor: requested_capture)
    monkeypatch.setattr(target_lock, "is_valid_window", lambda _hwnd: True)
    monkeypatch.setattr(target_lock, "get_window_placement", lambda _hwnd: actual_window)
    calls: list[dict] = []
    monkeypatch.setattr(target_lock.mss, "mss", lambda: FakeMss(calls))

    locked = target_lock.lock_target_by_handle(123, runtime)

    assert locked["target_locked"] is False
    assert locked["capture_region"] == {
        "left": 100,
        "top": 80,
        "width": 1920,
        "height": 1080,
    }
    assert locked["locked_region"] == locked["capture_region"]
    assert locked["bbox"] == locked["capture_region"]
    assert locked["target_window_rect"] == {
        "left": 100,
        "top": 80,
        "width": 1440,
        "height": 1080,
    }
    assert "does not match the anchor frame" in locked["blocked_reason"]
    with pytest.raises(RuntimeError, match="No locked target window"):
        target_lock.capture_locked_target(runtime_state_dir=runtime)
    assert calls == []


def test_capture_locked_target_uses_anchor_region_when_window_matches_anchor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime_state"
    requested_capture = WindowPlacement(left=100, top=80, width=1920, height=1080)
    actual_window = WindowPlacement(left=100, top=80, width=1920, height=1080)
    window = WindowInfo(
        hwnd=123,
        title="Tina",
        class_name="FlutterMultiWindow",
        process_id=42,
        box=actual_window,
    )
    monkeypatch.setattr(target_lock, "list_visible_windows", lambda exclude_foreground: [window])
    monkeypatch.setattr(
        target_lock,
        "ensure_anchor_profile",
        lambda: {
            "x": 100,
            "y": 80,
            "base_width": 1280,
            "base_height": 720,
            "scale": 1.5,
        },
    )
    monkeypatch.setattr(target_lock, "snap_to_anchor", lambda _hwnd, _anchor: requested_capture)
    monkeypatch.setattr(target_lock, "is_valid_window", lambda _hwnd: True)
    monkeypatch.setattr(target_lock, "get_window_placement", lambda _hwnd: actual_window)
    calls: list[dict] = []
    monkeypatch.setattr(target_lock.mss, "mss", lambda: FakeMss(calls))

    locked = target_lock.lock_target_by_handle(123, runtime)
    path, provenance = target_lock.capture_locked_target(runtime_state_dir=runtime)

    assert locked["target_locked"] is True
    assert locked["capture_region"] == {
        "left": 100,
        "top": 80,
        "width": 1920,
        "height": 1080,
    }
    assert calls == [{"left": 100, "top": 80, "width": 1920, "height": 1080}]
    assert Image.open(path).size == (1920, 1080)
    assert provenance["capture_region"] == locked["capture_region"]
    assert provenance["target_window_rect"] == locked["target_window_rect"]


def test_validate_locked_target_rejects_different_window_size_at_anchor_origin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime_state"
    runtime.mkdir()
    (runtime / "latest_locked_target.json").write_text(
        json.dumps(
            {
                "target_locked": True,
                "target_window_handle": 123,
                "capture_region": {"left": 100, "top": 80, "width": 1920, "height": 1080},
                "target_window_rect": {"left": 100, "top": 80, "width": 1440, "height": 1080},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(target_lock, "is_valid_window", lambda _hwnd: True)
    monkeypatch.setattr(
        target_lock,
        "get_window_placement",
        lambda _hwnd: WindowPlacement(left=100, top=80, width=1440, height=1080),
    )

    ok, _target, reason = target_lock.validate_locked_target(runtime)

    assert ok is False
    assert "does not match the anchor frame" in reason
