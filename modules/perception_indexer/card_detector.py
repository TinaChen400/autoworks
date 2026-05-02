from __future__ import annotations

from PIL import Image

from modules.perception_indexer.schema import (
    BBox,
    Element,
    IdGenerator,
    Region,
    TextBlock,
    bbox_from_dict,
    clamp_bbox,
    normalize_bbox,
)
from modules.perception_indexer.text_classifier import section_region_type_for_text


def detect_viewport_regions(
    image: Image.Image,
    model_region: BBox,
    ids: IdGenerator,
    warnings: list[str],
) -> list[Region]:
    gray = image.convert("L")
    found_top = None
    for y in range(model_region.y, model_region.y + min(260, model_region.height), 4):
        row = [gray.getpixel((x, y)) for x in range(model_region.x, model_region.right, max(1, model_region.width // 80))]
        bright_ratio = sum(1 for value in row if value > 235) / max(1, len(row))
        if bright_ratio > 0.62:
            found_top = y
            break
    if found_top is None:
        found_top = model_region.y + int(model_region.height * 0.10)
        warnings.append("web_viewport detection uncertain; using conservative viewport.")
    y_start = max(model_region.y, found_top)

    found_bottom = None
    for y in range(model_region.bottom - 1, max(y_start, model_region.bottom - 180), -4):
        row = [gray.getpixel((x, y)) for x in range(model_region.x, model_region.right, max(1, model_region.width // 80))]
        dark_ratio = sum(1 for value in row if value < 70) / max(1, len(row))
        if dark_ratio < 0.35:
            found_bottom = y
            break
    if found_bottom is None:
        found_bottom = model_region.bottom - int(model_region.height * 0.04)
        warnings.append("remote taskbar exclusion uncertain; viewport bottom is conservative.")
    y_end = min(model_region.bottom, found_bottom)
    browser_bbox = clamp_bbox(
        BBox(model_region.x, y_start, model_region.width, max(1, y_end - y_start)),
        image.width,
        image.height,
    )
    page_bbox = _detect_page_content_bbox(image, browser_bbox)
    business_bbox = _detect_business_content_bbox(image, page_bbox)
    return [
        Region(
            region_id=ids.next_region(),
            region_type_hint="browser_viewport",
            bbox_raw=browser_bbox.to_dict(),
            bbox_norm=normalize_bbox(browser_bbox, image.width, image.height),
            confidence=0.55 if warnings else 0.70,
            metadata={"source": "local_browser_viewport_detection"},
        ),
        Region(
            region_id=ids.next_region(),
            region_type_hint="web_viewport",
            bbox_raw=page_bbox.to_dict(),
            bbox_norm=normalize_bbox(page_bbox, image.width, image.height),
            confidence=0.62,
            metadata={"source": "local_page_content_detection"},
        ),
        Region(
            region_id=ids.next_region(),
            region_type_hint="business_content_area",
            bbox_raw=business_bbox.to_dict(),
            bbox_norm=normalize_bbox(business_bbox, image.width, image.height),
            confidence=0.58,
            metadata={"source": "central_business_area_detection"},
        ),
    ]


def detect_web_viewport(
    image: Image.Image,
    model_region: BBox,
    ids: IdGenerator,
    warnings: list[str],
) -> Region:
    return detect_viewport_regions(image, model_region, ids, warnings)[1]


def _detect_page_content_bbox(image: Image.Image, browser_bbox: BBox) -> BBox:
    gray = image.convert("L")
    sample_y_values = range(browser_bbox.y, browser_bbox.bottom, max(8, browser_bbox.height // 60))
    left_candidates = []
    right_candidates = []
    for y in sample_y_values:
        values = [
            gray.getpixel((x, y))
            for x in range(browser_bbox.x, browser_bbox.right, max(1, browser_bbox.width // 160))
        ]
        xs = list(range(browser_bbox.x, browser_bbox.right, max(1, browser_bbox.width // 160)))
        non_blank = [x for x, value in zip(xs, values, strict=False) if value < 248]
        if non_blank:
            left_candidates.append(min(non_blank))
            right_candidates.append(max(non_blank))
    if not left_candidates:
        return browser_bbox
    left = max(browser_bbox.x, min(left_candidates) - 16)
    right = min(browser_bbox.right, max(right_candidates) + 16)
    return clamp_bbox(BBox(left, browser_bbox.y, max(1, right - left), browser_bbox.height), image.width, image.height)


def _detect_business_content_bbox(image: Image.Image, page_bbox: BBox) -> BBox:
    gray = image.convert("L")
    xs: list[int] = []
    ys: list[int] = []
    step_x = max(4, page_bbox.width // 220)
    step_y = max(4, page_bbox.height // 160)
    for y in range(page_bbox.y, page_bbox.bottom, step_y):
        for x in range(page_bbox.x, page_bbox.right, step_x):
            value = gray.getpixel((x, y))
            if 35 < value < 245:
                if page_bbox.x + page_bbox.width * 0.16 <= x <= page_bbox.x + page_bbox.width * 0.92:
                    xs.append(x)
                    ys.append(y)
    if len(xs) < 20:
        return page_bbox
    left = max(page_bbox.x, min(xs) - 48)
    right = min(page_bbox.right, max(xs) + 48)
    top = max(page_bbox.y, min(ys) - 36)
    bottom = min(page_bbox.bottom, max(ys) + 36)
    return clamp_bbox(BBox(left, top, max(1, right - left), max(1, bottom - top)), image.width, image.height)


def _legacy_web_region(image: Image.Image, ids: IdGenerator, bbox: BBox, warnings: list[str]) -> Region:
    return Region(
        region_id=ids.next_region(),
        region_type_hint="web_viewport",
        bbox_raw=bbox.to_dict(),
        bbox_norm=normalize_bbox(bbox, image.width, image.height),
        confidence=0.55 if warnings else 0.70,
        metadata={"source": "local_web_viewport_detection"},
    )


def detect_card_regions(
    image: Image.Image,
    web_viewport: Region,
    elements: list[Element],
    text_blocks: list[TextBlock],
    ids: IdGenerator,
    warnings: list[str],
) -> tuple[list[Region], list[dict]]:
    viewport = bbox_from_dict(web_viewport.bbox_raw)
    title_cards = _cards_from_titles(image, viewport, text_blocks, ids)
    if title_cards:
        return _dedupe_cards(title_cards)
    warnings.append("OCR disabled; semantic section labels may be unavailable.")
    return _cards_from_element_clusters(image, viewport, elements, ids), []


def _cards_from_titles(
    image: Image.Image,
    viewport: BBox,
    text_blocks: list[TextBlock],
    ids: IdGenerator,
) -> list[Region]:
    title_blocks = []
    for block in text_blocks:
        if block.metadata.get("text_role") != "section_title":
            continue
        hint, semantic = section_region_type_for_text(block.text)
        box = bbox_from_dict(block.bbox_raw)
        if hint and viewport.y <= box.y <= viewport.bottom:
            title_blocks.append((block, hint, semantic, box))
    title_blocks.sort(key=lambda item: item[3].y)
    regions: list[Region] = []
    for index, (block, hint, semantic, box) in enumerate(title_blocks):
        next_y = title_blocks[index + 1][3].y if index + 1 < len(title_blocks) else viewport.bottom
        top = max(viewport.y, box.y - 16)
        bottom = min(viewport.bottom, max(box.bottom + 80, next_y - 8))
        left = max(viewport.x, box.x - 24)
        right = min(viewport.right, max(box.right + 420, left + int(viewport.width * 0.52)))
        regions.append(
            _new_card_region(
                image=image,
                ids=ids,
                bbox=BBox(left, top, max(1, right - left), max(1, bottom - top)),
                region_type_hint=hint,
                semantic_hint=semantic,
                source="ocr_section_title",
                title_text=block.text,
                title_text_id=block.text_id,
            )
        )
    return regions


def _cards_from_element_clusters(
    image: Image.Image,
    viewport: BBox,
    elements: list[Element],
    ids: IdGenerator,
) -> list[Region]:
    business_elements = [
        element
        for element in elements
        if element.confidence >= 0.30 and _center_inside(bbox_from_dict(element.bbox_raw), viewport)
    ]
    central_elements = [
        element
        for element in business_elements
        if viewport.x + viewport.width * 0.22
        <= bbox_from_dict(element.bbox_raw).x + bbox_from_dict(element.bbox_raw).width / 2
        <= viewport.x + viewport.width * 0.86
    ]
    if len(central_elements) >= 5:
        business_elements = central_elements
    if not business_elements:
        return []
    left = min(bbox_from_dict(element.bbox_raw).x for element in business_elements)
    right = max(bbox_from_dict(element.bbox_raw).right for element in business_elements)
    rows = sorted((bbox_from_dict(element.bbox_raw) for element in business_elements), key=lambda box: box.y)
    clusters: list[list[BBox]] = []
    for box in rows:
        if not clusters:
            clusters.append([box])
            continue
        previous_bottom = max(item.bottom for item in clusters[-1])
        gap = box.y - previous_bottom
        if gap >= 42 and len(clusters[-1]) >= 1:
            clusters.append([box])
        else:
            clusters[-1].append(box)
    if len(clusters) <= 2 and len(rows) >= 5:
        y_min = min(box.y for box in rows)
        y_max = max(box.bottom for box in rows)
        band = max(80, (y_max - y_min) // 5)
        clusters = []
        for start in range(y_min, y_max + 1, band):
            cluster = [box for box in rows if start <= box.y < start + band]
            if cluster:
                clusters.append(cluster)

    semantic_sequence = [
        ("license_section", "license"),
        ("account_section", "account"),
        ("contact_section", "contact"),
        ("notification_section", "notification"),
        ("security_section", "security"),
    ]
    regions: list[Region] = []
    for index, cluster in enumerate(clusters[:7]):
        top = max(viewport.y, min(box.y for box in cluster) - 42)
        bottom = min(viewport.bottom, max(box.bottom for box in cluster) + 34)
        semantic_type, semantic_name = semantic_sequence[index] if index < len(semantic_sequence) else ("form_section", "")
        regions.append(
            _new_card_region(
                image=image,
                ids=ids,
                bbox=BBox(max(viewport.x, left - 36), top, min(viewport.right, right + 36) - max(viewport.x, left - 36), max(1, bottom - top)),
                region_type_hint=semantic_type if len(clusters) >= 4 else "form_section",
                semantic_hint=semantic_name if len(clusters) >= 4 else "",
                source="element_vertical_clustering",
            )
        )
    return regions


def _new_card_region(
    image: Image.Image,
    ids: IdGenerator,
    bbox: BBox,
    region_type_hint: str,
    semantic_hint: str,
    source: str,
    title_text: str = "",
    title_text_id: str = "",
) -> Region:
    clamped = clamp_bbox(bbox, image.width, image.height)
    return Region(
        region_id=ids.next_region(),
        region_type_hint=region_type_hint,
        bbox_raw=clamped.to_dict(),
        bbox_norm=normalize_bbox(clamped, image.width, image.height),
        confidence=0.72 if title_text else 0.48,
        metadata={
            "source": source,
            "semantic_region_hint": semantic_hint,
            "title_text": title_text,
            "title_text_id": title_text_id,
            "is_true_business_card": bool(title_text),
            "is_card_region": True,
        },
    )

def _center_inside(box: BBox, outer: BBox) -> bool:
    return outer.x <= box.x + box.width // 2 <= outer.right and outer.y <= box.y + box.height // 2 <= outer.bottom


def _dedupe_cards(cards: list[Region]) -> tuple[list[Region], list[dict]]:
    kept: list[Region] = []
    removed: list[dict] = []
    seen_semantics: set[str] = set()
    for card in cards:
        semantic = str(card.metadata.get("semantic_region_hint", ""))
        if semantic and semantic in seen_semantics:
            removed.append(
                {
                    "region_type_hint": card.region_type_hint,
                    "semantic_region_hint": semantic,
                    "title_text": card.metadata.get("title_text", ""),
                    "reason": "duplicate_section_title",
                    "bbox_raw": card.bbox_raw,
                }
            )
            continue
        duplicate_of = next((item for item in kept if _overlap_ratio(bbox_from_dict(item.bbox_raw), bbox_from_dict(card.bbox_raw)) > 0.72), None)
        if duplicate_of:
            removed.append(
                {
                    "region_type_hint": card.region_type_hint,
                    "semantic_region_hint": semantic,
                    "title_text": card.metadata.get("title_text", ""),
                    "reason": f"overlaps_true_card_{duplicate_of.region_id}",
                    "bbox_raw": card.bbox_raw,
                }
            )
            continue
        kept.append(card)
        if semantic:
            seen_semantics.add(semantic)
    return kept, removed


def _overlap_ratio(a: BBox, b: BBox) -> float:
    overlap_x = max(0, min(a.right, b.right) - max(a.x, b.x))
    overlap_y = max(0, min(a.bottom, b.bottom) - max(a.y, b.y))
    overlap = overlap_x * overlap_y
    return overlap / max(1, min(a.area, b.area))
