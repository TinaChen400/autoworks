from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

DEFAULT_MODEL_INPUT_PATH = Path("runtime_state/latest_model_input.png")


def _region_box(
    region: dict[str, Any],
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    x = max(0, int(region.get("x", 0)))
    y = max(0, int(region.get("y", 0)))
    width = int(region.get("width", image_width))
    height = int(region.get("height", image_height))
    right = min(image_width, x + max(1, width))
    bottom = min(image_height, y + max(1, height))
    if right <= x or bottom <= y:
        raise ValueError("model_input_region does not overlap the screenshot")
    return x, y, right, bottom


def prepare_model_input_image(
    screenshot_path: str | Path,
    model_input_region: dict[str, Any] | None,
    output_path: str | Path = DEFAULT_MODEL_INPUT_PATH,
) -> Path:
    source = Path(screenshot_path)
    if not source.exists():
        raise FileNotFoundError("Please run window_capture Capture first.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as image:
        converted = image.convert("RGB")
        if model_input_region:
            crop_box = _region_box(model_input_region, converted.width, converted.height)
            converted = converted.crop(crop_box)
        converted.save(output, format="PNG")

    return output


def image_to_data_url(image_path: str | Path) -> str:
    path = Path(image_path)
    with Image.open(path) as image:
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
