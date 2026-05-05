from __future__ import annotations

from typing import Any

from .base_skill import BaseDryRunSkill
from .dry_run_skills import default_dry_run_skills


class SkillRegistry:
    def __init__(self, skills: list[BaseDryRunSkill] | None = None) -> None:
        self._skills: dict[str, BaseDryRunSkill] = {}
        for skill in skills or []:
            self.register(skill)

    def register(self, skill: BaseDryRunSkill) -> None:
        if not skill.name:
            raise ValueError("Skill name is required.")
        self._skills[skill.name] = skill

    def get(self, name: str) -> BaseDryRunSkill | None:
        return self._skills.get(name)

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        skill_name = str(action.get("skill") or "")
        skill = self.get(skill_name)
        if skill is None:
            return {
                "action_id": action.get("action_id", ""),
                "skill": skill_name,
                "status": "failed",
                "dry_run": True,
                "failure": {
                    "code": "unknown_skill",
                    "message": f"No dry-run skill registered for '{skill_name}'.",
                },
            }
        return skill.execute(action)

    def names(self) -> list[str]:
        return sorted(self._skills)


def default_skill_registry() -> SkillRegistry:
    return SkillRegistry(default_dry_run_skills())

