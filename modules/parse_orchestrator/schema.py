from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

SUPPORTED_STRATEGIES = {
    "direct_region_parse",
    "annotated_overview_parse",
    "full_screenshot_parse",
    "quick_scene_scan_then_parse",
    "fallback_full_screenshot_parse",
    "manual_review_required",
}

SUPPORTED_PARSER_TYPES = {
    "form",
    "survey",
    "image_task",
    "drag_drop",
    "matrix",
    "modal",
    "general",
    "scene_scan",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass
class StrategyDecision:
    strategy: str
    parser_type: str
    mode: str
    region_ids: list[str] = field(default_factory=list)
    input_images: list[str] = field(default_factory=list)
    fallback_strategy: str = "full_screenshot_parse"
    max_model_calls: int = 1
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsePlan:
    plan_id: str
    task_id: str
    task_type_hint: str
    selected_strategy: str
    selected_parser_type: str
    selected_mode: str
    selected_output_level: str
    selected_input_images: list[str]
    selected_region_ids: list[str]
    selected_crop_paths: list[str]
    selected_annotated_crop_paths: list[str]
    use_annotated_overview: bool
    use_full_screenshot: bool
    reason: str
    detector_scores: dict[str, float]
    possible_page_types: list[str]
    max_model_calls: int
    fallback_strategy: str
    crop_safety_summary: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParseMetrics:
    plan_id: str
    strategy_used: str
    parser_type_used: str
    mode_used: str
    model_calls_count: int
    elapsed_time_ms: int
    validation_passed: bool
    final_page_type: str
    final_confidence: float
    fallback_used: bool
    fallback_reason: str
    input_images_used: list[str]
    warnings: list[str]
    created_at: str
    local_fast_parse_used: bool = False
    local_parse_confidence: float = 0.0
    remote_fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrchestratedParse:
    orchestration_id: str
    plan_id: str
    task_id: str
    parsed_page_path: str
    parsed_page: dict[str, Any]
    parse_plan: dict[str, Any]
    parse_metrics: dict[str, Any]
    validation_report_path: str
    validation_report: dict[str, Any]
    requires_human_review: bool
    warnings: list[str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

