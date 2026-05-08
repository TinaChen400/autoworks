from __future__ import annotations

from collections import deque

from PIL import Image

from modules.perception_indexer.schema import (
    BBox,
    Element,
    IdGenerator,
    Region,
    TextBlock,
    bbox_from_dict,
    box_contains,
    boxes_intersect,
    click_point_for_bbox,
    normalize_bbox,
    normalize_point,
)


TEXT_LEFT_CONTROL_SOURCE = "ocr_guided_text_left_control"


def _edge_components(image: Image.Image, work_area: BBox) -> list[BBox]:
    crop = image.crop((work_area.x, work_area.y, work_area.right, work_area.bottom)).convert("L")
    max_side = 900
    scale = min(1.0, max_side / max(crop.width, crop.height))
    if scale < 1.0:
        resized = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))))
    else:
        resized = crop
    width, height = resized.size
    pixels = resized.load()
    edge: set[tuple[int, int]] = set()
    for y in range(1, height - 1, 2):
        for x in range(1, width - 1, 2):
            value = pixels[x, y]
            if abs(value - pixels[x + 1, y]) > 22 or abs(value - pixels[x, y + 1]) > 22:
                edge.add((x, y))

    components: list[BBox] = []
    while edge:
        start = edge.pop()
        queue: deque[tuple[int, int]] = deque([start])
        min_x = max_x = start[0]
        min_y = max_y = start[1]
        count = 0
        while queue:
            x, y = queue.popleft()
            count += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for nx, ny in ((x - 2, y), (x + 2, y), (x, y - 2), (x, y + 2)):
                if (nx, ny) in edge:
                    edge.remove((nx, ny))
                    queue.append((nx, ny))
        if count < 8:
            continue
        inv_scale = 1 / scale
        components.append(
            BBox(
                x=work_area.x + int(min_x * inv_scale),
                y=work_area.y + int(min_y * inv_scale),
                width=max(1, int((max_x - min_x + 2) * inv_scale)),
                height=max(1, int((max_y - min_y + 2) * inv_scale)),
            )
        )
    return components


def _classify(bbox: BBox, image_area: int) -> tuple[str, float]:
    area = bbox.area
    aspect = bbox.width / max(1, bbox.height)
    if bbox.width <= 28 and bbox.height <= 28:
        if 0.75 <= aspect <= 1.35:
            return "checkbox_like", 0.45
        return "icon_like", 0.35
    if area > image_area * 0.08 and bbox.width > bbox.height:
        return "card_like", 0.35
    if bbox.height <= 55 and bbox.width >= 90:
        if aspect > 5:
            return "input_like", 0.50
        if 1.6 <= aspect <= 5:
            return "button_like", 0.45
    if bbox.width > 160 and bbox.height > 120:
        return "image_like", 0.40
    if bbox.width > 80 and bbox.height > 24:
        return "text_container_like", 0.30
    return "unknown", 0.20


def _merge_nearby(boxes: list[BBox]) -> list[BBox]:
    merged: list[BBox] = []
    for box in sorted(boxes, key=lambda item: (item.y, item.x)):
        absorbed = False
        for index, existing in enumerate(merged):
            horizontal_close = abs(box.x - existing.x) < 12 and abs(box.right - existing.right) < 18
            vertical_gap = 0 <= box.y - existing.bottom <= 12
            if horizontal_close and vertical_gap:
                x = min(existing.x, box.x)
                y = min(existing.y, box.y)
                right = max(existing.right, box.right)
                bottom = max(existing.bottom, box.bottom)
                merged[index] = BBox(x, y, right - x, bottom - y)
                absorbed = True
                break
        if not absorbed:
            merged.append(box)
    return merged


def detect_elements(
    image: Image.Image,
    regions: list[Region],
    ids: IdGenerator,
    min_area: int,
    max_area_ratio: float,
) -> list[Element]:
    model_region = regions[0]
    work_area = BBox(
        x=model_region.bbox_raw["x"],
        y=model_region.bbox_raw["y"],
        width=model_region.bbox_raw["width"],
        height=model_region.bbox_raw["height"],
    )
    image_area = image.width * image.height
    raw_boxes = _merge_nearby(_edge_components(image, work_area))
    elements: list[Element] = []
    for bbox in raw_boxes:
        if bbox.area < min_area or bbox.area > image_area * max_area_ratio:
            continue
        if bbox.width < 8 or bbox.height < 8:
            continue
        hint, confidence = _classify(bbox, image_area)
        region_id = _best_region_id(bbox, regions)
        click_raw = click_point_for_bbox(bbox)
        elements.append(
            Element(
                element_id=ids.next_element(),
                region_id=region_id,
                element_type_hint=hint,
                bbox_raw=bbox.to_dict(),
                bbox_norm=normalize_bbox(bbox, image.width, image.height),
                click_point_raw=click_raw,
                click_point_norm=normalize_point(click_raw, image.width, image.height),
                confidence=confidence,
                metadata={"source": "local_edge_components"},
            )
        )
    return elements[:300]


