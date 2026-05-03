from __future__ import annotations

from typing import Any

from modules.parse_orchestrator.schema import ParseMetrics, now_iso


def build_metrics(
    *,
    plan: dict[str, Any],
    parsed_page: dict[str, Any],
    validation_report: dict[str, Any],
    model_calls_count: int,
    elapsed_time_ms: int,
    fallback_used: bool,
    fallback_reason: str,
    warnings: list[str],
) -> ParseMetrics:
    page = dict(parsed_page.get("page") or {})
    return ParseMetrics(
        plan_id=str(plan.get("plan_id", "")),
        strategy_used=str(plan.get("selected_strategy", "")),
        parser_type_used=str(plan.get("selected_parser_type", "")),
        mode_used=str(plan.get("selected_mode", "")),
        model_calls_count=model_calls_count,
        elapsed_time_ms=elapsed_time_ms,
        validation_passed=bool(validation_report.get("valid", False)),
        final_page_type=str(page.get("page_type", "unknown")),
        final_confidence=float(page.get("confidence", 0.0) or 0.0),
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        input_images_used=[str(item) for item in plan.get("selected_input_images", [])],
        warnings=warnings,
        created_at=now_iso(),
    )

