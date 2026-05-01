from __future__ import annotations

from modules.context_mapper.prompt_builder import build_answer_prompt, build_vision_prompt
from modules.context_mapper.task_context_loader import load_effective_task_context


def test_vision_prompt_contains_required_parse_instructions() -> None:
    context = load_effective_task_context("tts01")
    prompt = build_vision_prompt(context)

    assert "Separate the main question stem" in prompt
    assert "navigation buttons separately" in prompt
    assert "normalized coordinates relative to the model input screenshot region" in prompt
    assert "Return JSON only" in prompt
    assert "Never reuse coordinates" in prompt


def test_answer_prompt_requires_review_and_avoids_invented_facts() -> None:
    context = load_effective_task_context("tts01")
    prompt = build_answer_prompt(context)

    assert "Do not invent personal facts" in prompt
    assert "Use local user knowledge" in prompt
    assert "Require human review" in prompt
