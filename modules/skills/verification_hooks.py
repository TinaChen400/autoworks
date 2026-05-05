from __future__ import annotations

from typing import Any


def _verification_result(
    hook: str,
    action: dict[str, Any],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "action_id": action.get("action_id", ""),
        "skill": hook,
        "status": "pending",
        "dry_run": True,
        "target": action.get("target", {}) if isinstance(action.get("target"), dict) else {},
        "params": action.get("params", {}) if isinstance(action.get("params"), dict) else {},
        "details": {
            "layer": "verification",
            "simulated": True,
            **(details or {}),
        },
    }


def verify_option_selected(action: dict[str, Any]) -> dict[str, Any]:
    return _verification_result("verify_option_selected", action)


def verify_text_entered(action: dict[str, Any]) -> dict[str, Any]:
    return _verification_result("verify_text_entered", action)


def verify_navigation_possible(action: dict[str, Any]) -> dict[str, Any]:
    return _verification_result("verify_navigation_possible", action)
