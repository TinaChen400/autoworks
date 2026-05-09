from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.parse_orchestrator.fallback_policy import (
    BANNED_DETAIL_REGION_TYPES,
    BUSINESS_REGION_TYPES,
    choose_images_for_regions,
    summarize_crop_safety,
)
from modules.parse_orchestrator.input_loader import ANNOTATED_OVERVIEW_PATH, region_by_id
from modules.parse_orchestrator.schema import ParsePlan, StrategyDecision, new_id, now_iso


def _highest_detector(detector_scores: dict[str, Any]) -> tuple[str, float]:
    scores = {str(k): float(v or 0.0) for k, v in detector_scores.items()}
    if not scores:
        return "general", 0.0
    name = max(scores, key=scores.get)
    return name, scores[name]


def _is_ambiguous(detector_scores: dict[str, Any]) -> bool:
    values = sorted((float(v or 0.0) for v in detector_scores.values()), reverse=True)
    if not values or values[0] <= 0:
        return True
    return len(values) > 1 and abs(values[0] - values[1]) < 0.1


def _filter_detail_regions(region_ids: list[str], regions: dict[str, dict[str, Any]]) -> list[str]:
    business = [
        rid
        for rid in region_ids
        if (regions.get(rid, {}).get("region_type_hint") in BUSINESS_REGION_TYPES)
    ]
    if business:
        return business
    return [
        rid
        for rid in region_ids
        if regions.get(rid, {}).get("region_type_hint") not in BANNED_DETAIL_REGION_TYPES
    ]


