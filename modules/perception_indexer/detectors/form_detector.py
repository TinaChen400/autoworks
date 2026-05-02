from __future__ import annotations

from modules.perception_indexer.detectors.base import DetectorResult

FORM_REGION_HINTS = {
    "card",
    "form_section",
    "account_section",
    "contact_section",
    "notification_section",
    "security_section",
    "license_section",
}


def run_form_detector(regions, elements, text_blocks) -> DetectorResult:
    card_regions = [
        region
        for region in regions
        if region.region_type_hint in FORM_REGION_HINTS
        and (
            region.metadata.get("is_true_business_card")
            or region.metadata.get("source") == "element_vertical_clustering"
        )
    ]
    input_like = [
        element
        for element in elements
        if element.element_type_hint in {"input_like", "dropdown_like", "button_like"}
    ]
    section_titles = [
        text_block
        for text_block in text_blocks
        if text_block.metadata.get("text_role") == "section_title"
    ]
    score = 0.0
    if card_regions:
        score += 0.55
    if len(card_regions) >= 3:
        score += 0.20
    if len(input_like) >= 3:
        score += 0.15
    if section_titles:
        score += 0.10
    return DetectorResult(
        detector_name="form",
        score=round(min(1.0, score), 4),
        possible_page_type="form",
        region_ids=[region.region_id for region in card_regions],
        element_ids=[element.element_id for element in input_like],
        text_ids=[text_block.text_id for text_block in section_titles],
        metadata={
            "card_region_count": len(card_regions),
            "input_like_count": len(input_like),
            "section_title_count": len(section_titles),
        },
    )
