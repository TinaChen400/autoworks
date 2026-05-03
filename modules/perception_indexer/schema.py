from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

REGION_TYPE_HINTS = {
    "full_screenshot",
    "model_input_region",
    "web_viewport",
    "browser_viewport",
    "page_content_area",
    "business_content_area",
    "header",
    "browser_bar",
    "left_sidebar",
    "right_sidebar",
    "main_content",
    "form_area",
    "question_area",
    "option_area",
    "media_area",
    "source_items_area",
    "target_zones_area",
    "navigation_area",
    "footer",
    "modal_area",
    "card",
    "form_section",
    "question_card",
    "account_section",
    "contact_section",
    "notification_section",
    "security_section",
    "license_section",
    "unknown",
}

ELEMENT_TYPE_HINTS = {
    "input_like",
    "button_like",
    "checkbox_like",
    "radio_like",
    "dropdown_like",
    "card_like",
    "image_like",
    "icon_like",
    "text_container_like",
    "draggable_like",
    "drop_zone_like",
    "slider_like",
    "table_cell_like",
    "unknown",
}

RELATIONSHIP_TYPES = {
    "element_in_region",
    "text_in_region",
    "text_labels_element",
    "text_inside_element",
    "nearby_text",
    "possible_section_title",
    "possible_option_label",
    "region_contains_region",
    "card_contains_element",
    "section_contains_field",
    "section_title_for_region",
    "unknown",
}

FALLBACK_RECOMMENDATIONS = {"expand_crop", "use_annotated_overview", "use_full_screenshot"}


@dataclass
class BBox:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class CropQuality:
    crop_quality: str = "unknown"
    safe_for_detail_parse: bool = False
    crop_complete_estimate: float = 0.0
    content_touching_edges: bool = False
    content_touching_top_edge: bool = False
    content_touching_bottom_edge: bool = False
    content_touching_left_edge: bool = False
    content_touching_right_edge: bool = False
    possible_half_cut_text_or_controls: bool = False
    missing_question_context_possible: bool = False
    missing_options_or_inputs_possible: bool = False
    missing_answer_options_possible: bool = False
    missing_input_fields_possible: bool = False
    missing_navigation_possible: bool = False
    fallback_recommendation: str = "use_full_screenshot"
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Region:
    region_id: str
    region_type_hint: str
    bbox_raw: dict[str, int]
    bbox_norm: dict[str, float]
    crop_path: str = ""
    annotated_crop_path: str = ""
    element_ids: list[str] = field(default_factory=list)
    text_ids: list[str] = field(default_factory=list)
    crop_quality: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Element:
    element_id: str
    region_id: str
    element_type_hint: str
    bbox_raw: dict[str, int]
    bbox_norm: dict[str, float]
    click_point_raw: dict[str, int]
    click_point_norm: dict[str, float]
    associated_text_ids: list[str] = field(default_factory=list)
    label_text: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TextBlock:
    text_id: str
    text: str
    bbox_raw: dict[str, int]
    bbox_norm: dict[str, float]
    confidence: float
    source: str
    associated_region_id: str = ""
    associated_element_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Relationship:
    relationship_id: str
    relationship_type: str
    source_id: str
    target_id: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LayoutHints:
    has_many_input_like_elements: bool = False
    has_many_button_like_elements: bool = False
    has_large_image_area: bool = False
    has_left_sidebar: bool = False
    has_two_column_layout: bool = False
    has_grid_layout: bool = False
    has_table_like_structure: bool = False
    has_possible_drag_drop_layout: bool = False
    has_possible_form_layout: bool = False
    has_possible_survey_layout: bool = False
    web_viewport_region_id: str = ""
    main_business_region_id: str = ""
    card_region_ids: list[str] = field(default_factory=list)
    business_card_region_ids: list[str] = field(default_factory=list)
    form_section_region_ids: list[str] = field(default_factory=list)
    true_section_title_texts: list[str] = field(default_factory=list)
    false_card_candidates_removed: list[dict[str, Any]] = field(default_factory=list)
    detector_scores: dict[str, float] = field(default_factory=dict)
    possible_page_types: list[str] = field(default_factory=list)
    recommended_regions_for_detail_parse: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IdGenerator:
    def __init__(self) -> None:
        self._counters = {"R": 0, "E": 0, "T": 0, "REL": 0}

    def next_region(self) -> str:
        self._counters["R"] += 1
        return f"R{self._counters['R']}"

    def next_element(self) -> str:
        self._counters["E"] += 1
        return f"E{self._counters['E']}"

    def next_text(self) -> str:
        self._counters["T"] += 1
        return f"T{self._counters['T']}"

    def next_relationship(self) -> str:
        self._counters["REL"] += 1
        return f"REL{self._counters['REL']}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_index_id() -> str:
    return f"layout_{uuid4().hex}"


def clamp_bbox(bbox: BBox, image_width: int, image_height: int) -> BBox:
    x = max(0, min(image_width, bbox.x))
    y = max(0, min(image_height, bbox.y))
    right = max(x, min(image_width, bbox.right))
    bottom = max(y, min(image_height, bbox.bottom))
    return BBox(x=x, y=y, width=right - x, height=bottom - y)


def normalize_bbox(bbox: BBox, image_width: int, image_height: int) -> dict[str, float]:
    width = max(1, image_width)
    height = max(1, image_height)
    return {
        "x": round(bbox.x / width, 6),
        "y": round(bbox.y / height, 6),
        "width": round(bbox.width / width, 6),
        "height": round(bbox.height / height, 6),
    }


def click_point_for_bbox(bbox: BBox) -> dict[str, int]:
    return {"x": bbox.x + bbox.width // 2, "y": bbox.y + bbox.height // 2}


def normalize_point(point: dict[str, int], image_width: int, image_height: int) -> dict[str, float]:
    return {
        "x": round(point["x"] / max(1, image_width), 6),
        "y": round(point["y"] / max(1, image_height), 6),
    }


def boxes_intersect(a: BBox, b: BBox) -> bool:
    return a.x < b.right and a.right > b.x and a.y < b.bottom and a.bottom > b.y


def box_contains(outer: BBox, inner: BBox) -> bool:
    return (
        inner.x >= outer.x
        and inner.y >= outer.y
        and inner.right <= outer.right
        and inner.bottom <= outer.bottom
    )


def bbox_from_dict(data: dict[str, Any]) -> BBox:
    return BBox(
        x=int(data.get("x", 0)),
        y=int(data.get("y", 0)),
        width=int(data.get("width", 0)),
        height=int(data.get("height", 0)),
    )
