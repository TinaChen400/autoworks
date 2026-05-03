from __future__ import annotations

from modules.perception_indexer.schema import (
    BBox,
    Element,
    Relationship,
    TextBlock,
    bbox_from_dict,
    box_contains,
)
from modules.perception_indexer.text_classifier import classify_text

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


def associate_text(
    elements: list[Element],
    text_blocks: list[TextBlock],
    relationship_id,
) -> list[Relationship]:
    relationships: list[Relationship] = []
    for text_block in text_blocks:
        text_role = text_block.metadata.get("text_role") or classify_text(text_block.text)[0]
        text_box = bbox_from_dict(text_block.bbox_raw)
        best_element: Element | None = None
        best_relationship = ""
        best_confidence = 0.0
        candidates: list[tuple[int, float, Element, str, float]] = []
        for element in elements:
            element_box = bbox_from_dict(element.bbox_raw)
            if box_contains(element_box, text_box) and text_role in {"button_text", "action_link", "field_value", "field_label"}:
                priority = 0 if text_role in {"button_text", "action_link"} else 2
                candidates.append((priority, _distance(text_box, element_box), element, "text_inside_element", 0.85))
            if _labels_input(text_box, element_box, element.element_type_hint):
                priority = 0 if text_role == "field_label" else 4
                if text_role != "section_title":
                    candidates.append((priority, _distance(text_box, element_box), element, "text_labels_element", 0.72))
            elif _labels_option(text_box, element_box, element.element_type_hint):
                candidates.append((1, _distance(text_box, element_box), element, "possible_option_label", 0.60))
            elif _nearby(text_box, element_box) and text_role not in {"section_title", "instruction_text"}:
                candidates.append((5, _distance(text_box, element_box), element, "nearby_text", 0.35))
        if candidates:
            _priority, _distance_value, best_element, best_relationship, best_confidence = min(
                candidates,
                key=lambda item: (item[0], item[1]),
            )
        if best_element:
            text_block.associated_element_id = best_element.element_id
            if text_block.text_id not in best_element.associated_text_ids:
                best_element.associated_text_ids.append(text_block.text_id)
            if best_relationship in {
                "text_labels_element",
                "text_inside_element",
                "possible_option_label",
            } and _should_replace_label(best_element, text_block.text, str(text_role)):
                best_element.label_text = text_block.text
            relationships.append(
                Relationship(
                    relationship_id=relationship_id(),
                    relationship_type=best_relationship,
                    source_id=text_block.text_id,
                    target_id=best_element.element_id,
                    confidence=best_confidence,
                )
            )
        if text_role == "section_title":
            relationships.append(
                Relationship(
                    relationship_id=relationship_id(),
                    relationship_type="possible_section_title",
                    source_id=text_block.text_id,
                    target_id=text_block.associated_region_id,
                    confidence=0.45,
                )
            )
    return relationships


def associate_section_titles(
    regions,
    text_blocks: list[TextBlock],
    relationship_id,
) -> list[Relationship]:
    relationships: list[Relationship] = []
    for region in regions:
        if region.region_type_hint not in CARD_HINTS:
            continue
        region_box = bbox_from_dict(region.bbox_raw)
        candidates = [
            block
            for block in text_blocks
            if block.metadata.get("text_role") == "section_title"
            and box_contains(region_box, bbox_from_dict(block.bbox_raw))
            and bbox_from_dict(block.bbox_raw).y <= region_box.y + max(48, region_box.height * 0.22)
        ]
        if not candidates:
            continue
        title = min(candidates, key=lambda block: bbox_from_dict(block.bbox_raw).y)
        region.text_ids.append(title.text_id)
        region.metadata["section_title_text"] = title.text
        region.metadata.setdefault("semantic_region_hint", _semantic_name(title.text))
        relationships.append(
            Relationship(
                relationship_id=relationship_id(),
                relationship_type="section_title_for_region",
                source_id=title.text_id,
                target_id=region.region_id,
                confidence=0.70,
            )
        )
    return relationships


def _labels_input(text_box: BBox, element_box: BBox, hint: str) -> bool:
    if hint not in {"input_like", "dropdown_like", "button_like"}:
        return False
    vertically_close_above = 0 <= element_box.y - text_box.bottom <= 28
    left_aligned = abs(text_box.x - element_box.x) <= 45
    left_label = 0 <= element_box.x - text_box.right <= 70 and _vertical_overlap(text_box, element_box)
    return (vertically_close_above and left_aligned) or left_label


def _labels_option(text_box: BBox, element_box: BBox, hint: str) -> bool:
    if hint not in {"checkbox_like", "radio_like"}:
        return False
    return 0 <= text_box.x - element_box.right <= 160 and _vertical_overlap(text_box, element_box)


def _nearby(text_box: BBox, element_box: BBox) -> bool:
    x_gap = max(0, max(element_box.x - text_box.right, text_box.x - element_box.right))
    y_gap = max(0, max(element_box.y - text_box.bottom, text_box.y - element_box.bottom))
    return x_gap <= 80 and y_gap <= 40


def _distance(a: BBox, b: BBox) -> float:
    ax = a.x + a.width / 2
    ay = a.y + a.height / 2
    bx = b.x + b.width / 2
    by = b.y + b.height / 2
    return abs(ax - bx) + abs(ay - by)


def _should_replace_label(element: Element, candidate: str, role: str) -> bool:
    if not element.label_text:
        return role != "section_title"
    current_role = classify_text(element.label_text)[0]
    priority = {"field_label": 0, "button_text": 0, "action_link": 0, "field_value": 2, "unknown": 3, "section_title": 9}
    return priority.get(role, 5) < priority.get(current_role, 5)


def _vertical_overlap(a: BBox, b: BBox) -> bool:
    overlap = min(a.bottom, b.bottom) - max(a.y, b.y)
    return overlap >= min(a.height, b.height) * 0.35


def _looks_like_section_title(text_box: BBox, text: str) -> bool:
    if len(text.strip()) < 3:
        return False
    return text_box.height >= 18 and text_box.width >= 40


def _semantic_name(text: str) -> str:
    lowered = text.lower()
    if "license" in lowered or "credential" in lowered:
        return "license"
    if "account" in lowered:
        return "account"
    if "contact" in lowered:
        return "contact"
    if "notification" in lowered:
        return "notification"
    if "security" in lowered:
        return "security"
    return ""
