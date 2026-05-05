from __future__ import annotations

from typing import Any

from modules.skills.base_skill import BaseDryRunSkill
from modules.skills.verification_hooks import verify_option_selected

from .schema import click_steps, composite_result


class SelectSingleChoiceOptionSkill(BaseDryRunSkill):
    name = "select_single_choice_option"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        steps = click_steps(action)
        steps.append(verify_option_selected(action))
        return composite_result(
            action,
            self.name,
            steps,
            {"simulated_operation": "select_option"},
        )


class ClickOptionSkill(SelectSingleChoiceOptionSkill):
    name = "click_option"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        steps = click_steps(action)
        steps.append(verify_option_selected(action))
        return composite_result(
            action,
            "select_single_choice_option",
            steps,
            {"routed_from": "click_option", "simulated_operation": "select_option"},
        )


class SelectMultipleChoiceOptionsSkill(BaseDryRunSkill):
    name = "select_multiple_choice_options"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        params = action.get("params") if isinstance(action.get("params"), dict) else {}
        options = params.get("options")
        if not isinstance(options, list) or not options:
            steps = click_steps(action)
            steps.append(verify_option_selected(action))
            return composite_result(
                action,
                self.name,
                steps,
                {"simulated_operation": "select_options"},
            )

        steps: list[dict[str, Any]] = []
        for option in options:
            option_action = {
                **action,
                "target": option if isinstance(option, dict) else action.get("target", {}),
            }
            steps.extend(click_steps(option_action))
            steps.append(verify_option_selected(option_action))
        return composite_result(
            action,
            self.name,
            steps,
            {"simulated_operation": "select_options"},
        )


def choice_composite_skills() -> list[BaseDryRunSkill]:
    return [
        ClickOptionSkill(),
        SelectSingleChoiceOptionSkill(),
        SelectMultipleChoiceOptionsSkill(),
    ]
