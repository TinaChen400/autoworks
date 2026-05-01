from __future__ import annotations

import json

import pytest

from modules.context_mapper.task_context_loader import (
    load_effective_task_context,
    load_json_context,
)


def test_load_tts01_merges_inherited_contexts() -> None:
    context = load_effective_task_context("tts01")

    assert context["task_id"] == "tts01"
    assert context["task_family"] == "image_recognition_family"
    assert "base_templates/base_survey.json" in context["inherited_templates"]
    assert "single_choice" in context["supported_question_types"]
    assert "image_reasoning" in context["supported_question_types"]
    assert any("question_stem" in rule for rule in context["visual_parsing_rules"])


def test_rejects_fixed_answer_coordinates(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"fixed_answer_coordinates": [{"x": 1, "y": 2}]}), encoding="utf-8")

    with pytest.raises(ValueError, match="fixed_answer_coordinates"):
        load_json_context(path)
