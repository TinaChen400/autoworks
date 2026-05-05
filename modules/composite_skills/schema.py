from __future__ import annotations

from copy import deepcopy
from typing import Any

from modules.skills.atomic_keyboard_skills import keyboard_atomic_skills
from modules.skills.atomic_mouse_skills import mouse_atomic_skills
from modules.skills.atomic_wait_skills import wait_atomic_skills
from modules.skills.atomic_window_skills import window_atomic_skills
from modules.skills.base_skill import BaseDryRunSkill


def _atomic_skill_map() -> dict[str, BaseDryRunSkill]:
    skills = (
        mouse_atomic_skills()
        + keyboard_atomic_skills()
        + wait_atomic_skills()
        + window_atomic_skills()
    )
    return {skill.name: skill for skill in skills}


ATOMIC_SKILLS = _atomic_skill_map()


def atomic_action(
    source_action: dict[str, Any],
    skill: str,
    params: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_target = source_action.get("target")
    source_params = source_action.get("params")
    return {
        "action_id": source_action.get("action_id", ""),
        "skill": skill,
        "target": deepcopy(
            target
            if target is not None
            else source_target
            if isinstance(source_target, dict)
            else {}
        ),
        "params": deepcopy(
            params
            if params is not None
            else source_params
            if isinstance(source_params, dict)
            else {}
        ),
    }


def run_atomic_step(action: dict[str, Any]) -> dict[str, Any]:
    skill_name = str(action.get("skill") or "")
    skill = ATOMIC_SKILLS.get(skill_name)
    if skill is None:
        return {
            "action_id": action.get("action_id", ""),
            "skill": skill_name,
            "status": "failed",
            "dry_run": True,
            "failure": {
                "code": "unknown_atomic_skill",
                "message": f"No atomic dry-run skill registered for '{skill_name}'.",
            },
        }
    return skill.execute(action)


def composite_result(
    action: dict[str, Any],
    composite_skill: str,
    atomic_steps: list[dict[str, Any]],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "action_id": action.get("action_id", ""),
        "skill": action.get("skill", ""),
        "status": "success",
        "dry_run": True,
        "target": action.get("target", {}) if isinstance(action.get("target"), dict) else {},
        "params": action.get("params", {}) if isinstance(action.get("params"), dict) else {},
        "composite_skill": composite_skill,
        "atomic_steps": atomic_steps,
        "details": {
            "layer": "composite",
            **(details or {}),
        },
    }


def click_steps(action: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        run_atomic_step(atomic_action(action, "move_mouse")),
        run_atomic_step(atomic_action(action, "left_click")),
        run_atomic_step(atomic_action(action, "wait", {"duration_ms": 100})),
    ]
