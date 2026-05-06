from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from modules.vision_parser.doubao_client import call_vision_model, mask_api_key
from modules.vision_parser.image_payload import prepare_model_input_image
from modules.vision_parser.parse_store import DIAGNOSTICS_PATH, VALIDATION_REPORT_PATH
from modules.vision_parser.parser import parse_latest_runtime_context
from modules.vision_parser.prompt import build_final_prompt
from modules.vision_parser.response_validator import (
    ValidationError,
    validate_parsed_page,
    validate_parsed_page_with_report,
)
from modules.vision_parser.schema import sample_parsed_page


def runtime_context(image_path: Path) -> dict:
    return {
        "task_id": "test_task",
        "screenshot_path": str(image_path),
        "model_input_region": {"x": 0, "y": 0, "width": 100, "height": 80},
        "vision_prompt": "Parse this page.",
        "supported_question_types": ["single_choice", "unknown"],
    }


def test_fake_parser_returns_valid_parsed_page_json(tmp_path: Path) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    output_path = tmp_path / "model_input.png"

    prepared = prepare_model_input_image(
        image_path,
        runtime_context(image_path)["model_input_region"],
        output_path,
    )
    raw = call_vision_model("fake", "prompt", output_path, "test_task")
    parsed = validate_parsed_page(raw, runtime_context(image_path))

    assert prepared.exists()
    assert parsed["task_id"] == "test_task"
    assert parsed["questions"][0]["question_type"] == "unknown"


def test_validator_accepts_valid_fake_json() -> None:
    parsed = validate_parsed_page(
        json.dumps(sample_parsed_page("test_task")),
        {"task_id": "test_task", "supported_question_types": ["unknown"]},
    )
    assert parsed["parse_id"]


def test_validator_accepts_metadata() -> None:
    payload = sample_parsed_page("test_task")
    payload["metadata"] = {"parser_type_used": "form", "source": "vision_parser"}
    parsed = validate_parsed_page(
        json.dumps(payload),
        {"task_id": "test_task", "supported_question_types": ["unknown"]},
    )
    assert parsed["metadata"]["parser_type_used"] == "form"


def test_validator_normalizes_string_uncertainties() -> None:
    payload = sample_parsed_page("test_task")
    payload["uncertainties"] = ["Duplicate identical survey questions are displayed."]

    parsed, report = validate_parsed_page_with_report(
        json.dumps(payload),
        {"task_id": "test_task", "supported_question_types": ["unknown"]},
    )

    assert parsed["uncertainties"] == [
        {
            "type": "model_uncertainty",
            "message": "Duplicate identical survey questions are displayed.",
            "related_question_id": "",
        }
    ]
    assert report["validation_passed"] is True
    assert any(item["code"] == "normalized_uncertainty" for item in report["warnings"])


def test_validator_rejects_invalid_bbox_norm() -> None:
    payload = sample_parsed_page("test_task")
    payload["questions"][0]["question_stem"]["bbox_norm"]["x"] = 1.5
    with pytest.raises(ValidationError):
        validate_parsed_page(json.dumps(payload), {"supported_question_types": ["unknown"]})


def test_validator_normalizes_unknown_question_type_not_in_allowed_list() -> None:
    payload = sample_parsed_page("test_task")
    payload["questions"][0]["question_type"] = "image_reasoning"
    parsed, report = validate_parsed_page_with_report(
        json.dumps(payload),
        {"supported_question_types": ["single_choice"]},
    )
    assert parsed["questions"][0]["question_type"] == "unknown"
    assert report["validation_passed"] is True
    assert report["warnings"]


def test_prompt_builder_includes_json_only_instruction(tmp_path: Path) -> None:
    prompt = build_final_prompt(runtime_context(tmp_path / "capture.png"))
    assert "Return JSON only." in prompt
    assert "Do not answer the task." in prompt


def test_prompt_builder_includes_form_parser_instructions(tmp_path: Path) -> None:
    prompt = build_final_prompt(runtime_context(tmp_path / "capture.png"), parser_type="form")
    assert "Parser type: form" in prompt
    assert "Focus on form sections" in prompt


def test_light_form_prompt_is_shorter_than_standard_form_prompt(tmp_path: Path) -> None:
    context = runtime_context(tmp_path / "capture.png")
    standard = build_final_prompt(context, parser_type="form", output_level="standard")
    light = build_final_prompt(context, parser_type="form", output_level="light")

    assert len(light) < len(standard)
    assert len(light) < 1500


