from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from modules.parse_orchestrator.parse_plan_store import load_if_exists
from modules.parse_orchestrator.schema import new_id

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
    output_level = str(plan.get("selected_output_level") or ("light" if mode == "doubao" else "standard"))
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
            output_level=output_level,
            input_image=input_image,
        )
    except Exception as exc:  # noqa: BLE001 - preserve orchestrator outputs on parser failure.
        error = str(exc)
        validation = _failure_validation_report(load_if_exists(VALIDATION_REPORT_PATH), error)
        return VisionRunResult(
            parsed_page=_failure_parsed_page(plan, input_image, parser_type, error),
            validation_report=validation,
            model_calls_count=1,
            validation_passed=False,
            warnings=warnings,
            error=error,
        )
    validation = load_if_exists(VALIDATION_REPORT_PATH)
    error = "" if isinstance(parsed, dict) else "Parser returned no parsed page."
    if error:
        validation = _failure_validation_report(validation, error)
    return VisionRunResult(
        parsed_page=parsed if isinstance(parsed, dict) else _failure_parsed_page(
            plan,
            input_image,
            parser_type,
            error,
        ),
        validation_report=validation,
        model_calls_count=1,
        validation_passed=bool(validation.get("validation_passed", validation.get("valid", False))) and not error,
        warnings=warnings,
        error=error,
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
        "--output-level",
        str(plan.get("selected_output_level") or ("light" if mode == "doubao" else "standard")),
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
        if not error:
            error = f"Vision parser subprocess failed with exit code {completed.returncode}."
        validation = _failure_validation_report(validation, error)
    return VisionRunResult(
        parsed_page=load_if_exists(PARSED_PAGE_PATH)
        if completed.returncode == 0
        else _failure_parsed_page(
            plan,
            selected_input_images[0] if selected_input_images else None,
            str(plan.get("selected_parser_type", "general")),
            error,
        ),
        validation_report=validation,
        model_calls_count=1,
        validation_passed=bool(validation.get("validation_passed", validation.get("valid", False))) and completed.returncode == 0,
        warnings=warnings,
        error=error,
    )


def _failure_parsed_page(
    plan: dict[str, Any],
    input_image: str | None,
    parser_type: str,
    message: str,
) -> dict[str, Any]:
    return {
        "parse_id": new_id("parse_failed"),
        "task_id": str(plan.get("task_id", "")),
        "page": {
            "page_type": "unknown",
            "language": "unknown",
            "page_status": "parse_failed",
            "confidence": 0.0,
        },
        "questions": [],
        "navigation_buttons": [],
        "uncertainties": [
            {
                "type": "parse_failed",
                "message": message,
                "related_question_id": "",
            }
        ],
        "visual_elements": [],
        "metadata": {
            "source": "parse_orchestrator",
            "parse_failed": True,
            "input_image_used": input_image or "",
            "selected_parser_type": parser_type,
        },
    }


def _failure_validation_report(
    validation_report: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    if validation_report and validation_report.get("validation_passed") is False:
        return validation_report
    return {
        "validation_passed": False,
        "errors": [
            {
                "code": "parse_failed",
                "path": "$",
                "message": message,
            }
        ],
        "warnings": [],
        "info": [],
        "normalization_applied": [],
    }


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
