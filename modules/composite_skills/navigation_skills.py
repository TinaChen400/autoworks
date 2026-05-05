from __future__ import annotations

from typing import Any

from modules.skills.base_skill import BaseDryRunSkill
from modules.skills.verification_hooks import verify_navigation_possible

from .schema import click_steps, composite_result


class ClickNextSkill(BaseDryRunSkill):
    name = "click_next"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        steps = [verify_navigation_possible(action), *click_steps(action)]
        return composite_result(
            action,
            self.name,
            steps,
            {"simulated_operation": "advance_page"},
        )


class SubmitPageSkill(BaseDryRunSkill):
    name = "submit_page"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        steps = [verify_navigation_possible(action), *click_steps(action)]
        return composite_result(
            action,
            self.name,
            steps,
            {"simulated_operation": "submit_form"},
        )


class SubmitSkill(SubmitPageSkill):
    name = "submit"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        result = super().execute(action)
        result["composite_skill"] = "submit_page"
        result["details"]["routed_from"] = "submit"
        result["details"]["simulated_operation"] = "submit_form"
        return result


def navigation_composite_skills() -> list[BaseDryRunSkill]:
    return [
        ClickNextSkill(),
        SubmitPageSkill(),
        SubmitSkill(),
    ]
