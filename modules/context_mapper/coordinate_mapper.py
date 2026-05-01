from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from modules.context_mapper.schema import AnchorFrame, BoundingBox, ImageSize
from modules.window_capture.capture import PROJECT_ROOT

DEFAULT_RUNTIME_CONTEXT_PATH = PROJECT_ROOT / "runtime_state" / "latest_runtime_context.json"


def norm_to_image_pixel(
    norm_x: float,
    norm_y: float,
    image_width: int,
    image_height: int,
) -> tuple[int, int]:
    _validate_norm(norm_x, norm_y)
    ImageSize(image_width, image_height).validate()
    return (round(norm_x * image_width), round(norm_y * image_height))


def image_pixel_to_norm(
    px: float,
    py: float,
    image_width: int,
    image_height: int,
) -> tuple[float, float]:
    ImageSize(image_width, image_height).validate()
    return (px / image_width, py / image_height)


def image_pixel_to_screen(
    px: float,
    py: float,
    anchor_frame: dict[str, Any] | AnchorFrame,
) -> tuple[int, int]:
    anchor = _coerce_anchor(anchor_frame)
    anchor.validate()
    return (round(anchor.x + px), round(anchor.y + py))


def model_norm_to_raw_screenshot_pixel(
    norm_x: float,
    norm_y: float,
    model_input_region: dict[str, Any] | BoundingBox,
) -> tuple[int, int]:
    _validate_norm(norm_x, norm_y)
    region = _coerce_box(model_input_region)
    region.validate_positive("model_input_region")
    raw_x = region.x + norm_x * region.width
    raw_y = region.y + norm_y * region.height
    return (round(raw_x), round(raw_y))


def norm_to_screen(
    norm_x: float,
    norm_y: float,
    runtime_context: dict[str, Any],
) -> tuple[int, int]:
    raw_px = model_norm_to_raw_screenshot_pixel(
        norm_x,
        norm_y,
        runtime_context["model_input_region"],
    )
    return image_pixel_to_screen(raw_px[0], raw_px[1], runtime_context["anchor_frame"])


def map_model_norm(
    norm_x: float,
    norm_y: float,
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    raw_px = model_norm_to_raw_screenshot_pixel(
        norm_x,
        norm_y,
        runtime_context["model_input_region"],
    )
    screen_px = image_pixel_to_screen(raw_px[0], raw_px[1], runtime_context["anchor_frame"])
    return {
        "task_id": runtime_context.get("task_id"),
        "norm_coordinate": {"x": norm_x, "y": norm_y},
        "model_region_pixel": {
            "x": round(norm_x * runtime_context["model_input_region"]["width"]),
            "y": round(norm_y * runtime_context["model_input_region"]["height"]),
        },
        "raw_screenshot_pixel": {"x": raw_px[0], "y": raw_px[1]},
        "image_pixel_coordinate": {"x": raw_px[0], "y": raw_px[1]},
        "screen_pixel_coordinate": {"x": screen_px[0], "y": screen_px[1]},
    }


def load_runtime_context(path: Path = DEFAULT_RUNTIME_CONTEXT_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Runtime context not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_norm(norm_x: float, norm_y: float) -> None:
    if not 0 <= norm_x <= 1 or not 0 <= norm_y <= 1:
        raise ValueError("norm_x and norm_y must be between 0 and 1")


def _coerce_anchor(anchor: dict[str, Any] | AnchorFrame) -> AnchorFrame:
    if isinstance(anchor, AnchorFrame):
        return anchor
    return AnchorFrame(
        x=int(anchor["x"]),
        y=int(anchor["y"]),
        width=int(anchor["width"]),
        height=int(anchor["height"]),
    )


def _coerce_box(box: dict[str, Any] | BoundingBox) -> BoundingBox:
    if isinstance(box, BoundingBox):
        return box
    return BoundingBox(
        x=float(box["x"]),
        y=float(box["y"]),
        width=float(box["width"]),
        height=float(box["height"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Map model-normalized coordinates to pixels.")
    parser.add_argument("--x", required=True, type=float, help="Normalized x coordinate")
    parser.add_argument("--y", required=True, type=float, help="Normalized y coordinate")
    parser.add_argument(
        "--runtime-context",
        default=str(DEFAULT_RUNTIME_CONTEXT_PATH),
        help="Runtime context JSON path",
    )
    args = parser.parse_args()
    runtime_context = load_runtime_context(Path(args.runtime_context))
    mapped = map_model_norm(args.x, args.y, runtime_context)
    print(f"task_id: {runtime_context.get('task_id')}")
    print(f"AnchorFrame: {runtime_context.get('anchor_frame')}")
    print(f"image size: {runtime_context.get('image_size')}")
    print(f"norm coordinate: {mapped['norm_coordinate']}")
    print(f"model region pixel: {mapped['model_region_pixel']}")
    print(f"image pixel coordinate: {mapped['image_pixel_coordinate']}")
    print(f"screen pixel coordinate: {mapped['screen_pixel_coordinate']}")


if __name__ == "__main__":
    main()
