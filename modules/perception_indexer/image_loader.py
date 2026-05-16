from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from modules.perception_indexer.schema import BBox, clamp_bbox

RUNTIME_CONTEXT_PATH = Path("runtime_state/latest_runtime_context.json")
RUNTIME_CAPTURE_PATH = Path("runtime_state/latest_capture.png")
CAPTURE_PROVENANCE_PATH = Path("runtime_state/latest_capture_provenance.json")


def load_runtime_context(path: str | Path = RUNTIME_CONTEXT_PATH) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError("Please run context_mapper first.")
    with source.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_screenshot(runtime_context: dict[str, Any]) -> tuple[Image.Image, Path]:
    screenshot_path = Path(str(runtime_context.get("screenshot_path", "")))
    if not screenshot_path.exists():
        raise FileNotFoundError("Please run window_capture Capture first.")
    validate_runtime_capture_source(screenshot_path)
    return Image.open(screenshot_path).convert("RGB"), screenshot_path


def validate_runtime_capture_source(screenshot_path: Path) -> None:
    if not RUNTIME_CAPTURE_PATH.exists():
        return
    if screenshot_path.resolve(strict=False) != RUNTIME_CAPTURE_PATH.resolve(strict=False):
        raise ValueError(
            "latest_runtime_context.json does not reference runtime_state/latest_capture.png"
        )

    if not CAPTURE_PROVENANCE_PATH.exists():
        return
    try:
        provenance = json.loads(CAPTURE_PROVENANCE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("latest_capture_provenance.json is unreadable") from exc

    referenced = Path(
        str(provenance.get("screenshot_path") or provenance.get("capture_path") or "")
    )
    if referenced.resolve(strict=False) != screenshot_path.resolve(strict=False):
        raise ValueError(
            "latest_capture_provenance.json does not match latest_runtime_context.json"
        )


def get_model_input_region(runtime_context: dict[str, Any], image: Image.Image) -> BBox:
    raw = runtime_context.get("model_input_region") or {}
    if not raw:
        return BBox(x=0, y=0, width=image.width, height=image.height)
    return clamp_bbox(
        BBox(
            x=int(raw.get("x", 0)),
            y=int(raw.get("y", 0)),
            width=int(raw.get("width", image.width)),
            height=int(raw.get("height", image.height)),
        ),
        image.width,
        image.height,
    )
