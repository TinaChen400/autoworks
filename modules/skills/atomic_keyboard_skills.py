from __future__ import annotations

from typing import Any

from .base_skill import BaseDryRunSkill, dry_run_result


class _AtomicKeyboardSkill(BaseDryRunSkill):
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


class TypeTextAtomicSkill(_AtomicKeyboardSkill):
    name = "type_text"
    simulated_operation = "text_entry_preview"


class PressKeyAtomicSkill(_AtomicKeyboardSkill):
    name = "press_key"
    simulated_operation = "key_press_preview"


def keyboard_atomic_skills() -> list[BaseDryRunSkill]:
    return [
        TypeTextAtomicSkill(),
        PressKeyAtomicSkill(),
    ]
