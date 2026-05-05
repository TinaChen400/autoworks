from __future__ import annotations

from typing import Any

from .base_skill import BaseDryRunSkill, dry_run_result


class _AtomicMouseSkill(BaseDryRunSkill):
    name = ""
    simulated_operation = ""

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        return dry_run_result(
            action,
            details={
                "layer": "atomic",
                "simulated_operation": self.simulated_operation,
            },
        )


class MoveMouseAtomicSkill(_AtomicMouseSkill):
    name = "move_mouse"
    simulated_operation = "position_pointer_preview"


class LeftClickAtomicSkill(_AtomicMouseSkill):
    name = "left_click"
    simulated_operation = "left_click_preview"


class DoubleClickAtomicSkill(_AtomicMouseSkill):
    name = "double_click"
    simulated_operation = "double_click_preview"


class ScrollAtomicSkill(_AtomicMouseSkill):
    name = "scroll"
    simulated_operation = "scroll_preview"


def mouse_atomic_skills() -> list[BaseDryRunSkill]:
    return [
        MoveMouseAtomicSkill(),
        LeftClickAtomicSkill(),
        DoubleClickAtomicSkill(),
        ScrollAtomicSkill(),
    ]
