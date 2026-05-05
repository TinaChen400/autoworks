from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseDryRunSkill(ABC):
    """Base class for skills that simulate actions without OS interaction."""

    name: str

    @abstractmethod
    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        """Return a structured dry-run result for one action."""


def dry_run_result(
    action: dict[str, Any],
    status: str = "success",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "action_id": action.get("action_id", ""),
        "skill": action.get("skill", ""),
        "status": status,
        "dry_run": True,
        "target": action.get("target", {}) if isinstance(action.get("target"), dict) else {},
        "params": action.get("params", {}) if isinstance(action.get("params"), dict) else {},
        "details": details or {},
    }

