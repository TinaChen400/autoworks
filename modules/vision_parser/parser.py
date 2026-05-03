from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from modules.vision_parser.doubao_client import (
    VisionModelError,
    call_vision_model,
    load_model_config,
)
from modules.vision_parser.image_payload import prepare_model_input_image
from modules.vision_parser.parse_store import (
    DIAGNOSTICS_PATH,
    MODEL_INPUT_PATH,
    PARSED_PAGE_PATH,
    PROMPT_PATH,
    RAW_RESPONSE_PATH,
    VALIDATION_REPORT_PATH,
    load_runtime_context,
    read_json,
    write_json,
    write_text,
)
from modules.vision_parser.prompt import build_final_prompt
from modules.vision_parser.response_validator import (
    ValidationError,
    validate_parsed_page_with_report,
    validate_scene_scan,
)

SUPPORTED_PARSER_TYPES = {
    "form",
    "survey",
    "image_task",
    "drag_drop",
    "matrix",
    "modal",
    "general",
    "scene_scan",
}


def _load_parse_plan(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Parse plan not found: {source}")
    return read_json(source)


def _resolve_parser_type(
    parser_type: str | None,
    parse_plan: dict[str, Any],
) -> str:
    selected = parser_type or str(parse_plan.get("selected_parser_type") or "general")
    if selected not in SUPPORTED_PARSER_TYPES:
        raise ValueError(f"Unsupported parser_type: {selected}")
    return selected


def _resolve_input_image(
    input_image: str | Path | None,
    parse_plan: dict[str, Any],
) -> str | None:
    if input_image:
        return str(input_image)
    selected_images = parse_plan.get("selected_input_images") or []
    if selected_images:
        return str(selected_images[0])
    return None


def _metadata(
    *,
    parser_type: str,
    input_image: str | None,
    parse_plan: dict[str, Any],
) -> dict[str, Any]:
    metadata = {
        "parser_type_used": parser_type,
        "input_image_used": input_image or "",
        "parse_plan_used": bool(parse_plan),
        "source": "vision_parser",
    }
    selected_region_ids = parse_plan.get("selected_region_ids") or []
    if selected_region_ids:
        metadata["selected_region_id"] = str(selected_region_ids[0])
    return metadata


def _write_diagnostics(
    *,
    parser_type: str,
    mode: str,
    input_image_used: str | None,
    model_input_path: Path,
    prompt: str,
    raw_response: str,
    elapsed_time_ms: int,
    validation_report: dict[str, Any],
) -> None:
    write_json(
        DIAGNOSTICS_PATH,
        {
            "parser_type": parser_type,
            "mode": mode,
            "input_image_used": input_image_used or "",
            "input_image_file_size_bytes": model_input_path.stat().st_size
            if model_input_path.exists()
            else 0,
            "prompt_char_count": len(prompt),
            "raw_response_char_count": len(raw_response),
            "elapsed_time_ms": elapsed_time_ms,
            "validation_passed": bool(validation_report.get("validation_passed")),
            "errors_count": len(validation_report.get("errors", [])),
            "warnings_count": len(validation_report.get("warnings", [])),
        },
    )


def parse_latest_runtime_context(
    mode: str | None = None,
    parser_type: str | None = None,
    input_image: str | Path | None = None,
    from_parse_plan: str | Path | None = None,
) -> dict[str, Any]:
    parse_plan = _load_parse_plan(from_parse_plan)
    selected_parser_type = _resolve_parser_type(parser_type, parse_plan)
    selected_input_image = _resolve_input_image(input_image, parse_plan)
    runtime_context = load_runtime_context()
    screenshot_path = runtime_context.get("screenshot_path")
    if selected_input_image:
        if not Path(selected_input_image).exists():
            raise FileNotFoundError("Selected input image not found.")
        source_image = selected_input_image
        model_input_region = None
    elif not screenshot_path or not Path(screenshot_path).exists():
        raise FileNotFoundError("Please run window_capture Capture first.")
    else:
        source_image = screenshot_path
        model_input_region = runtime_context.get("model_input_region")

    config = load_model_config()
    selected_mode = mode or str(config.get("mode", "fake"))
    if selected_mode not in {"fake", "doubao"}:
        raise VisionModelError(f"Unsupported vision parser mode: {selected_mode}")

    model_input_path = prepare_model_input_image(
        screenshot_path=source_image,
        model_input_region=model_input_region,
        output_path=MODEL_INPUT_PATH,
    )
    final_prompt = build_final_prompt(runtime_context, parser_type=selected_parser_type)
    write_text(PROMPT_PATH, final_prompt)
    started_at = time.perf_counter()
    raw_response = call_vision_model(
        mode=selected_mode,
        prompt=final_prompt,
        image_path=model_input_path,
        task_id=str(runtime_context.get("task_id", "")),
        config=config,
        parser_type=selected_parser_type,
    )
    write_text(RAW_RESPONSE_PATH, raw_response)

    try:
        if selected_parser_type == "scene_scan":
            parsed = validate_scene_scan(raw_response)
            validation_report = {
                "validation_passed": True,
                "errors": [],
                "warnings": [],
                "info": [],
                "normalization_applied": [],
            }
        else:
            parsed, validation_report = validate_parsed_page_with_report(raw_response, runtime_context)
    except ValidationError as exc:
        validation_report = exc.report or {
            "validation_passed": False,
            "errors": [{"code": "validation_error", "path": "$", "message": str(exc)}],
            "warnings": [],
            "info": [],
            "normalization_applied": [],
        }
        write_json(VALIDATION_REPORT_PATH, validation_report)
        _write_diagnostics(
            parser_type=selected_parser_type,
            mode=selected_mode,
            input_image_used=selected_input_image,
            model_input_path=model_input_path,
            prompt=final_prompt,
            raw_response=raw_response,
            elapsed_time_ms=int((time.perf_counter() - started_at) * 1000),
            validation_report=validation_report,
        )
        raise

    parsed["metadata"] = _metadata(
        parser_type=selected_parser_type,
        input_image=selected_input_image,
        parse_plan=parse_plan,
    )
    write_json(PARSED_PAGE_PATH, parsed)
    write_json(VALIDATION_REPORT_PATH, validation_report)
    _write_diagnostics(
        parser_type=selected_parser_type,
        mode=selected_mode,
        input_image_used=selected_input_image,
        model_input_path=model_input_path,
        prompt=final_prompt,
        raw_response=raw_response,
        elapsed_time_ms=int((time.perf_counter() - started_at) * 1000),
        validation_report=validation_report,
    )
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse the latest screenshot with vision_parser.")
    parser.add_argument("--mode", choices=["fake", "doubao"], default=None)
    parser.add_argument("--parser-type", choices=sorted(SUPPORTED_PARSER_TYPES), default=None)
    parser.add_argument("--input-image", default=None)
    parser.add_argument("--from-parse-plan", default=None)
    args = parser.parse_args()
    try:
        parsed = parse_latest_runtime_context(
            mode=args.mode,
            parser_type=args.parser_type,
            input_image=args.input_image,
            from_parse_plan=args.from_parse_plan,
        )
    except (FileNotFoundError, ValidationError, VisionModelError, ValueError) as exc:
        print(str(exc))
        raise SystemExit(1) from exc
    print(f"Saved ParsedPage JSON to {PARSED_PAGE_PATH}")
    print(f"Questions: {len(parsed.get('questions', []))}")


if __name__ == "__main__":
    main()
