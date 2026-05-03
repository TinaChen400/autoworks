from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from modules.perception_indexer.annotator import save_annotated_overview
from modules.perception_indexer.card_detector import detect_card_regions, detect_web_viewport
from modules.perception_indexer.crop_quality import compute_crop_quality, expand_and_clamp_crop
from modules.perception_indexer.detectors import (
    DetectorResult,
    run_drag_drop_detector,
    run_form_detector,
)
from modules.perception_indexer.detectors.runner import (
    detector_scores,
    possible_page_types_from_scores,
    run_detectors,
)
from modules.perception_indexer.grouping import (
    assign_elements_to_smallest_regions,
    build_region_relationships,
    infer_layout_hints,
)
from modules.perception_indexer.index_store import read_json, write_json
from modules.perception_indexer.indexer import build_layout_index
from modules.perception_indexer.ocr_layer import run_ocr
from modules.perception_indexer.schema import (
    BBox,
    Element,
    IdGenerator,
    Region,
    TextBlock,
    click_point_for_bbox,
    normalize_bbox,
    normalize_point,
)
from modules.perception_indexer.text_association import associate_text
from modules.perception_indexer.text_classifier import classify_text, classify_text_blocks


def test_schema_bbox_normalization_and_click_point() -> None:
    bbox = BBox(x=10, y=20, width=40, height=20)
    point = click_point_for_bbox(bbox)
    assert point == {"x": 30, "y": 30}
    assert normalize_bbox(bbox, 100, 100) == {
        "x": 0.1,
        "y": 0.2,
        "width": 0.4,
        "height": 0.2,
    }
    assert normalize_point(point, 100, 100) == {"x": 0.3, "y": 0.3}


def test_crop_margin_expansion_and_clamping() -> None:
    expanded = expand_and_clamp_crop(
        BBox(x=5, y=5, width=50, height=40),
        image_width=100,
        image_height=90,
        margin_percent=0.2,
        min_margin_px=20,
    )
    assert expanded == BBox(x=0, y=0, width=75, height=65)


def test_crop_quality_marks_edge_touching_crop_as_unsafe() -> None:
    element = Element(
        element_id="E1",
        region_id="R1",
        element_type_hint="input_like",
        bbox_raw={"x": 0, "y": 20, "width": 80, "height": 20},
        bbox_norm={},
        click_point_raw={},
        click_point_norm={},
    )
    quality = compute_crop_quality(
        crop_bbox=BBox(x=0, y=0, width=120, height=80),
        region_bbox=BBox(x=0, y=0, width=100, height=60),
        image_width=200,
        image_height=200,
        elements=[element],
        text_blocks=[],
    )
    assert not quality.safe_for_detail_parse
    assert quality.content_touching_edges
    assert quality.missing_input_fields_possible
    assert quality.fallback_recommendation in {
        "expand_crop",
        "use_annotated_overview",
        "use_full_screenshot",
    }


def test_card_crop_without_global_navigation_is_not_automatically_unsafe() -> None:
    element = Element(
        element_id="E1",
        region_id="R1",
        element_type_hint="input_like",
        bbox_raw={"x": 40, "y": 80, "width": 180, "height": 28},
        bbox_norm={},
        click_point_raw={},
        click_point_norm={},
    )
    text = TextBlock(
        text_id="T1",
        text="Email",
        bbox_raw={"x": 40, "y": 50, "width": 50, "height": 18},
        bbox_norm={},
        confidence=0.9,
        source="test",
    )
    quality = compute_crop_quality(
        crop_bbox=BBox(x=0, y=0, width=320, height=220),
        region_bbox=BBox(x=20, y=30, width=240, height=140),
        image_width=500,
        image_height=500,
        elements=[element],
        text_blocks=[text],
        is_card_region=True,
    )
    assert quality.safe_for_detail_parse


def test_layout_index_can_be_saved_and_loaded(tmp_path: Path) -> None:
    path = tmp_path / "layout.json"
    write_json(path, {"regions": [{"region_id": "R1"}]})
    assert read_json(path)["regions"][0]["region_id"] == "R1"


def test_ocr_disabled_path_still_works() -> None:
    ids = IdGenerator()
    warnings: list[str] = []
    blocks = run_ocr(Image.new("RGB", (100, 80), "white"), "disabled", ids, warnings)
    assert blocks == []
    assert warnings == []


def test_id_generation_uses_expected_prefixes() -> None:
    ids = IdGenerator()
    assert ids.next_region() == "R1"
    assert ids.next_element() == "E1"
    assert ids.next_text() == "T1"


