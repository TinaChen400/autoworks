from __future__ import annotations

from modules.perception_indexer.schema import (
    BBox,
    Element,
    LayoutHints,
    Region,
    Relationship,
    TextBlock,
    bbox_from_dict,
    box_contains,
)


CARD_HINTS = {
    "card",
    "form_section",
    "question_card",
    "account_section",
    "contact_section",
    "notification_section",
    "security_section",
    "license_section",
}

REGION_PARENT_RANK = {
    "model_input_region": 0,
    "browser_viewport": 1,
    "web_viewport": 2,
    "business_content_area": 3,
    "main_content": 3,
    "header": 3,
    "footer": 3,
    "left_sidebar": 3,
    "right_sidebar": 3,
    "card": 4,
    "form_section": 4,
    "question_card": 4,
    "account_section": 4,
    "contact_section": 4,
    "notification_section": 4,
    "security_section": 4,
    "license_section": 4,
}


def assign_elements_to_smallest_regions(regions: list[Region], elements: list[Element]) -> None:
    for region in regions:
        region.element_ids.clear()
    for element in elements:
        element.region_id = _find_best_containing_region(regions, bbox_from_dict(element.bbox_raw)).region_id
    attach_elements_to_regions(regions, elements)


def attach_elements_to_regions(regions: list[Region], elements: list[Element]) -> None:
    by_region = {region.region_id: region for region in regions}
    for element in elements:
        if element.region_id in by_region:
            by_region[element.region_id].element_ids.append(element.element_id)


def attach_text_to_regions(regions: list[Region], text_blocks: list[TextBlock]) -> None:
    for text_block in text_blocks:
        text_box = bbox_from_dict(text_block.bbox_raw)
        best_region = _find_smallest_containing_region(regions, text_box)
        if best_region:
            text_block.associated_region_id = best_region.region_id
            best_region.text_ids.append(text_block.text_id)


def build_region_relationships(
    regions: list[Region],
    relationship_id,
) -> list[Relationship]:
    relationships: list[Relationship] = []
    for child in regions:
        child_box = bbox_from_dict(child.bbox_raw)
        parent = _find_parent_region(regions, child, child_box)
        if parent:
            child.metadata["parent_region_id"] = parent.region_id
            relationships.append(
                Relationship(
                    relationship_id=relationship_id(),
                    relationship_type="region_contains_region",
                    source_id=parent.region_id,
                    target_id=child.region_id,
                    confidence=min(child.confidence, parent.confidence),
                )
            )
    return relationships


def build_element_region_relationships(
    regions: list[Region],
    elements: list[Element],
    relationship_id,
) -> list[Relationship]:
    relationships: list[Relationship] = []
    region_ids = {region.region_id for region in regions}
    for element in elements:
        if element.region_id in region_ids:
            relationship_type = "element_in_region"
            region = next((item for item in regions if item.region_id == element.region_id), None)
            if region and region.region_type_hint in CARD_HINTS:
                relationship_type = (
                    "section_contains_field"
                    if element.element_type_hint in {"input_like", "dropdown_like"}
                    else "card_contains_element"
                )
            relationships.append(
                Relationship(
                    relationship_id=relationship_id(),
                    relationship_type=relationship_type,
                    source_id=element.element_id,
                    target_id=element.region_id,
                    confidence=element.confidence,
                )
            )
    return relationships