def select_strategy(
    runtime_context: dict[str, Any],
    layout_index: dict[str, Any],
    config: dict[str, Any],
    *,
    mode: str | None = None,
    parser_type: str = "auto",
    output_level: str | None = None,
    max_model_calls: int | None = None,
) -> tuple[ParsePlan, StrategyDecision]:
    hints = dict(layout_index.get("layout_hints") or {})
    detector_scores = {
        str(key): float(value or 0.0)
        for key, value in dict(hints.get("detector_scores") or {}).items()
    }
    possible_page_types = [str(item) for item in hints.get("possible_page_types", [])]
    recommended = [str(item) for item in hints.get("recommended_regions_for_detail_parse", [])]
    regions = region_by_id(layout_index)
    selected_region_ids = _filter_detail_regions(recommended, regions)
    selected_regions = [regions[rid] for rid in selected_region_ids if rid in regions]

    selected_mode = mode or str(config.get("default_mode", "fake"))
    selected_output_level = output_level or config.get("output_level")
    if selected_output_level is None:
        selected_output_level = "light" if selected_mode in {"doubao", "ollama"} else "standard"
    selected_output_level = str(selected_output_level)
    if selected_output_level not in {"light", "standard"}:
        selected_output_level = "standard"
    configured_limit = int(max_model_calls or config.get("max_model_calls", 3))
    highest_name, highest_score = _highest_detector(detector_scores)
    ambiguous = _is_ambiguous(detector_scores)
    parser = parser_type if parser_type != "auto" else highest_name
    if parser not in config.get("allowed_parser_types", []):
        parser = "general"

    annotated_overview = str(layout_index.get("annotated_overview") or ANNOTATED_OVERVIEW_PATH)
    annotated_exists = Path(annotated_overview).exists()
    full_screenshot = str(
        (layout_index.get("full_screenshot") or {}).get("path")
        or runtime_context.get("screenshot_path")
        or ""
    )
    crop_safety = summarize_crop_safety(selected_regions, annotated_exists)
    warnings: list[str] = []

    if not annotated_exists:
        strategy = "full_screenshot_parse"
        parser = "general" if parser_type == "auto" else parser
        input_images = [full_screenshot] if full_screenshot else []
        use_overview = False
        use_full = True
        crop_paths = [str(r.get("crop_path") or "") for r in selected_regions if r.get("crop_path")]
        annotated_crop_paths = [
            str(r.get("annotated_crop_path") or "")
            for r in selected_regions
            if r.get("annotated_crop_path")
        ]
        reason = "Annotated overview is missing; using full screenshot."
    elif ambiguous:
        strategy = "annotated_overview_parse"
        parser = "general" if parser_type == "auto" else parser
        input_images = [annotated_overview]
        use_overview = True
        use_full = False
        crop_paths = []
        annotated_crop_paths = []
        warnings.append("Detector scores are zero or ambiguous; human review may be needed.")
        reason = "Detector scores do not clearly identify a page type."
    elif (
        parser == "form"
        and highest_name == "form"
        and highest_score >= float(config.get("minimum_detector_score_for_direct_parse", 0.5))
        and selected_regions
    ):
        severe = bool(crop_safety["severely_unsafe_region_ids"])
        if severe:
            strategy = "annotated_overview_parse" if annotated_exists else "full_screenshot_parse"
            parser = "form"
        else:
            strategy = "direct_region_parse"
        (
            input_images,
            crop_paths,
            annotated_crop_paths,
            use_overview,
            use_full,
            policy_warnings,
        ) = choose_images_for_regions(
            selected_regions,
            annotated_overview_path=annotated_overview,
            full_screenshot_path=full_screenshot,
            prefer_annotated_crops=bool(config.get("prefer_annotated_crops", True)),
            include_annotated_overview_with_unsafe_crops=bool(
                config.get("include_annotated_overview_with_unsafe_crops", True)
            ),
            annotated_overview_exists=annotated_exists,
        )
        warnings.extend(policy_warnings)
        reason = "Form detector is highest and recommended business card regions are available."
    elif selected_regions:
        strategy = "direct_region_parse"
        (
            input_images,
            crop_paths,
            annotated_crop_paths,
            use_overview,
            use_full,
            policy_warnings,
        ) = choose_images_for_regions(
            selected_regions,
            annotated_overview_path=annotated_overview,
            full_screenshot_path=full_screenshot,
            prefer_annotated_crops=bool(config.get("prefer_annotated_crops", True)),
            include_annotated_overview_with_unsafe_crops=bool(
                config.get("include_annotated_overview_with_unsafe_crops", True)
            ),
            annotated_overview_exists=annotated_exists,
        )
        warnings.extend(policy_warnings)
        reason = "Recommended content regions are available."
    else:
        strategy = "annotated_overview_parse"
        parser = "general" if parser_type == "auto" else parser
        input_images = [annotated_overview]
        use_overview = True
        use_full = False
        crop_paths = []
        annotated_crop_paths = []
        reason = "No recommended detail regions; using annotated overview."

    max_calls = max(1, min(configured_limit, len(input_images) or 1))
    decision = StrategyDecision(
        strategy=strategy,
        parser_type=parser,
        mode=selected_mode,
        region_ids=selected_region_ids,
        input_images=input_images,
        fallback_strategy="full_screenshot_parse",
        max_model_calls=max_calls,
        reason=reason,
        warnings=warnings,
    )
    plan = ParsePlan(
        plan_id=new_id("plan"),
        task_id=str(runtime_context.get("task_id", "")),
        task_type_hint=str(runtime_context.get("task_type", "")),
        selected_strategy=strategy,
        selected_parser_type=parser,
        selected_mode=selected_mode,
        selected_output_level=selected_output_level,
        selected_input_images=input_images,
        selected_region_ids=selected_region_ids,
        selected_crop_paths=crop_paths,
        selected_annotated_crop_paths=annotated_crop_paths,
        use_annotated_overview=use_overview,
        use_full_screenshot=use_full,
        reason=reason,
        detector_scores=detector_scores,
        possible_page_types=possible_page_types,
        max_model_calls=max_calls,
        fallback_strategy="full_screenshot_parse",
        crop_safety_summary=crop_safety,
        created_at=now_iso(),
    )
    return plan, decision