def detect_text_left_controls(
    image: Image.Image,
    regions: list[Region],
    text_blocks: list[TextBlock],
    existing_elements: list[Element],
    ids: IdGenerator,
    max_search_left_px: int = 96,
) -> list[Element]:
    elements: list[Element] = []
    for text_block in text_blocks:
        text_box = bbox_from_dict(text_block.bbox_raw)
        if not _eligible_text_left_control_label(text_box, image.width, image.height):
            continue
        search_box = _text_left_search_box(text_box, image.width, image.height, max_search_left_px)
        if search_box.width < 8 or search_box.height < 8:
            continue
        for component in _merge_control_fragments(_edge_components(image, search_box)):
            control_box = _control_bbox_from_component(component)
            if control_box is None:
                continue
            click_raw = click_point_for_bbox(control_box)
            existing = _nearby_existing_control(click_raw, existing_elements + elements)
            if existing is not None:
                if existing.element_type_hint in {"icon_like", "unknown"}:
                    existing.element_type_hint = "checkbox_like"
                    existing.confidence = max(existing.confidence, 0.66)
                    existing.metadata["source"] = TEXT_LEFT_CONTROL_SOURCE
                    existing.metadata["source_text_id"] = text_block.text_id
                continue
            region_id = _best_region_id(control_box, regions)
            elements.append(
                Element(
                    element_id=ids.next_element(),
                    region_id=region_id,
                    element_type_hint="checkbox_like",
                    bbox_raw=control_box.to_dict(),
                    bbox_norm=normalize_bbox(control_box, image.width, image.height),
                    click_point_raw=click_raw,
                    click_point_norm=normalize_point(click_raw, image.width, image.height),
                    confidence=0.68,
                    metadata={
                        "source": TEXT_LEFT_CONTROL_SOURCE,
                        "source_text_id": text_block.text_id,
                    },
                )
            )
    return elements


def _eligible_text_left_control_label(text_box: BBox, image_width: int, image_height: int) -> bool:
    if text_box.width < max(70, int(image_width * 0.03)) or text_box.height < 8:
        return False
    center_y = text_box.y + text_box.height / 2
    if center_y < image_height * 0.20 or center_y > image_height * 0.92:
        return False
    return True


def _text_left_search_box(
    text_box: BBox,
    image_width: int,
    image_height: int,
    max_search_left_px: int,
) -> BBox:
    center_y = text_box.y + text_box.height // 2
    vertical_radius = max(18, int(text_box.height * 1.2))
    left = max(0, text_box.x - max_search_left_px)
    right = max(left, min(image_width, text_box.x - 4))
    top = max(0, center_y - vertical_radius)
    bottom = min(image_height, center_y + vertical_radius)
    return BBox(left, top, right - left, bottom - top)


def _control_bbox_from_component(component: BBox) -> BBox | None:
    if not (8 <= component.width <= 28 and 8 <= component.height <= 28):
        return None
    aspect = component.width / max(1, component.height)
    if not 0.65 <= aspect <= 1.45:
        return None
    return component


def _merge_control_fragments(components: list[BBox]) -> list[BBox]:
    merged: list[BBox] = []
    for component in sorted(components, key=lambda item: (item.y, item.x)):
        merged_into_existing = False
        for index, existing in enumerate(merged):
            if _control_fragments_close(existing, component):
                left = min(existing.x, component.x)
                top = min(existing.y, component.y)
                right = max(existing.right, component.right)
                bottom = max(existing.bottom, component.bottom)
                merged[index] = BBox(left, top, right - left, bottom - top)
                merged_into_existing = True
                break
        if not merged_into_existing:
            merged.append(component)
    return merged


def _control_fragments_close(first: BBox, second: BBox) -> bool:
    left = min(first.x, second.x)
    top = min(first.y, second.y)
    right = max(first.right, second.right)
    bottom = max(first.bottom, second.bottom)
    if right - left > 32 or bottom - top > 32:
        return False
    horizontal_gap = max(0, max(first.x - second.right, second.x - first.right))
    vertical_gap = max(0, max(first.y - second.bottom, second.y - first.bottom))
    return horizontal_gap <= 4 and vertical_gap <= 4


def _nearby_existing_control(point: dict[str, int], elements: list[Element]) -> Element | None:
    for element in elements:
        if element.element_type_hint not in {"checkbox_like", "radio_like", "icon_like", "unknown"}:
            continue
        existing = element.click_point_raw
        if not isinstance(existing, dict):
            continue
        try:
            distance = abs(int(existing["x"]) - point["x"]) + abs(int(existing["y"]) - point["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if distance <= 10:
            return element
    return None


def _best_region_id(bbox: BBox, regions: list[Region]) -> str:
    best_id = regions[0].region_id
    best_area = 0
    for region in regions[1:] or regions:
        region_box = BBox(
            region.bbox_raw["x"],
            region.bbox_raw["y"],
            region.bbox_raw["width"],
            region.bbox_raw["height"],
        )
        if box_contains(region_box, bbox):
            return region.region_id
        if boxes_intersect(region_box, bbox):
            overlap_x = min(region_box.right, bbox.right) - max(region_box.x, bbox.x)
            overlap_y = min(region_box.bottom, bbox.bottom) - max(region_box.y, bbox.y)
            area = max(0, overlap_x) * max(0, overlap_y)
            if area > best_area:
                best_area = area
                best_id = region.region_id
    return best_id
