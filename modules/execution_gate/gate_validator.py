from __future__ import annotations

from typing import Any

from .schema import VALID_GATE_STATUSES


def validate_execution_gate(gate: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    status = gate.get("status")
    execution_allowed = gate.get("execution_allowed")
    block_reasons = gate.get("block_reasons")
    executable_actions = gate.get("executable_actions")

    if status not in VALID_GATE_STATUSES:
        issues.append({"type": "invalid_status", "status": status})

    if not isinstance(execution_allowed, bool):
        issues.append({"type": "invalid_execution_allowed"})

    if not isinstance(block_reasons, list):
        issues.append({"type": "invalid_block_reasons"})
        block_reasons = []

    if not isinstance(executable_actions, list):
        issues.append({"type": "invalid_executable_actions"})
        executable_actions = []

    if execution_allowed is True and status != "allowed":
        issues.append({"type": "allowed_status_mismatch"})
    if execution_allowed is False and status != "blocked":
        issues.append({"type": "blocked_status_mismatch"})
    if execution_allowed is True and block_reasons:
        issues.append({"type": "allowed_gate_has_block_reasons"})
    if execution_allowed is False and not block_reasons:
        issues.append({"type": "blocked_gate_missing_block_reason"})
    if execution_allowed is False and executable_actions:
        issues.append({"type": "blocked_gate_has_executable_actions"})

    return {
        "validation_passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "execution_allowed": (
            bool(execution_allowed) if isinstance(execution_allowed, bool) else False
        ),
        "status": status,
        "block_reason_count": len(block_reasons),
        "executable_action_count": len(executable_actions),
    }
