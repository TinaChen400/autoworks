from __future__ import annotations

from typing import Any

from .base_skill import BaseDryRunSkill, dry_run_result


class WaitAtomicSkill(BaseDryRunSkill):
    name = "wait"

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        return dry_run_result(
            action,
            details={
                "layer": "atomic",
                "simulated_operation": "wait",
            },
        )


def wait_atomic_skills() -> list[BaseDryRunSkill]:
    return [WaitAtomicSkill()]