def test_annotated_overview_generation_does_not_crash(tmp_path: Path) -> None:
    image = Image.new("RGB", (160, 120), "white")
    region = Region(
        region_id="R1",
        region_type_hint="main_content",
        bbox_raw={"x": 10, "y": 10, "width": 100, "height": 80},
        bbox_norm={},
    )
    output = save_annotated_overview(image, [region], [], [], tmp_path / "overview.png")
    assert output.exists()


def test_indexer_builds_layout_with_ocr_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    fixture_dir = tmp_path / "tests" / "fixtures"
    fixture_dir.mkdir(parents=True)
    image_path = fixture_dir / "latest_capture.png"
    image = Image.new("RGB", (320, 240), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 70, 220, 100), outline="black", width=2)
    draw.rectangle((60, 130, 150, 160), outline="black", width=2)
    image.save(image_path)

    runtime_dir = tmp_path / "runtime_state"
    runtime_dir.mkdir()
    (runtime_dir / "latest_runtime_context.json").write_text(
        json.dumps(
            {
                "task_id": "test",
                "screenshot_path": str(image_path),
                "model_input_region": {"x": 0, "y": 0, "width": 320, "height": 240},
            }
        ),
        encoding="utf-8",
    )

    layout = build_layout_index(ocr_backend="disabled")
    assert layout["full_screenshot"]["preserved"] is True
    assert layout["regions"][0]["region_id"].startswith("R")
    assert Path(layout["annotated_overview"]).exists()
    assert Path("runtime_state/latest_layout_index.json").exists()


def test_card_region_creation_from_clustered_elements() -> None:
    image = Image.new("RGB", (400, 500), "white")
    ids = IdGenerator()
    viewport = Region(
        region_id="R1",
        region_type_hint="web_viewport",
        bbox_raw={"x": 0, "y": 0, "width": 400, "height": 500},
        bbox_norm={},
    )
    elements = []
    for index, y in enumerate((80, 120, 220, 260, 350, 390), start=1):
        elements.append(
            Element(
                element_id=f"E{index}",
                region_id="R1",
                element_type_hint="input_like",
                bbox_raw={"x": 100, "y": y, "width": 180, "height": 24},
                bbox_norm={},
                click_point_raw={},
                click_point_norm={},
                confidence=0.5,
            )
        )
    warnings: list[str] = []
    cards, removed = detect_card_regions(image, viewport, elements, [], ids, warnings)
    assert cards
    assert removed == []
    assert all(card.metadata["is_card_region"] for card in cards)
    assert "OCR disabled; semantic section labels may be unavailable." in warnings


def test_elements_assign_to_smallest_containing_region() -> None:
    broad = Region("R1", "main_content", {"x": 0, "y": 0, "width": 400, "height": 400}, {})
    card = Region("R2", "account_section", {"x": 80, "y": 80, "width": 220, "height": 140}, {})
    element = Element(
        element_id="E1",
        region_id="R1",
        element_type_hint="input_like",
        bbox_raw={"x": 100, "y": 100, "width": 120, "height": 20},
        bbox_norm={},
        click_point_raw={},
        click_point_norm={},
    )
    assign_elements_to_smallest_regions([broad, card], [element])
    assert element.region_id == "R2"
    assert card.element_ids == ["E1"]


def test_layout_hints_include_card_region_ids() -> None:
    card = Region("R2", "account_section", {"x": 0, "y": 0, "width": 100, "height": 100}, {})
    card.metadata["is_true_business_card"] = True
    card.element_ids.append("E1")
    hints = infer_layout_hints([card], [])
    assert hints.card_region_ids == ["R2"]
    assert hints.recommended_regions_for_detail_parse == ["R2"]


def test_recommended_regions_returns_true_cards_only() -> None:
    full = Region("R1", "model_input_region", {"x": 0, "y": 0, "width": 500, "height": 500}, {})
    main = Region("R5", "main_content", {"x": 0, "y": 0, "width": 500, "height": 500}, {})
    card = Region("R9", "account_section", {"x": 100, "y": 100, "width": 200, "height": 120}, {})
    card.metadata["is_true_business_card"] = True
    hints = infer_layout_hints([full, main, card], [])
    assert hints.recommended_regions_for_detail_parse == ["R9"]


