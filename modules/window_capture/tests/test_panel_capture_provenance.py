from __future__ import annotations

from pathlib import Path

from PIL import Image

from modules.window_capture.panel import build_capture_provenance
from modules.window_capture.window_controller import WindowPlacement


def test_build_capture_provenance_uses_capture_region_as_coordinate_frame(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "latest_capture.png"
    Image.new("RGB", (1920, 1080), "white").save(capture)
    target_window_rect = WindowPlacement(left=100, top=80, width=1440, height=1080)

    provenance = build_capture_provenance(
        output_path=capture,
        capture_target={"x": 100, "y": 80, "width": 1920, "height": 1080},
        locked_target=target_window_rect,
        target_window_handle=123,
        target_window_title="Tina",
        dpi_scale=1.5,
    )

    assert provenance["capture_source"] == "locked_target"
    assert provenance["target_locked"] is True
    assert provenance["target_window_handle"] == 123
    assert provenance["target_window_title"] == "Tina"
    assert provenance["locked_region"] == {
        "left": 100,
        "top": 80,
        "width": 1920,
        "height": 1080,
    }
    assert provenance["capture_region"] == provenance["locked_region"]
    assert provenance["bbox"] == provenance["locked_region"]
    assert provenance["target_window_rect"] == {
        "left": 100,
        "top": 80,
        "width": 1440,
        "height": 1080,
    }
    assert provenance["image_width"] == 1920
    assert provenance["image_height"] == 1080
    assert provenance["image_hash"]
    assert provenance["screenshot_path"] == str(capture)
