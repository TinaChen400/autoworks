from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from modules.parse_orchestrator.parse_plan_store import load_if_exists

PARSED_PAGE_PATH = Path("runtime_state/latest_parsed_page.json")
VALIDATION_REPORT_PATH = Path("runtime_state/latest_vision_validation_report.json")
MULTI_REGION_MVP_WARNING = (
    "Multi-region parse is planned but MVP currently parses the first selected input image only."
)


@dataclass
class VisionRunResult:
    parsed_page: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)
    model_calls_count: int = 0
    validation_passed: bool = False
    warnings: list[str] = field(default_factory=list)
    error: str = ""


def run_vision_parser(plan: dict[str, Any]) -> VisionRunResult:
    warnings = []
    selected_input_images = [str(item) for item in plan.get("selected_input_images", [])]
    if len(selected_input_images) > 1:
        warnings.append(MULTI_REGION_MVP_WARNING)
    mode = str(plan.get("selected_mode", "fake"))
    parser_type = str(plan.get("selected_parser_type", "general"))
    input_image = selected_input_images[0] if selected_input_images else None
    try:
        from modules.vision_parser.parser import parse_latest_runtime_context
    except ImportError:
        if mode == "fake":
            return _fake_result(plan, warnings + ["Please implement or merge vision_parser first."])
        return _run_vision_parser_subprocess(plan, mode, warnings)

    try:
        parsed = parse_latest_runtime_context(
            mode=mode,
            parser_type=parser_type,
            input_image=input_image,
        )
    except Exception as exc:  # noqa: BLE001 - preserve orchestrator outputs on parser failure.
        validation = load_if_exists(VALIDATION_REPORT_PATH)
        return VisionRunResult(
            parsed_page=load_if_exists(PARSED_PAGE_PATH),
            validation_report=validation,
            model_calls_count=1,
            validation_passed=bool(validation.get("valid", False)),
            warnings=warnings,
            error=str(exc),
        )
    validation = load_if_exists(VALIDATION_REPORT_PATH)
    return VisionRunResult(
        parsed_page=parsed or load_if_exists(PARSED_PAGE_PATH),
        validation_report=validation,
        model_calls_count=1,
        validation_passed=bool(validation.get("valid", False)),
        warnings=warnings,
    )


def _run_vision_parser_subprocess(
    plan: dict[str, Any], mode: str, warnings: list[str]
) -> VisionRunResult:
    command = [
        sys.executable,
        "-m",
        "modules.vision_parser.parser",
        "--mode",
        mode,
        "--parser-type",
        str(plan.get("selected_parser_type", "general")),
    ]
    selected_input_images = [str(item) for item in plan.get("selected_input_images", [])]
    if selected_input_images:
        command.extend(["--input-image", selected_input_images[0]])
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        if mode == "fake":
            return _fake_result(plan, warnings + ["Please implement or merge vision_parser first."])
        return VisionRunResult(
            warnings=warnings,
            error="Please implement or merge vision_parser first.",
        )
    validation = load_if_exists(VALIDATION_REPORT_PATH)
    error = ""
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or "").strip()
    return VisionRunResult(
        parsed_page=load_if_exists(PARSED_PAGE_PATH),
        validation_report=validation,
        model_calls_count=1,
        validation_passed=bool(validation.get("valid", False)) and completed.returncode == 0,
        warnings=warnings,
        error=error,
    )


def _fake_result(plan: dict[str, Any], warnings: list[str]) -> VisionRunResult:
    parsed = {
        "parse_id": f"fake_{plan.get('plan_id', '')}",
        "task_id": str(plan.get("task_id", "")),
        "page": {
            "page_type": "unknown",
            "language": "unknown",
            "page_status": "unknown",
            "confidence": 0.1,
        },
        "questions": [
            {
                "question_id": "q1",
                "region_id": (plan.get("selected_region_ids") or [""])[0],
                "element_id": "",
                "question_type": "unknown",
                "question_stem": {
                    "text": "",
                    "bbox_norm": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0},
                },
                "instructions": [],
                "answer_options": [],
                "input_fields": [],
                "media": [],
                "matrix": None,
                "confidence": 0.1,
                "requires_human_review": plan.get("selected_strategy") == "manual_review_required",
            }
        ],
        "navigation_buttons": [],
        "uncertainties": [
            {
                "type": "fake_mode",
                "message": "Fake parse generated by parse_orchestrator fallback.",
                "related_region_ids": plan.get("selected_region_ids", []),
            }
        ],
    }
    return VisionRunResult(
        parsed_page=parsed,
        validation_report={"valid": True, "errors": []},
        model_calls_count=0,
        validation_passed=True,
        warnings=warnings,
    )
