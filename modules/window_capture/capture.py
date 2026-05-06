from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import mss
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ANCHOR = {
    "x": 100,
    "y": 80,
    "base_width": 1280,
    "base_height": 720,
    "scale": 1.25,
}
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "anchor_profile.json"
DEFAULT_CAPTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "latest_capture.png"
ALLOWED_SCALES = (1.0, 1.25, 1.5)


class AnchorFrame(TypedDict):
    x: int
    y: int
    width: int
    height: int


class AnchorProfile(TypedDict):
    x: int
    y: int
    base_width: int
    base_height: int
    scale: float


def _nearest_allowed_scale(value: float) -> float:
    return min(ALLOWED_SCALES, key=lambda scale: abs(scale - value))


def resolve_anchor_frame(anchor: AnchorProfile | AnchorFrame) -> AnchorFrame:
    if "base_width" not in anchor:
        return {
            "x": int(anchor["x"]),
            "y": int(anchor["y"]),
            "width": int(anchor["width"]),
            "height": int(anchor["height"]),
        }

    return {
        "x": int(anchor["x"]),
        "y": int(anchor["y"]),
        "width": int(round(anchor["base_width"] * anchor["scale"])),
        "height": int(round(anchor["base_height"] * anchor["scale"])),
    }


def ensure_anchor_profile(path: Path = DEFAULT_CONFIG_PATH) -> AnchorProfile:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_ANCHOR, indent=2) + "\n", encoding="utf-8")
        return DEFAULT_ANCHOR.copy()

    data = json.loads(path.read_text(encoding="utf-8"))
    if "base_width" not in data or "base_height" not in data:
        width = int(data.get("width", DEFAULT_ANCHOR["base_width"]))
        height = int(data.get("height", DEFAULT_ANCHOR["base_height"]))
        inferred_scale = width / DEFAULT_ANCHOR["base_width"]
        data = {
            "x": int(data.get("x", DEFAULT_ANCHOR["x"])),
            "y": int(data.get("y", DEFAULT_ANCHOR["y"])),
            "base_width": DEFAULT_ANCHOR["base_width"],
            "base_height": DEFAULT_ANCHOR["base_height"],
            "scale": _nearest_allowed_scale(
                inferred_scale if width and height else DEFAULT_ANCHOR["scale"]
            ),
        }
        save_anchor_profile(data, path)

    return {
        "x": int(data.get("x", DEFAULT_ANCHOR["x"])),
        "y": int(data.get("y", DEFAULT_ANCHOR["y"])),
        "base_width": int(data.get("base_width", DEFAULT_ANCHOR["base_width"])),
        "base_height": int(data.get("base_height", DEFAULT_ANCHOR["base_height"])),
        "scale": _nearest_allowed_scale(float(data.get("scale", DEFAULT_ANCHOR["scale"]))),
    }


def save_anchor_profile(anchor: AnchorProfile, path: Path = DEFAULT_CONFIG_PATH) -> AnchorProfile:
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = {
        "x": int(anchor["x"]),
        "y": int(anchor["y"]),
        "base_width": int(anchor["base_width"]),
        "base_height": int(anchor["base_height"]),
        "scale": _nearest_allowed_scale(float(anchor["scale"])),
    }
    path.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
    return saved


def initialize_capture_backend() -> None:
    """Initialize mss before window lock state is captured."""
    with mss.mss():
        pass


def capture_anchor_frame(
    anchor: AnchorProfile | AnchorFrame | None = None,
    output_path: Path = DEFAULT_CAPTURE_PATH,
) -> Path:
    frame = resolve_anchor_frame(anchor or ensure_anchor_profile())
    monitor = {
        "left": frame["x"],
        "top": frame["y"],
        "width": frame["width"],
        "height": frame["height"],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        image.save(output_path)

    return output_path
