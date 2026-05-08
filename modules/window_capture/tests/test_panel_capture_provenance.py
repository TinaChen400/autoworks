from __future__ import annotations

from pathlib import Path

from PIL import Image

from modules.window_capture.panel import build_capture_provenance
from modules.window_capture.window_controller import WindowPlacement


def test_build_capture_provenance_uses_current_image_and_locked_region(tmp_path: Path) -> None:
    capture = tmp_path / "latest_capture.png"
    Image.new("RGB", (1600, 900), "white").save(capture)
    locked_region = WindowPlacement(left=100, top=80, width=1600, height=900)

    provenance = build_capture_provenance(
        output_path=capture,
        capture_target={"x": 100, "y": 80, "width": 1600, "height": 900},
        locked_target=locked_region,
        target_window_handle=123,
        target_window_title="Tina",
        dpi_scale=1.25,
    )

    assert provenance["capture_source"] == "locked_target"
    assert provenance["target_locked"] is True
    assert provenance["target_window_handle"] == 123
    assert provenance["target_window_title"] == "Tina"
    assert provenance["locked_region"] == {
        "left": 100,
        "top": 80,
        "width": 1600,
        "height": 900,
    }
    assert provenance["image_width"] == 1600
    assert provenance["image_height"] == 900
    assert provenance["image_hash"]
    assert provenance["screenshot_path"] == str(capture)
