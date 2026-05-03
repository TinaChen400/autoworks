from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from modules.perception_indexer.schema import BBox, Element, Region, TextBlock, bbox_from_dict

COLORS = {
    "region": "#2563eb",
    "card": "#dc2626",
    "element": "#16a34a",
    "text": "#ea580c",
}

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


def save_annotated_overview(
    image: Image.Image,
    regions: list[Region],
    elements: list[Element],
    text_blocks: list[TextBlock],
    output_path: str | Path,
    annotate_regions: bool = True,
    annotate_elements: bool = True,
    annotate_text_blocks: bool = True,
    show_browser_elements: bool = False,
    show_low_confidence_elements: bool = False,
    min_element_confidence_for_annotation: float = 0.35,
) -> Path:
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    if annotate_regions:
        for region in regions:
            color = COLORS["card"] if region.region_type_hint in CARD_HINTS else COLORS["region"]
            label = _region_label(region)
            _draw_labeled_box(draw, bbox_from_dict(region.bbox_raw), label, color, width=3)
    if annotate_elements:
        visible_region_ids = _visible_region_ids(regions, show_browser_elements)
        for element in elements:
            if element.region_id not in visible_region_ids:
                continue
            if not show_low_confidence_elements and element.confidence < min_element_confidence_for_annotation:
                continue
            _draw_labeled_box(draw, bbox_from_dict(element.bbox_raw), element.element_id, COLORS["element"], width=2)
    if annotate_text_blocks:
        for text_block in text_blocks:
            _draw_labeled_box(draw, bbox_from_dict(text_block.bbox_raw), text_block.text_id, COLORS["text"], width=1)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    annotated.save(destination)
    return destination


def save_annotated_crop(
    image: Image.Image,
    crop_bbox: BBox,
    region: Region,
    elements: list[Element],
    text_blocks: list[TextBlock],
    output_path: str | Path,
) -> Path:
    crop = image.crop((crop_bbox.x, crop_bbox.y, crop_bbox.right, crop_bbox.bottom))
    draw = ImageDraw.Draw(crop)
    region_box = _translate(bbox_from_dict(region.bbox_raw), crop_bbox)
    _draw_labeled_box(draw, region_box, region.region_id, COLORS["region"], width=3)
    for element in elements:
        element_box = bbox_from_dict(element.bbox_raw)
        if _center_inside(element_box, crop_bbox):
            _draw_labeled_box(draw, _translate(element_box, crop_bbox), element.element_id, COLORS["element"], width=2)
    for text_block in text_blocks:
        text_box = bbox_from_dict(text_block.bbox_raw)
        if _center_inside(text_box, crop_bbox):
            _draw_labeled_box(draw, _translate(text_box, crop_bbox), text_block.text_id, COLORS["text"], width=1)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    crop.save(destination)
    return destination


def _region_label(region: Region) -> str:
    semantic = region.metadata.get("semantic_region_hint") or region.metadata.get("section_title_text", "")
    if semantic:
        return f"{region.region_id} {semantic}"
    return region.region_id


def _visible_region_ids(regions: list[Region], show_browser_elements: bool) -> set[str]:
    hidden = {"header", "browser_bar", "footer"}
    if show_browser_elements:
        return {region.region_id for region in regions}
    return {region.region_id for region in regions if region.region_type_hint not in hidden}


def _draw_labeled_box(
    draw: ImageDraw.ImageDraw,
    bbox: BBox,
    label: str,
    color: str,
    width: int,
) -> None:
    draw.rectangle((bbox.x, bbox.y, bbox.right, bbox.bottom), outline=color, width=width)
    font = ImageFont.load_default()
    text_box = draw.textbbox((bbox.x + 2, max(0, bbox.y - 12)), label, font=font)
    draw.rectangle(text_box, fill=color)
    draw.text((text_box[0], text_box[1]), label, fill="white", font=font)


def _translate(bbox: BBox, crop_bbox: BBox) -> BBox:
    return BBox(x=bbox.x - crop_bbox.x, y=bbox.y - crop_bbox.y, width=bbox.width, height=bbox.height)


def _center_inside(box: BBox, outer: BBox) -> bool:
    center_x = box.x + box.width // 2
    center_y = box.y + box.height // 2
    return outer.x <= center_x <= outer.right and outer.y <= center_y <= outer.bottom
