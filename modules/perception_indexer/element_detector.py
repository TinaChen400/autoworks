from __future__ import annotations

from collections import deque

from PIL import Image

from modules.perception_indexer.schema import (
    BBox,
    Element,
    IdGenerator,
    Region,
    box_contains,
    boxes_intersect,
    click_point_for_bbox,
    normalize_bbox,
    normalize_point,
)


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
