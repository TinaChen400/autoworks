from __future__ import annotations

from modules.composite_skills import (
    choice_composite_skills,
    form_composite_skills,
    navigation_composite_skills,
)

from .atomic_keyboard_skills import keyboard_atomic_skills
from .atomic_mouse_skills import mouse_atomic_skills
from .atomic_wait_skills import wait_atomic_skills
from .atomic_window_skills import window_atomic_skills
from .base_skill import BaseDryRunSkill


def default_dry_run_skills() -> list[BaseDryRunSkill]:
    return [
        *mouse_atomic_skills(),
        *keyboard_atomic_skills(),
        *wait_atomic_skills(),
        *window_atomic_skills(),
        *choice_composite_skills(),
        *form_composite_skills(),
        *navigation_composite_skills(),
    ]
