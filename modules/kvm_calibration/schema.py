from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


REQUIRED_FRAME_KEYS = ("x", "y", "width", "height")
REQUIRED_SIZE_KEYS = ("width", "height")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_kvm_calibration(
    runtime_context: dict[str, Any],
    resolved_action_plan: dict[str, Any],
    action_executor_preview: dict[str, Any],
    calibrated: bool,
    model: dict[str, Any],
    validated_points: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    anchor_frame = model.get("anchor_frame") if isinstance(model.get("anchor_frame"), dict) else {}
    controlled_screen = (
        model.get("controlled_screen") if isinstance(model.get("controlled_screen"), dict) else {}
    )
    scale = model.get("scale") if isinstance(model.get("scale"), dict) else {}
    offset = model.get("offset") if isinstance(model.get("offset"), dict) else {}

    return {
        "kvm_calibration_id": f"kvm_calibration_{uuid4().hex}",
        "task_id": runtime_context.get("task_id") or resolved_action_plan.get("task_id") or "",
        "session_id": resolved_action_plan.get("session_id")
        or action_executor_preview.get("session_id")
        or "",
        "source_resolved_action_plan_id": resolved_action_plan.get("resolved_action_plan_id", ""),
        "source_action_executor_preview_id": action_executor_preview.get(
            "action_executor_preview_id",
            "",
        ),
        "calibrated": calibrated,
        "anchor_frame": anchor_frame,
        "controller_screen_anchor": anchor_frame,
        "controlled_screen": controlled_screen,
        "model_input_region": model.get("model_input_region", {}),
        "raw_screenshot": model.get("raw_screenshot", {}),
        "coordinate_policy": runtime_context.get("coordinate_policy", {}),
        "scale": {"x": scale.get("x", 0), "y": scale.get("y", 0)},
        "offset": {"x": offset.get("x", 0), "y": offset.get("y", 0)},
        "validated_points": validated_points,
        "warnings": warnings,
        "created_at": utc_now_iso(),
    }


def calibration_issue(issue_type: str, message: str, **details: Any) -> dict[str, Any]:
    issue = {"type": issue_type, "message": message}
    issue.update(details)
    return issue