def test_light_form_prompt_omits_heavy_interaction_instructions(tmp_path: Path) -> None:
    prompt = build_final_prompt(
        runtime_context(tmp_path / "capture.png"),
        parser_type="form",
        output_level="light",
    )

    assert "drag_drop" not in prompt
    assert "matrix" not in prompt
    assert "audio" not in prompt


def test_secrets_loader_masks_api_key_in_logs() -> None:
    assert mask_api_key("sk-test123456") == "sk-****3456"


def test_fake_mode_accepts_parser_type_form() -> None:
    parsed = parse_latest_runtime_context(mode="fake", parser_type="form")
    assert parsed["metadata"]["parser_type_used"] == "form"


def test_fake_mode_accepts_input_image_path() -> None:
    image_path = Path("runtime_state/crops/R10_card_account_annotated.png")
    parsed = parse_latest_runtime_context(mode="fake", parser_type="form", input_image=image_path)
    assert parsed["metadata"]["input_image_used"] == str(image_path)


def test_fake_mode_can_load_parse_plan(tmp_path: Path) -> None:
    image_path = tmp_path / "plan_input.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    parse_plan_path = tmp_path / "parse_plan.json"
    parse_plan_path.write_text(
        json.dumps(
            {
                "selected_parser_type": "form",
                "selected_output_level": "standard",
                "selected_input_images": [str(image_path)],
                "selected_region_ids": ["R1"],
            }
        ),
        encoding="utf-8",
    )
    parsed = parse_latest_runtime_context(
        mode="fake",
        from_parse_plan=parse_plan_path,
    )
    assert parsed["metadata"]["parse_plan_used"] is True
    assert parsed["metadata"]["parser_type_used"] == "form"


def test_missing_input_image_returns_clear_error() -> None:
    with pytest.raises(FileNotFoundError, match="Selected input image not found."):
        parse_latest_runtime_context(
            mode="fake",
            parser_type="form",
            input_image="runtime_state/crops/does_not_exist.png",
        )


def test_existing_old_fake_command_still_works() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "modules.vision_parser.parser", "--mode", "fake"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Saved ParsedPage JSON" in completed.stdout


def test_cli_accepts_output_level_light() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "modules.vision_parser.parser",
            "--mode",
            "fake",
            "--parser-type",
            "form",
            "--output-level",
            "light",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Saved ParsedPage JSON" in completed.stdout


def test_answer_option_option_type_none_normalizes_and_passes() -> None:
    payload = sample_parsed_page("test_task")
    payload["questions"][0]["question_type"] = "single_choice"
    payload["questions"][0]["answer_options"] = [
        {
            "option_id": "a",
            "option_type": None,
            "selection_control": "radio",
            "text": "Option A",
            "bbox_norm": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1},
        }
    ]
    parsed, report = validate_parsed_page_with_report(json.dumps(payload), {"supported_question_types": ["single_choice"]})

    assert parsed["questions"][0]["answer_options"][0]["option_type"] == "text_option"
    assert parsed["questions"][0]["answer_options"][0]["click_point_norm"] == {"x": 0.25, "y": 0.25}
    assert report["validation_passed"] is True


def test_answer_option_missing_selection_control_normalizes_and_passes() -> None:
    payload = sample_parsed_page("test_task")
    payload["questions"][0]["question_type"] = "multiple_choice"
    payload["questions"][0]["answer_options"] = [
        {
            "option_id": "a",
            "option_type": "text_option",
            "text": "Option A",
            "bbox_norm": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1},
        }
    ]
    parsed, report = validate_parsed_page_with_report(json.dumps(payload), {"supported_question_types": ["multiple_choice"]})

    assert parsed["questions"][0]["answer_options"][0]["selection_control"] == "checkbox"
    assert report["validation_passed"] is True


