from __future__ import annotations

from modules.skills.skill_registry import default_skill_registry


def _action(skill: str = "click_option") -> dict:
    return {
        "action_id": "a1",
        "skill": skill,
        "target": {"question_id": "q1", "option_id": "o1"},
        "params": {},
    }


def test_default_registry_contains_required_dry_run_skills() -> None:
    registry = default_skill_registry()

    assert registry.names() == [
        "click_next",
        "click_option",
        "double_click",
        "fill_text_field",
        "focus_window",
        "left_click",
        "move_mouse",
        "press_key",
        "scroll",
        "select_dropdown",
        "select_dropdown_option",
        "select_multiple_choice_options",
        "select_single_choice_option",
        "submit",
        "submit_page",
        "type_text",
        "wait",
    ]


def test_click_option_dry_run_skill_returns_structured_result() -> None:
    result = default_skill_registry().execute(_action("click_option"))

    assert result["status"] == "success"
    assert result["dry_run"] is True
    assert result["action_id"] == "a1"
    assert result["skill"] == "click_option"
    assert result["composite_skill"] == "select_single_choice_option"
    assert [step["skill"] for step in result["atomic_steps"]] == [
        "move_mouse",
        "left_click",
        "wait",
        "verify_option_selected",
    ]


def test_unknown_skill_fails_gracefully() -> None:
    result = default_skill_registry().execute(_action("missing_skill"))

    assert result["status"] == "failed"
    assert result["dry_run"] is True
    assert result["failure"]["code"] == "unknown_skill"
