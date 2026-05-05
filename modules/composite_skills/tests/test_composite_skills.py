from __future__ import annotations

import ast
from pathlib import Path

from modules.skills.skill_registry import default_skill_registry


def _action(action_id: str = "a1", skill: str = "click_option") -> dict:
    return {
        "action_id": action_id,
        "skill": skill,
        "target": {
            "question_id": "q1",
            "option_id": "o1",
            "click_point_screen": {"x": 100, "y": 200},
        },
        "params": {},
    }


def test_click_option_expands_to_option_selection_steps() -> None:
    result = default_skill_registry().execute(_action("a1", "click_option"))

    assert result["status"] == "success"
    assert result["composite_skill"] == "select_single_choice_option"
    assert [step["skill"] for step in result["atomic_steps"]] == [
        "move_mouse",
        "left_click",
        "wait",
        "verify_option_selected",
    ]
    assert all(step["dry_run"] is True for step in result["atomic_steps"])


def test_type_text_expands_to_focus_click_text_and_verification() -> None:
    action = _action("a1", "type_text")
    action["params"] = {"text": "hello"}

    result = default_skill_registry().execute(action)

    assert result["composite_skill"] == "fill_text_field"
    assert [step["skill"] for step in result["atomic_steps"]] == [
        "focus_window",
        "move_mouse",
        "left_click",
        "type_text",
        "verify_text_entered",
    ]


def test_submit_page_is_separate_from_answer_option_click() -> None:
    registry = default_skill_registry()

    option_result = registry.execute(_action("a1", "click_option"))
    submit_result = registry.execute(_action("a2", "submit_page"))

    assert option_result["composite_skill"] == "select_single_choice_option"
    assert submit_result["composite_skill"] == "submit_page"
    assert "verify_option_selected" not in [
        step["skill"] for step in submit_result["atomic_steps"]
    ]


def test_unknown_skill_fails_safely() -> None:
    result = default_skill_registry().execute(_action("a1", "missing_skill"))

    assert result["status"] == "failed"
    assert result["dry_run"] is True
    assert result["failure"]["code"] == "unknown_skill"


def test_no_os_interaction_libraries_imported_by_skill_layers() -> None:
    blocked_modules = {
        "ctypes",
        "win32api",
        "win32con",
        "win32gui",
        "pyautogui",
        "keyboard",
        "mouse",
        "pynput",
    }
    roots = [Path("modules/skills"), Path("modules/composite_skills")]

    imports: set[str] = set()
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])

    assert blocked_modules.isdisjoint(imports)