def test_navigation_action_text_normalizes_to_next_page() -> None:
    payload = sample_parsed_page("test_task")
    payload["navigation_buttons"] = [
        {
            "label": "Next",
            "action": "navigate to next page",
            "bbox_norm": {"x": 0.8, "y": 0.8, "width": 0.1, "height": 0.1},
        }
    ]
    parsed, report = validate_parsed_page_with_report(json.dumps(payload), {"supported_question_types": ["unknown"]})

    assert parsed["navigation_buttons"][0]["action"] == "next_page"
    assert parsed["navigation_buttons"][0]["button_id"] == "nav_next"
    assert parsed["navigation_buttons"][0]["click_point_norm"]["x"] == pytest.approx(0.85)
    assert parsed["navigation_buttons"][0]["click_point_norm"]["y"] == pytest.approx(0.85)
    assert report["validation_passed"] is True


def test_visual_elements_only_response_passes() -> None:
    payload = {
        "page": {"page_type": "unknown", "language": "en", "page_status": "unknown", "confidence": 0.7},
        "visual_elements": [
            {
                "element_role": "page_title",
                "text": "Welcome",
                "bbox_norm": {"x": 0, "y": 0, "width": 0.5, "height": 0.1},
            }
        ],
    }
    parsed, report = validate_parsed_page_with_report(json.dumps(payload), {"task_id": "test_task"})

    assert parsed["visual_elements"][0]["element_role"] == "page_title"
    assert parsed["questions"] == []
    assert report["validation_passed"] is True


def test_light_json_with_visual_elements_passes_validation() -> None:
    payload = {
        "page_summary": {"page_type": "form", "language": "en", "summary": "Account form"},
        "visual_elements": [
            {
                "element_role": "form_field",
                "text": "Account number",
                "bbox_norm": {},
            }
        ],
        "input_fields": [],
        "navigation_buttons": [],
        "uncertainties": [],
    }
    parsed, report = validate_parsed_page_with_report(json.dumps(payload), output_level="light")

    assert parsed["page"]["page_type"] == "form"
    assert parsed["visual_elements"][0]["element_role"] == "form_field"
    assert parsed["visual_elements"][0]["bbox_norm"] is None
    assert report["validation_passed"] is True


def test_unknown_page_type_does_not_fail() -> None:
    payload = sample_parsed_page("test_task")
    payload["page"]["page_type"] = "learning_app"
    parsed, report = validate_parsed_page_with_report(json.dumps(payload), {"supported_question_types": ["unknown"]})

    assert parsed["page"]["page_type"] == "unknown"
    assert parsed["page"]["raw_page_type"] == "learning_app"
    assert report["validation_passed"] is True


def test_invalid_json_still_fails() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate_parsed_page_with_report("{bad json")

    assert exc_info.value.report["validation_passed"] is False
    assert exc_info.value.report["errors"][0]["code"] == "invalid_json"


def test_no_recognizable_content_fails() -> None:
    payload = {"page": {"page_type": "unknown", "language": "unknown", "page_status": "unknown", "confidence": 0.1}}
    with pytest.raises(ValidationError) as exc_info:
        validate_parsed_page_with_report(json.dumps(payload))

    assert exc_info.value.report["errors"][0]["code"] == "no_recognizable_content"


def test_normalization_warnings_are_recorded() -> None:
    payload = sample_parsed_page("test_task")
    payload["questions"][0]["answer_options"] = [
        {
            "option_id": "a",
            "option_type": None,
            "selection_control": None,
            "text": "A",
            "bbox_norm": {"x": -0.01, "y": 0.2, "width": 0.3, "height": 0.1},
        }
    ]
    _parsed, report = validate_parsed_page_with_report(json.dumps(payload), {"supported_question_types": ["unknown"]})
    codes = {warning["code"] for warning in report["warnings"]}

    assert "missing_optional_enum" in codes
    assert "inferred_click_point" in codes
    assert "clamped_bbox_value" in codes
    assert report["normalization_applied"]


def test_diagnostics_file_writer_works() -> None:
    parsed = parse_latest_runtime_context(mode="fake", parser_type="form", output_level="light")
    diagnostics = json.loads(DIAGNOSTICS_PATH.read_text(encoding="utf-8"))
    report = json.loads(VALIDATION_REPORT_PATH.read_text(encoding="utf-8"))

    assert parsed["metadata"]["parser_type_used"] == "form"
    assert diagnostics["parser_type"] == "form"
    assert diagnostics["output_level"] == "light"
    assert diagnostics["mode"] == "fake"
    assert diagnostics["validation_passed"] is True
    assert diagnostics["raw_response_char_count"] > 0
    assert report["validation_passed"] is True
