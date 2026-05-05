from __future__ import annotations

from typing import Any

from modules.skills.base_skill import BaseDryRunSkill
from modules.skills.verification_hooks import verify_option_selected, verify_text_entered

from .schema import atomic_action, composite_result, run_atomic_step


class FillTextFieldSkill(BaseDryRunSkill):
    name = "fill_text_field"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        steps = [
            run_atomic_step(atomic_action(action, "focus_window")),
            run_atomic_step(atomic_action(action, "move_mouse")),
            run_atomic_step(atomic_action(action, "left_click")),
            run_atomic_step(atomic_action(action, "type_text")),
            verify_text_entered(action),
        ]
        return composite_result(action, self.name, steps, {"simulated_operation": "enter_text"})


class TypeTextSkill(FillTextFieldSkill):
    name = "type_text"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        steps = [
            run_atomic_step(atomic_action(action, "focus_window")),
            run_atomic_step(atomic_action(action, "move_mouse")),
            run_atomic_step(atomic_action(action, "left_click")),
            run_atomic_step(atomic_action(action, "type_text")),
            verify_text_entered(action),
        ]
        return composite_result(
            action,
            "fill_text_field",
            steps,
            {"routed_from": "type_text", "simulated_operation": "enter_text"},
        )


class SelectDropdownOptionSkill(BaseDryRunSkill):
    name = "select_dropdown_option"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        steps = [
            run_atomic_step(atomic_action(action, "move_mouse")),
            run_atomic_step(atomic_action(action, "left_click")),
            run_atomic_step(atomic_action(action, "press_key", {"key": "arrow_down"})),
            run_atomic_step(atomic_action(action, "press_key", {"key": "enter"})),
            verify_option_selected(action),
        ]
        return composite_result(
            action,
            self.name,
            steps,
            {"simulated_operation": "choose_dropdown_option"},
        )


class SelectDropdownSkill(SelectDropdownOptionSkill):
    name = "select_dropdown"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        result = super().execute(action)
        result["composite_skill"] = "select_dropdown_option"
        result["details"]["routed_from"] = "select_dropdown"
        result["details"]["simulated_operation"] = "choose_dropdown_option"
        return result


def form_composite_skills() -> list[BaseDryRunSkill]:
    return [
        FillTextFieldSkill(),
        TypeTextSkill(),
        SelectDropdownOptionSkill(),
        SelectDropdownSkill(),
    ]
