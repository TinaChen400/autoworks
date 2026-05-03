from __future__ import annotations

from pathlib import Path
from typing import Any

BANNED_DETAIL_REGION_TYPES = {"browser_bar", "header", "footer", "left_sidebar", "right_sidebar"}
BUSINESS_REGION_TYPES = {
    "business_content_area",
    "main_content",
    "form_area",
    "question_area",
    "card",
    "form_section",
    "question_card",
    "account_section",
    "contact_section",
    "notification_section",
    "security_section",
    "license_section",
}


def is_severely_unsafe(crop_quality: dict[str, Any], annotated_overview_exists: bool) -> bool:
    if crop_quality.get("safe_for_detail_parse", False):
        return False
    if crop_quality.get("fallback_recommendation") == "use_full_screenshot":
        return True
    if crop_quality.get("content_touching_edges") and crop_quality.get(
        "missing_question_context_possible"
    ):
        return True
    return bool(
        crop_quality.get("possible_half_cut_text_or_controls") and not annotated_overview_exists
    )


def summarize_crop_safety(
    selected_regions: list[dict[str, Any]], annotated_overview_exists: bool
) -> dict[str, Any]:
    per_region: dict[str, Any] = {}
    unsafe_region_ids: list[str] = []
    severely_unsafe_region_ids: list[str] = []
    for region in selected_regions:
        region_id = str(region.get("region_id", ""))
        quality = dict(region.get("crop_quality") or {})
        safe = bool(quality.get("safe_for_detail_parse", False))
        severe = is_severely_unsafe(quality, annotated_overview_exists)
        if not safe:
            unsafe_region_ids.append(region_id)
        if severe:
            severely_unsafe_region_ids.append(region_id)
        per_region[region_id] = {
            "safe_for_detail_parse": safe,
            "severely_unsafe": severe,
            "fallback_recommendation": quality.get("fallback_recommendation", ""),
            "crop_quality": quality.get("crop_quality", "unknown"),
            "reasons": quality.get("reasons", []),
        }
    return {
        "all_safe": not unsafe_region_ids,
        "unsafe_region_ids": unsafe_region_ids,
        "severely_unsafe_region_ids": severely_unsafe_region_ids,
        "per_region": per_region,
    }


def choose_images_for_regions(
    selected_regions: list[dict[str, Any]],
    *,
    annotated_overview_path: str,
    full_screenshot_path: str,
    prefer_annotated_crops: bool,
    include_annotated_overview_with_unsafe_crops: bool,
    annotated_overview_exists: bool,
) -> tuple[list[str], list[str], list[str], bool, bool, list[str]]:
    input_images: list[str] = []
    crop_paths: list[str] = []
    annotated_crop_paths: list[str] = []
    use_overview = False
    use_full = False
    warnings: list[str] = []

    for region in selected_regions:
        crop = str(region.get("crop_path") or "")
        annotated_crop = str(region.get("annotated_crop_path") or "")
        quality = dict(region.get("crop_quality") or {})
        safe = bool(quality.get("safe_for_detail_parse", False))
        severe = is_severely_unsafe(quality, annotated_overview_exists)
        if crop:
            crop_paths.append(crop)
        if annotated_crop:
            annotated_crop_paths.append(annotated_crop)

        preferred_crop = (
            annotated_crop if prefer_annotated_crops and Path(annotated_crop).exists() else crop
        )
        if severe:
            warnings.append(
                f"{region.get('region_id')} crop is severely unsafe; using fallback context."
            )
            if annotated_overview_exists:
                use_overview = True
            else:
                use_full = True
            continue
        if not safe and include_annotated_overview_with_unsafe_crops and annotated_overview_exists:
            use_overview = True
            warnings.append(
                f"{region.get('region_id')} crop is unsafe; pairing crop with overview."
            )
        if preferred_crop and Path(preferred_crop).exists():
            input_images.append(preferred_crop)
        elif annotated_overview_exists:
            use_overview = True
            warnings.append(
                f"{region.get('region_id')} crop file is missing; using overview."
            )
        else:
            use_full = True
            warnings.append(
                f"{region.get('region_id')} crop file is missing; using full screenshot."
            )

    if use_overview and annotated_overview_path:
        input_images.insert(0, annotated_overview_path)
    if use_full and full_screenshot_path:
        input_images.insert(0, full_screenshot_path)
    return input_images, crop_paths, annotated_crop_paths, use_overview, use_full, warnings
