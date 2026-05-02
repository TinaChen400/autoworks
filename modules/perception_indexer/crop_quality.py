from __future__ import annotations

from modules.perception_indexer.schema import BBox, CropQuality, Element, TextBlock, bbox_from_dict


def expand_and_clamp_crop(
    bbox: BBox,
    image_width: int,
    image_height: int,
    margin_percent: float = 0.08,
    min_margin_px: int = 40,
) -> BBox:
    margin_x = max(min_margin_px, int(bbox.width * margin_percent))
    margin_y = max(min_margin_px, int(bbox.height * margin_percent))
    x = max(0, bbox.x - margin_x)
    y = max(0, bbox.y - margin_y)
    right = min(image_width, bbox.right + margin_x)
    bottom = min(image_height, bbox.bottom + margin_y)
    return BBox(x=x, y=y, width=max(1, right - x), height=max(1, bottom - y))


def compute_crop_quality(
    crop_bbox: BBox,
    region_bbox: BBox,
    image_width: int,
    image_height: int,
    elements: list[Element],
    text_blocks: list[TextBlock],
    is_card_region: bool = False,
) -> CropQuality:
    quality = CropQuality(crop_quality="good", safe_for_detail_parse=True, crop_complete_estimate=0.85)
    edge_margin = 12
    relevant_elements = [
        element for element in elements if _center_inside(bbox_from_dict(element.bbox_raw), crop_bbox)
    ]
    relevant_text = [
        text_block for text_block in text_blocks if _center_inside(bbox_from_dict(text_block.bbox_raw), crop_bbox)
    ]

    if crop_bbox.width < 220 or crop_bbox.height < 160:
        _mark_unsafe(quality, "Crop is too narrow or too small for reliable detail parsing.")
    if crop_bbox.x <= 0 or crop_bbox.y <= 0 or crop_bbox.right >= image_width or crop_bbox.bottom >= image_height:
        quality.content_touching_edges = True
        quality.reasons.append("Crop is clamped to the full screenshot boundary.")

    for element in relevant_elements:
        box = bbox_from_dict(element.bbox_raw)
        touched = _touches_edges(box, crop_bbox, edge_margin)
        if any(touched):
            quality.content_touching_edges = True
            quality.possible_half_cut_text_or_controls = True
            _set_edge_flags(quality, touched)

    for text_block in relevant_text:
        box = bbox_from_dict(text_block.bbox_raw)
        touched = _touches_edges(box, crop_bbox, edge_margin)
        if touched[0] or touched[1]:
            quality.possible_half_cut_text_or_controls = True
            _mark_unsafe(quality, "OCR text touches the top or bottom crop edge.")
        _set_edge_flags(quality, touched)

    element_types = {element.element_type_hint for element in relevant_elements}
    has_label_text = any(text.text.strip() for text in relevant_text)
    if {"checkbox_like", "radio_like", "button_like"} & element_types and not has_label_text:
        quality.missing_question_context_possible = True
        quality.missing_answer_options_possible = True
        _mark_unsafe(quality, "Option-like elements are present without nearby question or instruction text.")
    if "input_like" in element_types and not has_label_text:
        quality.missing_input_fields_possible = True
        _mark_unsafe(quality, "Input-like elements are present without nearby label text.")
    if "draggable_like" in element_types and "drop_zone_like" not in element_types:
        _mark_unsafe(quality, "Draggable-like elements are present without target-zone-like elements.")
    if "drop_zone_like" in element_types and "draggable_like" not in element_types:
        _mark_unsafe(quality, "Target-zone-like elements are present without draggable-like elements.")
    if "input_like" in element_types and len(relevant_elements) >= 3:
        has_action = bool({"button_like", "dropdown_like"} & element_types)
        if not has_label_text or not has_action:
            quality.missing_navigation_possible = not has_action
            reason = "Form-like crop may be missing a section title or navigation/action button."
            if is_card_region and has_label_text and relevant_elements:
                if reason not in quality.reasons:
                    quality.reasons.append(reason)
            else:
                _mark_unsafe(quality, reason)

    near_boundary_count = sum(
        1 for element in relevant_elements if any(_touches_edges(bbox_from_dict(element.bbox_raw), crop_bbox, 20))
    )
    if near_boundary_count >= 3:
        _mark_unsafe(quality, "Many detected elements touch or nearly touch the crop boundary.")

    if quality.possible_half_cut_text_or_controls:
        _mark_unsafe(quality, "Crop may include partial controls or half-cut text.")
    if not quality.safe_for_detail_parse:
        quality.crop_quality = "unsafe"
        quality.crop_complete_estimate = min(quality.crop_complete_estimate, 0.45)
        quality.fallback_recommendation = _fallback_for(quality, crop_bbox, region_bbox)
    return quality


def _center_inside(box: BBox, outer: BBox) -> bool:
    center_x = box.x + box.width // 2
    center_y = box.y + box.height // 2
    return outer.x <= center_x <= outer.right and outer.y <= center_y <= outer.bottom


def _touches_edges(box: BBox, crop: BBox, margin: int) -> tuple[bool, bool, bool, bool]:
    top = box.y - crop.y <= margin
    bottom = crop.bottom - box.bottom <= margin
    left = box.x - crop.x <= margin
    right = crop.right - box.right <= margin
    return top, bottom, left, right


def _set_edge_flags(quality: CropQuality, touched: tuple[bool, bool, bool, bool]) -> None:
    top, bottom, left, right = touched
    quality.content_touching_top_edge = quality.content_touching_top_edge or top
    quality.content_touching_bottom_edge = quality.content_touching_bottom_edge or bottom
    quality.content_touching_left_edge = quality.content_touching_left_edge or left
    quality.content_touching_right_edge = quality.content_touching_right_edge or right
    quality.content_touching_edges = quality.content_touching_edges or any(touched)


def _mark_unsafe(quality: CropQuality, reason: str) -> None:
    quality.safe_for_detail_parse = False
    if reason not in quality.reasons:
        quality.reasons.append(reason)


def _fallback_for(quality: CropQuality, crop_bbox: BBox, region_bbox: BBox) -> str:
    if crop_bbox.width <= region_bbox.width + 80 or crop_bbox.height <= region_bbox.height + 80:
        return "expand_crop"
    if quality.content_touching_edges:
        return "use_full_screenshot"
    return "use_annotated_overview"
