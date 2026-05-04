from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from modules.vision_parser.parse_store import VALIDATION_REPORT_PATH, write_json
from modules.vision_parser.prompt import get_supported_question_types
from modules.vision_parser.schema import (
    ELEMENT_ROLES,
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

SCENE_SCAN_REQUIRED_FIELDS = (
    "detected_page_type",
    "layout_type",
    "detected_interaction_types",
    "recommended_parser",
    "confidence",
    "reason",
)


class ValidationError(ValueError):
    def __init__(self, message: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report


def empty_validation_report() -> dict[str, Any]:
    return {
        "validation_passed": True,
        "errors": [],
        "warnings": [],
        "info": [],
        "normalization_applied": [],
    }


def _message(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _add(
    report: dict[str, Any],
    severity: str,
    code: str,
    path: str,
    message: str,
) -> None:
    report[severity].append(_message(code, path, message))
    if severity in {"warnings", "info"}:
        report["normalization_applied"].append(
            {"code": code, "path": path, "message": message}
        )


def _report_error(report: dict[str, Any], code: str, path: str, message: str) -> None:
    report["validation_passed"] = False
    report["errors"].append(_message(code, path, message))


def report_to_text(report: dict[str, Any]) -> str:
    if report.get("errors"):
        first = report["errors"][0]
        return f"{first.get('path', '$')}: {first.get('message', first.get('code', 'invalid'))}"
    return "Validation failed."


def _raise_report(report: dict[str, Any]) -> None:
    raise ValidationError(report_to_text(report), report)


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


def _is_missing(value: Any) -> bool:
    return value is None or value == ""


def _normalize_enum(
    container: dict[str, Any],
    key: str,
    allowed: set[str],
    path: str,
    report: dict[str, Any],
    *,
    raw_key: str | None = None,
) -> str:
    value = container.get(key)
    if _is_missing(value):
        container[key] = "unknown"
        _add(report, "warnings", "missing_optional_enum", path, f"{path} was missing; set to unknown.")
        return "unknown"
    text = str(value)
    if text not in allowed:
        if raw_key:
            container.setdefault(raw_key, text)
        container[key] = "unknown"
        _add(
            report,
            "warnings",
            "normalized_unknown_enum",
            path,
            f"{path} had unsupported value {text!r}; set to unknown.",
        )
        return "unknown"
    container[key] = text
    return text


def _clamp_number(value: Any, path: str, report: dict[str, Any]) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        _report_error(report, "invalid_coordinate", path, f"{path} must be a number.")
        return None
    number = float(value)
    if 0.0 <= number <= 1.0:
        return number
    if -0.05 <= number <= 1.05:
        clamped = min(1.0, max(0.0, number))
        _add(
            report,
            "warnings",
            "clamped_bbox_value",
            path,
            f"{path} was {number}; clamped to {clamped}.",
        )
        return clamped
    _report_error(report, "invalid_coordinate", path, f"{path} is outside normalizable range.")
    return None


def _normalize_bbox(container: dict[str, Any], key: str, path: str, report: dict[str, Any]) -> None:
    value = container.get(key)
    if value is None:
        return
    if not isinstance(value, dict):
        _report_error(report, "invalid_bbox", path, f"{path} must be an object.")
        return
    for axis in ("x", "y", "width", "height"):
        if axis not in value:
            _report_error(report, "invalid_bbox", f"{path}.{axis}", f"{path}.{axis} is required.")
            continue
        normalized = _clamp_number(value[axis], f"{path}.{axis}", report)
        if normalized is not None:
            value[axis] = normalized


def _normalize_point(container: dict[str, Any], key: str, path: str, report: dict[str, Any]) -> None:
    value = container.get(key)
    if value is None:
        return
    if not isinstance(value, dict):
        _report_error(report, "invalid_point", path, f"{path} must be an object.")
        return
    for axis in ("x", "y"):
        if axis not in value:
            _report_error(report, "invalid_point", f"{path}.{axis}", f"{path}.{axis} is required.")
            continue
        normalized = _clamp_number(value[axis], f"{path}.{axis}", report)
        if normalized is not None:
            value[axis] = normalized


def _infer_click_from_bbox(container: dict[str, Any], path: str, report: dict[str, Any]) -> None:
    if container.get("click_point_norm") is not None:
        return
    bbox = container.get("bbox_norm")
    if not isinstance(bbox, dict):
        return
    needed = ("x", "y", "width", "height")
    if not all(isinstance(bbox.get(key), (int, float)) and not isinstance(bbox.get(key), bool) for key in needed):
        return
    container["click_point_norm"] = {
        "x": min(1.0, max(0.0, float(bbox["x"]) + float(bbox["width"]) / 2.0)),
        "y": min(1.0, max(0.0, float(bbox["y"]) + float(bbox["height"]) / 2.0)),
    }
    _add(
        report,
        "warnings",
        "inferred_click_point",
        f"{path}.click_point_norm",
        "click_point_norm was inferred from bbox_norm center.",
    )


def _normalize_action(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", " ")
    mapping = {
        "navigate to next page": "next_page",
        "next": "next_page",
        "next page": "next_page",
        "continue": "continue",
        "submit": "submit",
        "previous": "previous_page",
        "previous page": "previous_page",
        "skip": "skip",
    }
    return mapping.get(text, "unknown")


def _has_textual_content(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_textual_content(value.get(key)) for key in ("text", "label", "summary", "title"))
    return False


def _normalize_light_extracted(extracted: dict[str, Any], report: dict[str, Any]) -> None:
    page_summary = extracted.get("page_summary")
    if isinstance(page_summary, dict) and "page" not in extracted:
        extracted["page"] = {
            "page_type": page_summary.get("page_type", "unknown"),
            "language": page_summary.get("language", "unknown"),
            "page_status": page_summary.get("page_status", "unknown"),
            "confidence": page_summary.get("confidence", 0.0),
        }
        _add(report, "info", "normalized_page_summary", "page_summary", "Mapped page_summary to page.")
    elif page_summary is not None and not isinstance(page_summary, dict):
        _report_error(report, "invalid_page_summary", "page_summary", "page_summary must be an object.")
    _drop_incomplete_light_bboxes(extracted, "$", report)


def _drop_incomplete_light_bboxes(value: Any, path: str, report: dict[str, Any]) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _drop_incomplete_light_bboxes(item, f"{path}[{index}]", report)
        return
    if not isinstance(value, dict):
        return
    bbox = value.get("bbox_norm")
    if isinstance(bbox, dict) and not all(axis in bbox for axis in ("x", "y", "width", "height")):
        value["bbox_norm"] = None
        _add(
            report,
            "info",
            "ignored_incomplete_light_bbox",
            f"{path}.bbox_norm",
            "Ignored incomplete light-mode bbox_norm.",
        )
    for key, item in value.items():
        if key != "bbox_norm":
            _drop_incomplete_light_bboxes(item, f"{path}.{key}", report)


def _validate_light_input_fields(parsed: dict[str, Any], report: dict[str, Any]) -> None:
    if "input_fields" not in parsed:
        return
    if not isinstance(parsed["input_fields"], list):
        _report_error(report, "invalid_input_fields", "input_fields", "input_fields must be a list.")
        parsed["input_fields"] = []
        return
    for field_index, field_value in enumerate(parsed["input_fields"]):
        field_path = f"input_fields[{field_index}]"
        if not isinstance(field_value, dict):
            _report_error(report, "invalid_input_field", field_path, f"{field_path} must be an object.")
            continue
        if "field_type" in field_value:
            _normalize_enum(field_value, "field_type", FIELD_TYPES, f"{field_path}.field_type", report, raw_key="raw_field_type")
        _normalize_bbox(field_value, "bbox_norm", f"{field_path}.bbox_norm", report)
        _infer_click_from_bbox(field_value, field_path, report)
        _normalize_point(field_value, "click_point_norm", f"{field_path}.click_point_norm", report)


def validate_parsed_page(
    raw_text: str,
    runtime_context: dict[str, Any] | None = None,
    output_level: str = "standard",
) -> dict[str, Any]:
    parsed, _report = validate_parsed_page_with_report(raw_text, runtime_context, output_level=output_level)
    return parsed


def validate_parsed_page_with_report(
    raw_text: str,
    runtime_context: dict[str, Any] | None = None,
    output_level: str = "standard",
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = empty_validation_report()
    try:
        extracted = extract_json(raw_text)
    except ValidationError as exc:
        code = "response_not_object" if "must be an object" in str(exc) else "invalid_json"
        _report_error(report, code, "$", str(exc))
        try:
            _raise_report(report)
        except ValidationError as report_exc:
            raise report_exc from exc
    if "metadata" in extracted and not isinstance(extracted["metadata"], dict):
        _report_error(report, "invalid_metadata", "metadata", "metadata must be an object.")
    selected_output_level = output_level if output_level in {"light", "standard"} else "standard"
    if selected_output_level == "light":
        _normalize_light_extracted(extracted, report)

    parsed = normalize_parsed_page(extracted, task_id=str((runtime_context or {}).get("task_id", "")))
    supported = set(get_supported_question_types(runtime_context or {}))
    supported = supported.intersection(QUESTION_TYPES) or QUESTION_TYPES

    if not isinstance(parsed.get("page"), dict):
        _report_error(report, "invalid_page", "page", "page must be an object.")
        parsed["page"] = {"page_type": "unknown", "language": "unknown", "page_status": "unknown", "confidence": 0.0}
    page = parsed["page"]
    _normalize_enum(page, "page_type", PAGE_TYPES, "page.page_type", report, raw_key="raw_page_type")
    _normalize_enum(page, "language", LANGUAGES, "page.language", report)
    _normalize_enum(page, "page_status", PAGE_STATUSES, "page.page_status", report)
    if "confidence" in page:
        normalized_confidence = _clamp_number(page.get("confidence"), "page.confidence", report)
        if normalized_confidence is not None:
            page["confidence"] = normalized_confidence
    else:
        page["confidence"] = 0.0

    if not isinstance(parsed.get("questions"), list):
        _report_error(report, "invalid_questions", "questions", "questions must be a list.")
        parsed["questions"] = []
    questions = parsed["questions"]
    seen_question_ids: set[str] = set()
    for index, question_value in enumerate(questions):
        qpath = f"questions[{index}]"
        if not isinstance(question_value, dict):
            _report_error(report, "invalid_question", qpath, f"{qpath} must be an object.")
            continue
        question = question_value
        question_id = str(question.get("question_id", ""))
        if not question_id:
            question_id = f"q{index + 1}"
            question["question_id"] = question_id
            _add(report, "info", "generated_id", f"{qpath}.question_id", "Generated missing question_id.")
        seen_question_ids.add(question_id)
        question_type = _normalize_enum(
            question,
            "question_type",
            supported,
            f"{qpath}.question_type",
            report,
            raw_key="raw_question_type",
        )

        if not isinstance(question.get("question_stem"), dict):
            question["question_stem"] = {"text": str(question.get("text") or question.get("label") or ""), "bbox_norm": None}
            _add(report, "info", "normalized_question_stem", f"{qpath}.question_stem", "Created empty question_stem object.")
        stem = question["question_stem"]
        _normalize_bbox(stem, "bbox_norm", f"{qpath}.question_stem.bbox_norm", report)

        for instruction_index, instruction_value in enumerate(
            question.get("instructions", []) if isinstance(question.get("instructions", []), list) else []
        ):
            instruction_path = f"{qpath}.instructions[{instruction_index}]"
            if not isinstance(instruction_value, dict):
                _report_error(report, "invalid_instruction", instruction_path, f"{instruction_path} must be an object.")
                continue
            _normalize_bbox(instruction_value, "bbox_norm", f"{instruction_path}.bbox_norm", report)

        for option_index, option_value in enumerate(
            question.get("answer_options", []) if isinstance(question.get("answer_options", []), list) else []
        ):
            option_path = f"{qpath}.answer_options[{option_index}]"
            if not isinstance(option_value, dict):
                _report_error(report, "invalid_answer_option", option_path, f"{option_path} must be an object.")
                continue
            option = option_value
            option_id = str(option.get("option_id", ""))
            if not option_id:
                option["option_id"] = f"{question_id}_option_{option_index + 1}"
                _add(report, "info", "generated_id", f"{option_path}.option_id", "Generated missing option_id.")
            if _is_missing(option.get("option_type")):
                option["option_type"] = "text_option" if option.get("text") or option.get("label") else "unknown"
                _add(report, "warnings", "missing_optional_enum", f"{option_path}.option_type", f"Set option_type to {option['option_type']}.")
            else:
                _normalize_enum(option, "option_type", OPTION_TYPES, f"{option_path}.option_type", report, raw_key="raw_option_type")
            if _is_missing(option.get("selection_control")):
                option["selection_control"] = "checkbox" if question_type == "multiple_choice" else "radio" if question_type == "single_choice" else "unknown"
                _add(report, "warnings", "missing_optional_enum", f"{option_path}.selection_control", f"Set selection_control to {option['selection_control']}.")
            else:
                _normalize_enum(option, "selection_control", SELECTION_CONTROLS, f"{option_path}.selection_control", report, raw_key="raw_selection_control")
            _normalize_bbox(option, "bbox_norm", f"{option_path}.bbox_norm", report)
            _infer_click_from_bbox(option, option_path, report)
            _normalize_point(option, "click_point_norm", f"{option_path}.click_point_norm", report)

        for field_index, field_value in enumerate(
            question.get("input_fields", []) if isinstance(question.get("input_fields", []), list) else []
        ):
            field_path = f"{qpath}.input_fields[{field_index}]"
            if not isinstance(field_value, dict):
                _report_error(report, "invalid_input_field", field_path, f"{field_path} must be an object.")
                continue
            input_field = field_value
            _normalize_enum(input_field, "field_type", FIELD_TYPES, f"{field_path}.field_type", report, raw_key="raw_field_type")
            _normalize_bbox(input_field, "bbox_norm", f"{field_path}.bbox_norm", report)
            _infer_click_from_bbox(input_field, field_path, report)
            _normalize_point(input_field, "click_point_norm", f"{field_path}.click_point_norm", report)

        media_items = question.get("media", []) if isinstance(question.get("media", []), list) else []
        ambiguous_media = False
        for media_index, media_value in enumerate(media_items):
            media_path = f"{qpath}.media[{media_index}]"
            if not isinstance(media_value, dict):
                _report_error(report, "invalid_media", media_path, f"{media_path} must be an object.")
                continue
            media = media_value
            _normalize_enum(media, "media_type", MEDIA_TYPES, f"{media_path}.media_type", report)
            _normalize_enum(media, "role", MEDIA_ROLES, f"{media_path}.role", report)
            _normalize_bbox(media, "bbox_norm", f"{media_path}.bbox_norm", report)
            if media.get("human_review_required") or media.get("requires_audio_understanding"):
                ambiguous_media = True
        if ambiguous_media and not parsed["uncertainties"]:
            _add(report, "warnings", "missing_uncertainty", f"{qpath}.media", "Ambiguous media found without uncertainties.")

        if "confidence" in question:
            normalized_confidence = _clamp_number(question.get("confidence"), f"{qpath}.confidence", report)
            if normalized_confidence is not None:
                question["confidence"] = normalized_confidence

    if not isinstance(parsed.get("navigation_buttons"), list):
        _report_error(report, "invalid_navigation_buttons", "navigation_buttons", "navigation_buttons must be a list.")
        parsed["navigation_buttons"] = []
    seen_button_candidates: set[str] = set()
    for button_index, button_value in enumerate(parsed["navigation_buttons"]):
        button_path = f"navigation_buttons[{button_index}]"
        if not isinstance(button_value, dict):
            _report_error(report, "invalid_navigation_button", button_path, f"{button_path} must be an object.")
            continue
        button = button_value
        candidate = str(button.get("label") or button.get("text") or button.get("action") or button_index)
        if candidate in seen_button_candidates:
            _add(report, "warnings", "duplicate_navigation_button_candidate", button_path, "Duplicate navigation button candidate.")
        seen_button_candidates.add(candidate)
        if _is_missing(button.get("button_id")):
            stable = candidate.strip().lower().replace(" ", "_") or f"button_{button_index + 1}"
            button["button_id"] = f"nav_{stable}"
            _add(report, "warnings", "missing_optional_enum", f"{button_path}.button_id", "Generated missing button_id.")
        raw_action = button.get("action")
        normalized_action = _normalize_action(raw_action)
        if _is_missing(raw_action):
            _add(
                report,
                "warnings",
                "missing_optional_enum",
                f"{button_path}.action",
                "Navigation action was missing; set to unknown.",
            )
        if normalized_action != str(raw_action or "") and not _is_missing(raw_action):
            button.setdefault("raw_action", str(raw_action))
        if normalized_action == "unknown" and not _is_missing(raw_action):
            _add(report, "warnings", "unknown_action_text", f"{button_path}.action", f"Unknown navigation action {raw_action!r}.")
        button["action"] = normalized_action
        _normalize_bbox(button, "bbox_norm", f"{button_path}.bbox_norm", report)
        _infer_click_from_bbox(button, button_path, report)
        _normalize_point(button, "click_point_norm", f"{button_path}.click_point_norm", report)

    if not isinstance(parsed.get("visual_elements"), list):
        _report_error(report, "invalid_visual_elements", "visual_elements", "visual_elements must be a list.")
        parsed["visual_elements"] = []
    for element_index, element_value in enumerate(parsed["visual_elements"]):
        element_path = f"visual_elements[{element_index}]"
        if not isinstance(element_value, dict):
            _report_error(report, "invalid_visual_element", element_path, f"{element_path} must be an object.")
            continue
        if _is_missing(element_value.get("element_id")):
            element_value["element_id"] = f"ve_{element_index + 1}"
            _add(report, "info", "generated_id", f"{element_path}.element_id", "Generated missing element_id.")
        if "element_role" not in element_value and "raw_type" in element_value:
            element_value["element_role"] = element_value["raw_type"]
        _normalize_enum(element_value, "element_role", ELEMENT_ROLES, f"{element_path}.element_role", report, raw_key="raw_type")
        _normalize_bbox(element_value, "bbox_norm", f"{element_path}.bbox_norm", report)
        _infer_click_from_bbox(element_value, element_path, report)
        _normalize_point(element_value, "click_point_norm", f"{element_path}.click_point_norm", report)
        if "metadata" in element_value and not isinstance(element_value["metadata"], dict):
            element_value["metadata"] = {"raw_metadata": element_value["metadata"]}
            _add(report, "info", "normalized_metadata", f"{element_path}.metadata", "Wrapped non-object metadata.")

    for uncertainty_index, uncertainty_value in enumerate(
        parsed["uncertainties"] if isinstance(parsed.get("uncertainties"), list) else []
    ):
        if not isinstance(uncertainty_value, dict):
            _report_error(report, "invalid_uncertainty", f"uncertainties[{uncertainty_index}]", "uncertainty must be an object.")
            continue
        uncertainty = uncertainty_value
        related = str(uncertainty.get("related_question_id", ""))
        if related and related not in seen_question_ids:
            _add(
                report,
                "warnings",
                "unknown_related_question",
                f"uncertainties[{uncertainty_index}].related_question_id",
                "related_question_id does not match a question.",
            )

    if selected_output_level == "light":
        _validate_light_input_fields(parsed, report)

    recognizable = bool(parsed["visual_elements"] or parsed["navigation_buttons"])
    if selected_output_level == "standard":
        recognizable = recognizable or bool(parsed["uncertainties"])
    else:
        recognizable = recognizable or bool(parsed.get("input_fields"))
    recognizable = recognizable or any(
        isinstance(question, dict)
        and (
            _has_textual_content(question.get("question_stem"))
            or bool(question.get("answer_options"))
            or bool(question.get("input_fields"))
            or bool(question.get("media"))
        )
        for question in parsed["questions"]
    )
    recognizable = recognizable or _has_textual_content(page)
    if not recognizable:
        _report_error(report, "no_recognizable_content", "$", "Response contains no recognizable page content.")

    if not report["validation_passed"]:
        _raise_report(report)
    return parsed, report


def validate_scene_scan(raw_text: str) -> dict[str, Any]:
    extracted = extract_json(raw_text)
    if "metadata" in extracted:
        _require_object(extracted["metadata"], "metadata")
    for field in SCENE_SCAN_REQUIRED_FIELDS:
        if field not in extracted:
            raise ValidationError(f"Missing top-level field: {field}")
    _require_list(extracted["detected_interaction_types"], "detected_interaction_types")
    _check_enum(
        extracted.get("recommended_parser"),
        {"form", "survey", "image_task", "drag_drop", "matrix", "modal", "general", "scene_scan"},
        "recommended_parser",
    )
    _check_norm_number(extracted.get("confidence"), "confidence")
    return extracted


def validate_file(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8-sig")
    return validate_parsed_page(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a raw vision model response.")
    parser.add_argument("raw_response_path")
    args = parser.parse_args()
    try:
        raw = Path(args.raw_response_path).read_text(encoding="utf-8-sig")
        parsed, report = validate_parsed_page_with_report(raw)
    except ValidationError as exc:
        report = exc.report or {
            "validation_passed": False,
            "errors": [_message("validation_error", "$", str(exc))],
            "warnings": [],
            "info": [],
            "normalization_applied": [],
        }
        write_json(VALIDATION_REPORT_PATH, report)
        print(str(exc))
        raise SystemExit(1) from exc
    write_json(VALIDATION_REPORT_PATH, report)
    print(json.dumps(parsed, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
