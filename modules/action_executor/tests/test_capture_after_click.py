from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from modules.action_executor import capture_after_click
from modules.window_capture.window_controller import WindowPlacement


class FakeShot:
    size = (4, 3)
    rgb = b"\xff\xff\xff" * 12


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


def test_capture_after_click_uses_latest_capture_provenance_without_restore(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime_state"
    runtime.mkdir()
    provenance = {
        "target_locked": True,
        "target_window_title": "Tina",
        "target_window_handle": 123,
        "capture_region": {"left": 100, "top": 80, "width": 4, "height": 3},
        "target_window_rect": {"left": 100, "top": 80, "width": 8, "height": 3},
        "dpi_scale": 1.5,
    }
    (runtime / "latest_capture_provenance.json").write_text(
        json.dumps(provenance),
        encoding="utf-8",
    )
    calls: list[dict] = []
    monkeypatch.setattr(capture_after_click, "is_valid_window", lambda _hwnd: True)
    monkeypatch.setattr(
        capture_after_click,
        "get_window_placement",
        lambda _hwnd: WindowPlacement(left=100, top=80, width=8, height=3),
    )
    monkeypatch.setattr(capture_after_click.mss, "mss", lambda: FakeMss(calls))

    path, after = capture_after_click.capture_after_click(runtime_state_dir=runtime)

    assert calls == [{"left": 100, "top": 80, "width": 4, "height": 3}]
    assert path == runtime / "latest_capture_after_click.png"
    assert after["capture_source"] == "action_executor_after_click"
    assert after["capture_region"] == {"left": 100, "top": 80, "width": 4, "height": 3}
    assert after["target_window_rect"] == {"left": 100, "top": 80, "width": 8, "height": 3}
    assert after["image_width"] == 4
    assert after["image_height"] == 3
    assert Image.open(path).size == (4, 3)


def test_capture_after_click_fails_if_locked_target_moved(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    runtime.mkdir()
    (runtime / "latest_capture_provenance.json").write_text(
        json.dumps(
            {
                "target_window_handle": 123,
                "capture_region": {"left": 100, "top": 80, "width": 4, "height": 3},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(capture_after_click, "is_valid_window", lambda _hwnd: True)
    monkeypatch.setattr(
        capture_after_click,
        "get_window_placement",
        lambda _hwnd: WindowPlacement(left=110, top=80, width=5, height=3),
    )

    try:
        capture_after_click.capture_after_click(runtime_state_dir=runtime)
    except RuntimeError as exc:
        assert "moved or resized" in str(exc)
    else:
        raise AssertionError("capture_after_click should fail when the locked target moved")


def test_capture_after_click_accepts_dpi_scaled_window_origin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime_state"
    runtime.mkdir()
    (runtime / "latest_capture_provenance.json").write_text(
        json.dumps(
            {
                "target_window_handle": 123,
                "capture_region": {"left": 100, "top": 80, "width": 4, "height": 3},
                "dpi_scale": 1.5,
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []
    monkeypatch.setattr(capture_after_click, "is_valid_window", lambda _hwnd: True)
    monkeypatch.setattr(
        capture_after_click,
        "get_window_placement",
        lambda _hwnd: WindowPlacement(left=150, top=120, width=2160, height=1620),
    )
    monkeypatch.setattr(capture_after_click.mss, "mss", lambda: FakeMss(calls))

    capture_after_click.capture_after_click(runtime_state_dir=runtime)

    assert calls == [{"left": 100, "top": 80, "width": 4, "height": 3}]
