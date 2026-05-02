from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from modules.vision_parser.doubao_client import call_vision_model, mask_api_key
from modules.vision_parser.image_payload import prepare_model_input_image
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


def test_secrets_loader_masks_api_key_in_logs() -> None:
    assert mask_api_key("sk-test123456") == "sk-****3456"
