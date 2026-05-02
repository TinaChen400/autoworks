from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from modules.vision_parser.parse_store import VALIDATION_REPORT_PATH, write_json
from modules.vision_parser.prompt import get_supported_question_types
from modules.vision_parser.schema import (
    FIELD_TYPES,
    LANGUAGES,
    MEDIA_ROLES,
    MEDIA_TYPES,
    NAV_ACTIONS,
    OPTION_TYPES,
    PAGE_STATUSES,
    PAGE_TYPES,
    QUESTION_TYPES,
    SELECTION_CONTROLS,
    normalize_parsed_page,
)


class ValidationError(ValueError):
    pass


def extract_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Response must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("Response JSON must be an object.")
    return parsed


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must be an object.")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{path} must be a list.")
    return value


def _check_norm_number(value: Any, path: str) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValidationError(f"{path} must be a number.")
    if value < 0 or value > 1:
        raise ValidationError(f"{path} must be between 0 and 1.")


def _check_bbox(value: Any, path: str) -> None:
    bbox = _require_object(value, path)
    for key in ("x", "y", "width", "height"):
        if key not in bbox:
            raise ValidationError(f"{path}.{key} is required.")
        _check_norm_number(bbox[key], f"{path}.{key}")


def _check_point(value: Any, path: str) -> None:
    point = _require_object(value, path)
    for key in ("x", "y"):
        if key not in point:
            raise ValidationError(f"{path}.{key} is required.")
        _check_norm_number(point[key], f"{path}.{key}")


def _check_enum(value: Any, allowed: set[str] | list[str], path: str) -> None:
    if value not in allowed:
        raise ValidationError(f"{path} has unsupported value: {value}")


def validate_parsed_page(
    raw_text: str,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extracted = extract_json(raw_text)
    required_fields = (
        "parse_id",
        "task_id",
        "page",
        "questions",
        "navigation_buttons",
        "uncertainties",
    )
    for field in required_fields:
        if field not in extracted:
            raise ValidationError(f"Missing top-level field: {field}")

    parsed = normalize_parsed_page(
        extracted,
        task_id=str((runtime_context or {}).get("task_id", "")),
    )
    supported = set(get_supported_question_types(runtime_context or {}))
    supported = supported.intersection(QUESTION_TYPES) or QUESTION_TYPES

    page = _require_object(parsed["page"], "page")
    _check_enum(page.get("page_type"), PAGE_TYPES, "page.page_type")
    _check_enum(page.get("language"), LANGUAGES, "page.language")
    _check_enum(page.get("page_status"), PAGE_STATUSES, "page.page_status")
    _check_norm_number(page.get("confidence"), "page.confidence")

    questions = _require_list(parsed["questions"], "questions")
    seen_question_ids: set[str] = set()
    for index, question_value in enumerate(questions):
        qpath = f"questions[{index}]"
        question = _require_object(question_value, qpath)
        question_id = str(question.get("question_id", ""))
        if not question_id:
            raise ValidationError(f"{qpath}.question_id is required.")
        seen_question_ids.add(question_id)
        _check_enum(question.get("question_type"), supported, f"{qpath}.question_type")

        stem = _require_object(question.get("question_stem"), f"{qpath}.question_stem")
        _check_bbox(stem.get("bbox_norm"), f"{qpath}.question_stem.bbox_norm")

        for instruction_index, instruction_value in enumerate(
            _require_list(question.get("instructions", []), f"{qpath}.instructions")
        ):
            instruction = _require_object(
                instruction_value,
                f"{qpath}.instructions[{instruction_index}]",
            )
            _check_bbox(
                instruction.get("bbox_norm"),
                f"{qpath}.instructions[{instruction_index}].bbox_norm",
            )

        for option_index, option_value in enumerate(
            _require_list(question.get("answer_options", []), f"{qpath}.answer_options")
        ):
            option_path = f"{qpath}.answer_options[{option_index}]"
            option = _require_object(option_value, option_path)
            option_id = str(option.get("option_id", ""))
            if not option_id:
                raise ValidationError(f"{option_path}.option_id is required.")
            _check_enum(option.get("option_type"), OPTION_TYPES, f"{option_path}.option_type")
            _check_enum(
                option.get("selection_control"),
                SELECTION_CONTROLS,
                f"{option_path}.selection_control",
            )
            _check_bbox(option.get("bbox_norm"), f"{option_path}.bbox_norm")
            _check_point(option.get("click_point_norm"), f"{option_path}.click_point_norm")
            if str(option.get("action", "")) in NAV_ACTIONS - {"unknown"}:
                raise ValidationError("Navigation buttons must not be mixed into answer_options.")

        for field_index, field_value in enumerate(
            _require_list(question.get("input_fields", []), f"{qpath}.input_fields")
        ):
            field_path = f"{qpath}.input_fields[{field_index}]"
            input_field = _require_object(field_value, field_path)
            _check_enum(input_field.get("field_type"), FIELD_TYPES, f"{field_path}.field_type")
            _check_bbox(input_field.get("bbox_norm"), f"{field_path}.bbox_norm")
            _check_point(input_field.get("click_point_norm"), f"{field_path}.click_point_norm")

        media_items = _require_list(question.get("media", []), f"{qpath}.media")
        ambiguous_media = False
        for media_index, media_value in enumerate(media_items):
            media_path = f"{qpath}.media[{media_index}]"
            media = _require_object(media_value, media_path)
            _check_enum(media.get("media_type"), MEDIA_TYPES, f"{media_path}.media_type")
            _check_enum(media.get("role"), MEDIA_ROLES, f"{media_path}.role")
            _check_bbox(media.get("bbox_norm"), f"{media_path}.bbox_norm")
            if media.get("human_review_required") or media.get("requires_audio_understanding"):
                ambiguous_media = True
        if ambiguous_media and not parsed["uncertainties"]:
            raise ValidationError("Image/audio ambiguity requires at least one uncertainty.")

        _check_norm_number(question.get("confidence"), f"{qpath}.confidence")

    for button_index, button_value in enumerate(
        _require_list(parsed["navigation_buttons"], "navigation_buttons")
    ):
        button_path = f"navigation_buttons[{button_index}]"
        button = _require_object(button_value, button_path)
        _check_enum(button.get("action"), NAV_ACTIONS, f"{button_path}.action")
        _check_bbox(button.get("bbox_norm"), f"{button_path}.bbox_norm")
        _check_point(button.get("click_point_norm"), f"{button_path}.click_point_norm")

    for uncertainty_index, uncertainty_value in enumerate(
        _require_list(parsed["uncertainties"], "uncertainties")
    ):
        uncertainty = _require_object(uncertainty_value, f"uncertainties[{uncertainty_index}]")
        related = str(uncertainty.get("related_question_id", ""))
        if related and related not in seen_question_ids:
            raise ValidationError(
                f"uncertainties[{uncertainty_index}].related_question_id does not match a question."
            )

    return parsed


def validate_file(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8")
    return validate_parsed_page(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a raw vision model response.")
    parser.add_argument("raw_response_path")
    args = parser.parse_args()
    try:
        parsed = validate_file(args.raw_response_path)
    except ValidationError as exc:
        report = {"valid": False, "errors": [str(exc)]}
        write_json(VALIDATION_REPORT_PATH, report)
        print(str(exc))
        raise SystemExit(1) from exc
    write_json(VALIDATION_REPORT_PATH, {"valid": True, "errors": []})
    print(json.dumps(parsed, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
