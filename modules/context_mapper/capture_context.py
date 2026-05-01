from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from modules.context_mapper.prompt_builder import build_prompt_bundle
from modules.context_mapper.schema import AnchorFrame, BoundingBox, ImageSize, RuntimeContext
from modules.context_mapper.task_context_loader import load_effective_task_context
from modules.window_capture.capture import (
    DEFAULT_ANCHOR,
    DEFAULT_CAPTURE_PATH,
    DEFAULT_CONFIG_PATH,
    PROJECT_ROOT,
    ensure_anchor_profile,
    resolve_anchor_frame,
)

DEFAULT_RUNTIME_STATE_DIR = PROJECT_ROOT / "runtime_state"
DEFAULT_RUNTIME_CONTEXT_PATH = DEFAULT_RUNTIME_STATE_DIR / "latest_runtime_context.json"


def build_runtime_context(
    task_id: str,
    screenshot_path: Path = DEFAULT_CAPTURE_PATH,
    output_path: Path = DEFAULT_RUNTIME_CONTEXT_PATH,
) -> dict[str, Any]:
    task_context = load_effective_task_context(task_id)
    anchor_profile = ensure_anchor_profile(DEFAULT_CONFIG_PATH)
    anchor_data = resolve_anchor_frame(anchor_profile)
    anchor = AnchorFrame(**anchor_data)
    anchor.validate()

    image_size = read_image_size_or_anchor(screenshot_path, anchor)
    raw_screenshot = BoundingBox(0, 0, image_size.width, image_size.height)
    content_region, ignore_regions, model_input_region = build_regions(task_context, image_size)
    prompts = build_prompt_bundle(task_context)

    runtime_context = RuntimeContext(
        task_id=task_id,
        task_type=str(task_context.get("task_type", "")),
        screenshot_path=str(screenshot_path),
        anchor_frame=anchor,
        image_size=image_size,
        raw_screenshot=raw_screenshot,
        content_region=content_region,
        ignore_regions=ignore_regions,
        model_input_region=model_input_region,
        effective_task_context=task_context,
        vision_prompt=prompts["vision_prompt"],
        answer_prompt=prompts["answer_prompt"],
        coordinate_policy={
            "model_norm": "normalized 0-1 coordinates relative to ModelInputRegion",
            "model_region_pixel": "pixel coordinates inside ModelInputRegion",
            "raw_screenshot_pixel": "pixel coordinates inside RawScreenshot",
            "screen_pixel": "absolute screen coordinate on Computer A",
            "formula": (
                "raw_x = model_input_region.x + norm_x * model_input_region.width; "
                "raw_y = model_input_region.y + norm_y * model_input_region.height; "
                "screen_x = anchor_frame.x + raw_x; screen_y = anchor_frame.y + raw_y"
            ),
        },
        supported_question_types=task_context.get("supported_question_types", []),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = runtime_context.to_json_dict()
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def read_image_size_or_anchor(screenshot_path: Path, anchor: AnchorFrame) -> ImageSize:
    if screenshot_path.exists():
        with Image.open(screenshot_path) as image:
            size = ImageSize(width=int(image.width), height=int(image.height))
            size.validate()
            return size
    if DEFAULT_ANCHOR:
        size = ImageSize(width=anchor.width, height=anchor.height)
        size.validate()
        return size
    raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")


def build_regions(
    task_context: dict[str, Any],
    image_size: ImageSize,
) -> tuple[BoundingBox, list[BoundingBox], BoundingBox]:
    crop = task_context.get("crop_margins", {})
    left = int(crop.get("left", 0))
    top = int(crop.get("top", 0))
    right = int(crop.get("right", 0))
    bottom = int(crop.get("bottom", 0))
    if min(left, top, right, bottom) < 0:
        raise ValueError("crop margins must be zero or positive")
    width = image_size.width - left - right
    height = image_size.height - top - bottom
    if width <= 0 or height <= 0:
        raise ValueError("crop margins leave no model input region")

    model_input_region = BoundingBox(left, top, width, height)
    content_region = model_input_region
    ignore_regions = []
    if top:
        ignore_regions.append(BoundingBox(0, 0, image_size.width, top))
    if bottom:
        ignore_regions.append(BoundingBox(0, image_size.height - bottom, image_size.width, bottom))
    if left:
        ignore_regions.append(BoundingBox(0, top, left, height))
    if right:
        ignore_regions.append(BoundingBox(image_size.width - right, top, right, height))
    return content_region, ignore_regions, model_input_region


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate runtime context for a task.")
    parser.add_argument("--task", required=True, help="Task id, for example tts01")
    parser.add_argument("--screenshot", default=str(DEFAULT_CAPTURE_PATH))
    parser.add_argument("--output", default=str(DEFAULT_RUNTIME_CONTEXT_PATH))
    args = parser.parse_args()
    data = build_runtime_context(args.task, Path(args.screenshot), Path(args.output))
    print(f"generated: {args.output}")
    print(f"task_id: {data['task_id']}")
    print(f"task_type: {data['task_type']}")
    print(f"image_size: {data['image_size']}")
    print(f"model_input_region: {data['model_input_region']}")


if __name__ == "__main__":
    main()
