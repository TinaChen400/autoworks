from __future__ import annotations

import json
from pathlib import Path

from modules.context_mapper import capture_context


def test_anchor_frame_from_capture_provenance_uses_capture_region_not_window_rect(
    monkeypatch,
    tmp_path: Path,
) -> None:
    screenshot = tmp_path / "latest_capture.png"
    screenshot.write_bytes(b"fake")
    provenance = tmp_path / "latest_capture_provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "screenshot_path": str(screenshot),
                "capture_region": {
                    "left": 100,
                    "top": 80,
                    "width": 1920,
                    "height": 1080,
                },
                "target_window_rect": {
                    "left": 100,
                    "top": 80,
                    "width": 1440,
                    "height": 1080,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(capture_context, "DEFAULT_CAPTURE_PROVENANCE_PATH", provenance)

    assert capture_context.anchor_frame_from_capture_provenance(screenshot) == {
        "x": 100,
        "y": 80,
        "width": 1920,
        "height": 1080,
    }