def test_ocr_titles_create_semantic_card_regions() -> None:
    image = Image.new("RGB", (500, 500), "white")
    ids = IdGenerator()
    viewport = Region(
        region_id="R1",
        region_type_hint="web_viewport",
        bbox_raw={"x": 0, "y": 0, "width": 500, "height": 500},
        bbox_norm={},
    )
    text_blocks = [
        TextBlock(
            text_id="T1",
            text="Account",
            bbox_raw={"x": 120, "y": 100, "width": 80, "height": 24},
            bbox_norm={},
            confidence=0.9,
            source="test",
        )
    ]
    classify_text_blocks(text_blocks)
    cards, removed = detect_card_regions(image, viewport, [], text_blocks, ids, [])
    assert cards[0].region_type_hint == "account_section"
    assert cards[0].metadata["semantic_region_hint"] == "account"
    assert removed == []


def test_section_title_classifier_distinguishes_roles() -> None:
    assert classify_text("Account") == ("section_title", "account")
    assert classify_text("Your personal and contact information.")[0] == "instruction_text"
    assert classify_text("FIRST NAME")[0] == "field_label"
    assert classify_text("Save changes")[0] == "button_text"
    assert classify_text("Savechanges")[0] == "button_text"


def test_false_card_candidates_are_removed_by_deduplication() -> None:
    image = Image.new("RGB", (500, 500), "white")
    ids = IdGenerator()
    viewport = Region("R1", "web_viewport", {"x": 0, "y": 0, "width": 500, "height": 500}, {})
    text_blocks = [
        TextBlock("T1", "Account", {"x": 120, "y": 100, "width": 80, "height": 24}, {}, 0.9, "test"),
        TextBlock("T2", "Account", {"x": 122, "y": 106, "width": 82, "height": 24}, {}, 0.9, "test"),
    ]
    classify_text_blocks(text_blocks)
    cards, removed = detect_card_regions(image, viewport, [], text_blocks, ids, [])
    assert len(cards) == 1
    assert removed


def test_account_instruction_text_does_not_create_contact_card() -> None:
    image = Image.new("RGB", (500, 500), "white")
    ids = IdGenerator()
    viewport = Region("R1", "web_viewport", {"x": 0, "y": 0, "width": 500, "height": 500}, {})
    text_blocks = [
        TextBlock("T1", "Account", {"x": 120, "y": 100, "width": 80, "height": 24}, {}, 0.9, "test"),
        TextBlock(
            "T2",
            "Your personal and contact information.",
            {"x": 120, "y": 132, "width": 250, "height": 18},
            {},
            0.9,
            "test",
        ),
    ]
    classify_text_blocks(text_blocks)
    cards, _removed = detect_card_regions(image, viewport, [], text_blocks, ids, [])
    assert [card.region_type_hint for card in cards] == ["account_section"]


def test_email_notifications_and_save_changes_do_not_create_cards() -> None:
    image = Image.new("RGB", (500, 500), "white")
    ids = IdGenerator()
    viewport = Region("R1", "web_viewport", {"x": 0, "y": 0, "width": 500, "height": 500}, {})
    text_blocks = [
        TextBlock("T1", "Notification preferences", {"x": 120, "y": 100, "width": 190, "height": 24}, {}, 0.9, "test"),
        TextBlock("T2", "Email notifications", {"x": 120, "y": 150, "width": 160, "height": 18}, {}, 0.9, "test"),
        TextBlock("T3", "Save changes", {"x": 120, "y": 220, "width": 120, "height": 24}, {}, 0.9, "test"),
    ]
    classify_text_blocks(text_blocks)
    cards, _removed = detect_card_regions(image, viewport, [], text_blocks, ids, [])
    assert [card.region_type_hint for card in cards] == ["notification_section"]


def test_element_label_assignment_prefers_field_label_over_section_title() -> None:
    element = Element(
        "E1",
        "R1",
        "input_like",
        {"x": 100, "y": 150, "width": 160, "height": 28},
        {},
        {},
        {},
    )
    text_blocks = [
        TextBlock("T1", "Contact", {"x": 100, "y": 90, "width": 80, "height": 24}, {}, 0.9, "test"),
        TextBlock("T2", "Email", {"x": 100, "y": 126, "width": 60, "height": 18}, {}, 0.9, "test"),
    ]
    classify_text_blocks(text_blocks)
    associate_text([element], text_blocks, lambda: "REL1")
    assert element.label_text == "Email"