def infer_layout_hints(regions: list[Region], elements: list[Element]) -> LayoutHints:
    input_count = sum(1 for element in elements if element.element_type_hint == "input_like")
    button_count = sum(1 for element in elements if element.element_type_hint == "button_like")
    image_count = sum(1 for element in elements if element.element_type_hint in {"image_like", "card_like"})
    has_sidebar = any(region.region_type_hint == "left_sidebar" for region in regions)
    x_centers = [bbox_from_dict(element.bbox_raw).x + bbox_from_dict(element.bbox_raw).width // 2 for element in elements]
    two_column = bool(x_centers) and len({center // 300 for center in x_centers}) >= 2
    possible_types: list[str] = []
    if input_count >= 3:
        possible_types.append("form")
    if button_count >= 2 or input_count >= 1:
        possible_types.append("survey")
    if image_count >= 1:
        possible_types.append("image_task")
    card_regions = [
        region
        for region in regions
        if region.region_type_hint in CARD_HINTS
        and region.metadata.get("removed") is not True
        and (region.metadata.get("is_true_business_card") or region.metadata.get("source") == "element_vertical_clustering")
    ]
    web_viewport = next((region for region in regions if region.region_type_hint == "web_viewport"), None)
    business = next((region for region in regions if region.region_type_hint == "main_content"), None)
    recommended = [region.region_id for region in card_regions]
    if not recommended:
        recommended = [
            region.region_id
            for region in regions
            if region.region_type_hint in {"main_content", "form_area", "question_area", "web_viewport"}
        ][:4]
    if not recommended:
        broad_fallback = [
            region.region_id
            for region in regions
            if region.region_type_hint in {"main_content", "form_area", "question_area", "web_viewport"}
        ][:4]
        recommended = broad_fallback
    return LayoutHints(
        has_many_input_like_elements=input_count >= 3,
        has_many_button_like_elements=button_count >= 3,
        has_large_image_area=image_count >= 1,
        has_left_sidebar=has_sidebar,
        has_two_column_layout=two_column,
        has_grid_layout=_has_grid(elements),
        has_table_like_structure=_has_grid(elements) and input_count >= 4,
        has_possible_drag_drop_layout=any(
            element.element_type_hint in {"draggable_like", "drop_zone_like"} for element in elements
        ),
        has_possible_form_layout=input_count >= 3,
        has_possible_survey_layout=button_count >= 1 or input_count >= 1,
        web_viewport_region_id=web_viewport.region_id if web_viewport else "",
        main_business_region_id=business.region_id if business else "",
        card_region_ids=[region.region_id for region in card_regions],
        business_card_region_ids=[region.region_id for region in card_regions],
        true_section_title_texts=[
            str(region.metadata.get("title_text", ""))
            for region in card_regions
            if region.metadata.get("title_text")
        ],
        false_card_candidates_removed=[],
        form_section_region_ids=[
            region.region_id
            for region in card_regions
            if region.region_type_hint.endswith("_section") or region.region_type_hint == "form_section"
        ],
        possible_page_types=possible_types or ["unknown"],
        recommended_regions_for_detail_parse=recommended,
    )


def _find_smallest_containing_region(regions: list[Region], bbox: BBox) -> Region | None:
    matches = []
    for region in regions:
        region_box = bbox_from_dict(region.bbox_raw)
        if (
            bbox.x >= region_box.x
            and bbox.y >= region_box.y
            and bbox.right <= region_box.right
            and bbox.bottom <= region_box.bottom
        ):
            matches.append(region)
    if not matches:
        return None
    return min(matches, key=lambda region: region.bbox_raw["width"] * region.bbox_raw["height"])


def _find_best_containing_region(regions: list[Region], bbox: BBox) -> Region:
    useful_matches = []
    broad_matches = []
    for region in regions:
        region_box = bbox_from_dict(region.bbox_raw)
        if box_contains(region_box, bbox):
            if region.region_type_hint in CARD_HINTS or region.region_type_hint == "web_viewport":
                useful_matches.append(region)
            else:
                broad_matches.append(region)
    matches = useful_matches or broad_matches or regions
    return min(matches, key=lambda region: region.bbox_raw["width"] * region.bbox_raw["height"])


def _find_parent_region(regions: list[Region], child: Region, child_box: BBox) -> Region | None:
    candidates = []
    child_rank = REGION_PARENT_RANK.get(child.region_type_hint, 99)
    for region in regions:
        if region.region_id == child.region_id:
            continue
        parent_rank = REGION_PARENT_RANK.get(region.region_type_hint, 99)
        if parent_rank >= child_rank:
            continue
        region_box = bbox_from_dict(region.bbox_raw)
        if box_contains(region_box, child_box):
            candidates.append(region)
    if not candidates:
        return None
    return min(candidates, key=lambda region: region.bbox_raw["width"] * region.bbox_raw["height"])


def _has_grid(elements: list[Element]) -> bool:
    if len(elements) < 6:
        return False
    rows: dict[int, int] = {}
    cols: dict[int, int] = {}
    for element in elements:
        box = bbox_from_dict(element.bbox_raw)
        rows[box.y // 40] = rows.get(box.y // 40, 0) + 1
        cols[box.x // 80] = cols.get(box.x // 80, 0) + 1
    return max(rows.values(), default=0) >= 3 and max(cols.values(), default=0) >= 3
