from __future__ import annotations

from typing import Any

from .base_skill import BaseDryRunSkill, dry_run_result


class _NamedDryRunSkill(BaseDryRunSkill):
    name = ""
    simulated_operation = ""

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        return dry_run_result(
            action,
            details={
                "simulated_operation": self.simulated_operation,
            },
        )


class ClickOptionDryRunSkill(_NamedDryRunSkill):
    name = "click_option"
    simulated_operation = "select_option"


class TypeTextDryRunSkill(_NamedDryRunSkill):
    name = "type_text"
    simulated_operation = "enter_text"


class SelectDropdownDryRunSkill(_NamedDryRunSkill):
    name = "select_dropdown"
    simulated_operation = "choose_dropdown_option"


class WaitDryRunSkill(_NamedDryRunSkill):
    name = "wait"
    simulated_operation = "wait"


class ClickNextDryRunSkill(_NamedDryRunSkill):
    name = "click_next"
    simulated_operation = "advance_page"


class SubmitDryRunSkill(_NamedDryRunSkill):
    name = "submit"
    simulated_operation = "submit_form"


def default_dry_run_skills() -> list[BaseDryRunSkill]:
    return [
        ClickOptionDryRunSkill(),
        TypeTextDryRunSkill(),
        SelectDropdownDryRunSkill(),
        WaitDryRunSkill(),
        ClickNextDryRunSkill(),
        SubmitDryRunSkill(),
    ]
