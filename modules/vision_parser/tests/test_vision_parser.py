from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from modules.vision_parser.doubao_client import call_vision_model, mask_api_key
from modules.vision_parser.image_payload import prepare_model_input_image
from modules.vision_parser.parser import parse_latest_runtime_context
from modules.vision_parser.prompt import build_final_prompt
from modules.vision_parser.response_validator import ValidationError, validate_parsed_page
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


def test_validator_rejects_invalid_bbox_norm() -> None:
    payload = sample_parsed_page("test_task")
    payload["questions"][0]["question_stem"]["bbox_norm"]["x"] = 1.5
    with pytest.raises(ValidationError):
        validate_parsed_page(json.dumps(payload), {"supported_question_types": ["unknown"]})


def test_validator_rejects_unknown_question_type_not_in_allowed_list() -> None:
    payload = sample_parsed_page("test_task")
    payload["questions"][0]["question_type"] = "image_reasoning"
    with pytest.raises(ValidationError):
        validate_parsed_page(json.dumps(payload), {"supported_question_types": ["single_choice"]})


def test_prompt_builder_includes_json_only_instruction(tmp_path: Path) -> None:
    prompt = build_final_prompt(runtime_context(tmp_path / "capture.png"))
    assert "Return JSON only." in prompt
    assert "Do not answer the task." in prompt


def test_prompt_builder_includes_form_parser_instructions(tmp_path: Path) -> None:
    prompt = build_final_prompt(runtime_context(tmp_path / "capture.png"), parser_type="form")
    assert "Parser type: form" in prompt
    assert "Focus on form sections" in prompt


def test_secrets_loader_masks_api_key_in_logs() -> None:
    assert mask_api_key("sk-test123456") == "sk-****3456"


def test_fake_mode_accepts_parser_type_form() -> None:
    parsed = parse_latest_runtime_context(mode="fake", parser_type="form")
    assert parsed["metadata"]["parser_type_used"] == "form"


def test_fake_mode_accepts_input_image_path() -> None:
    image_path = Path("runtime_state/crops/R10_card_account_annotated.png")
    parsed = parse_latest_runtime_context(mode="fake", parser_type="form", input_image=image_path)
    assert parsed["metadata"]["input_image_used"] == str(image_path)


def test_fake_mode_can_load_parse_plan() -> None:
    parsed = parse_latest_runtime_context(
        mode="fake",
        from_parse_plan="runtime_state/latest_parse_plan.json",
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