def test_region_relationships_do_not_create_cycles() -> None:
    regions = [
        Region("R1", "model_input_region", {"x": 0, "y": 0, "width": 500, "height": 500}, {}),
        Region("R6", "browser_viewport", {"x": 0, "y": 40, "width": 500, "height": 420}, {}),
        Region("R7", "web_viewport", {"x": 20, "y": 60, "width": 460, "height": 380}, {}),
        Region("R8", "business_content_area", {"x": 80, "y": 80, "width": 320, "height": 330}, {}),
        Region("R9", "account_section", {"x": 100, "y": 100, "width": 280, "height": 120}, {}),
    ]
    relationships = build_region_relationships(regions, lambda: f"REL{len(regions)}")
    pairs = {
        (relationship.source_id, relationship.target_id)
        for relationship in relationships
        if relationship.relationship_type == "region_contains_region"
    }
    assert ("R6", "R7") in pairs
    assert ("R7", "R6") not in pairs


def test_perception_report_includes_region_tree(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    fixture_dir = tmp_path / "tests" / "fixtures"
    fixture_dir.mkdir(parents=True)
    image_path = fixture_dir / "latest_capture.png"
    Image.new("RGB", (320, 240), "white").save(image_path)
    runtime_dir = tmp_path / "runtime_state"
    runtime_dir.mkdir()
    (runtime_dir / "latest_runtime_context.json").write_text(
        json.dumps(
            {
                "screenshot_path": str(image_path),
                "model_input_region": {"x": 0, "y": 0, "width": 320, "height": 240},
            }
        ),
        encoding="utf-8",
    )
    build_layout_index(ocr_backend="disabled")
    report = json.loads(Path("runtime_state/latest_perception_report.json").read_text())
    assert "region_tree" in report


def test_detector_interface_returns_detector_result() -> None:
    result = DetectorResult(detector_name="test", score=0.1, possible_page_type="test_page")
    assert result.to_dict()["detector_name"] == "test"
    assert result.score == 0.1


def test_form_detector_scores_when_card_regions_exist() -> None:
    card = Region("R9", "account_section", {"x": 0, "y": 0, "width": 200, "height": 120}, {})
    card.metadata["is_true_business_card"] = True
    element = Element(
        "E1",
        "R9",
        "input_like",
        {"x": 20, "y": 40, "width": 100, "height": 20},
        {},
        {},
        {},
    )
    text = TextBlock("T1", "Account", {"x": 20, "y": 10, "width": 80, "height": 20}, {}, 0.9, "test")
    text.metadata["text_role"] = "section_title"
    result = run_form_detector([card], [element], [text])
    assert result.score > 0
    assert result.possible_page_type == "form"
    assert result.region_ids == ["R9"]


def test_stub_detector_returns_zero_score_and_warning() -> None:
    result = run_drag_drop_detector([], [], [])
    assert result.score == 0.0
    assert result.warnings == ["Detector not implemented yet."]


def test_detector_scores_and_possible_page_types_select_form() -> None:
    card = Region("R9", "account_section", {"x": 0, "y": 0, "width": 200, "height": 120}, {})
    card.metadata["is_true_business_card"] = True
    results = run_detectors([card], [], [])
    scores = detector_scores(results)
    assert set(scores) == {"form", "survey", "image_task", "drag_drop", "matrix", "modal"}
    assert possible_page_types_from_scores(results)[0] == "form"


def test_layout_hints_includes_detector_scores(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    fixture_dir = tmp_path / "tests" / "fixtures"
    fixture_dir.mkdir(parents=True)
    image_path = fixture_dir / "latest_capture.png"
    Image.new("RGB", (320, 240), "white").save(image_path)
    runtime_dir = tmp_path / "runtime_state"
    runtime_dir.mkdir()
    (runtime_dir / "latest_runtime_context.json").write_text(
        json.dumps(
            {
                "screenshot_path": str(image_path),
                "model_input_region": {"x": 0, "y": 0, "width": 320, "height": 240},
            }
        ),
        encoding="utf-8",
    )
    layout = build_layout_index(ocr_backend="disabled")
    assert "detector_scores" in layout["layout_hints"]


def test_annotation_filtering_hides_low_confidence_browser_elements(tmp_path: Path) -> None:
    image = Image.new("RGB", (200, 120), "white")
    region = Region("R1", "header", {"x": 0, "y": 0, "width": 200, "height": 40}, {})
    element = Element(
        element_id="E1",
        region_id="R1",
        element_type_hint="button_like",
        bbox_raw={"x": 10, "y": 10, "width": 50, "height": 20},
        bbox_norm={},
        click_point_raw={},
        click_point_norm={},
        confidence=0.1,
    )
    output = save_annotated_overview(
        image,
        [region],
        [element],
        [],
        tmp_path / "filtered.png",
        show_browser_elements=False,
        show_low_confidence_elements=False,
        min_element_confidence_for_annotation=0.35,
    )
    assert output.exists()
