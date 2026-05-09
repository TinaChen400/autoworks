from __future__ import annotations

from pathlib import Path
from typing import Any


def verify_selected_state(
    record: dict[str, Any],
    candidate: dict[str, Any],
    capture_path: str | Path,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ = (record, provenance)
    raw_point = candidate.get("click_point_raw")
    if not isinstance(raw_point, dict):
        return {
            "status": "inconclusive",
            "reason": "candidate_missing_click_point_raw",
        }

    try:
        from PIL import Image
    except ImportError as exc:
        return {
            "status": "inconclusive",
            "reason": f"pillow_unavailable: {exc}",
        }

    try:
        x = int(round(float(raw_point["x"])))
        y = int(round(float(raw_point["y"])))
        image = Image.open(capture_path).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "inconclusive",
            "reason": f"capture_unreadable: {exc}",
        }

    width, height = image.size
    if x < 0 or y < 0 or x >= width or y >= height:
        return {
            "status": "inconclusive",
            "reason": "candidate_click_point_raw_out_of_bounds",
        }

    radius = 9
    saturated = 0
    dark = 0
    total = 0
    for sample_y in range(max(0, y - radius), min(height, y + radius + 1)):
        for sample_x in range(max(0, x - radius), min(width, x + radius + 1)):
            if (sample_x - x) ** 2 + (sample_y - y) ** 2 > radius**2:
                continue
            red, green, blue = image.getpixel((sample_x, sample_y))
            total += 1
            color_range = max(red, green, blue) - min(red, green, blue)
            if color_range >= 45 and max(red, green, blue) >= 80:
                saturated += 1
            if red + green + blue <= 210:
                dark += 1

    if total == 0:
        return {"status": "inconclusive", "reason": "empty_sample_region"}

    saturated_ratio = saturated / total
    dark_ratio = dark / total
    selected = saturated_ratio >= 0.08 or dark_ratio >= 0.18
    return {
        "status": "selected" if selected else "not_selected",
        "reason": "local_control_state_heuristic",
        "metrics": {
            "sample_count": total,
            "saturated_ratio": round(saturated_ratio, 4),
            "dark_ratio": round(dark_ratio, 4),
        },
    }
