from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from modules.vision_parser.doubao_client import (
    VisionModelError,
    call_vision_model,
    load_model_config,
)
from modules.vision_parser.image_payload import prepare_model_input_image
from modules.vision_parser.parse_store import (
    MODEL_INPUT_PATH,
    PARSED_PAGE_PATH,
    RAW_RESPONSE_PATH,
    VALIDATION_REPORT_PATH,
    load_runtime_context,
    write_json,
    write_text,
)
from modules.vision_parser.prompt import build_final_prompt
from modules.vision_parser.response_validator import ValidationError, validate_parsed_page


def parse_latest_runtime_context(mode: str | None = None) -> dict[str, Any]:
    runtime_context = load_runtime_context()
    screenshot_path = runtime_context.get("screenshot_path")
    if not screenshot_path or not Path(screenshot_path).exists():
        raise FileNotFoundError("Please run window_capture Capture first.")

    config = load_model_config()
    selected_mode = mode or str(config.get("mode", "fake"))
    if selected_mode not in {"fake", "doubao"}:
        raise VisionModelError(f"Unsupported vision parser mode: {selected_mode}")

    model_input_path = prepare_model_input_image(
        screenshot_path=screenshot_path,
        model_input_region=runtime_context.get("model_input_region"),
        output_path=MODEL_INPUT_PATH,
    )
    final_prompt = build_final_prompt(runtime_context)
    raw_response = call_vision_model(
        mode=selected_mode,
        prompt=final_prompt,
        image_path=model_input_path,
        task_id=str(runtime_context.get("task_id", "")),
        config=config,
    )
    write_text(RAW_RESPONSE_PATH, raw_response)

    try:
        parsed = validate_parsed_page(raw_response, runtime_context)
    except ValidationError as exc:
        write_json(VALIDATION_REPORT_PATH, {"valid": False, "errors": [str(exc)]})
        raise

    write_json(PARSED_PAGE_PATH, parsed)
    write_json(VALIDATION_REPORT_PATH, {"valid": True, "errors": []})
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse the latest screenshot with vision_parser.")
    parser.add_argument("--mode", choices=["fake", "doubao"], default=None)
    args = parser.parse_args()
    try:
        parsed = parse_latest_runtime_context(mode=args.mode)
    except (FileNotFoundError, ValidationError, VisionModelError, ValueError) as exc:
        print(str(exc))
        raise SystemExit(1) from exc
    print(f"Saved ParsedPage JSON to {PARSED_PAGE_PATH}")
    print(f"Questions: {len(parsed.get('questions', []))}")


if __name__ == "__main__":
    main()
