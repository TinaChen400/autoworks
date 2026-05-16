from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from modules.parse_orchestrator.input_loader import load_layout_index
from modules.parse_orchestrator.ollama_evidence_parser import (
    build_evidence_payload,
    parsed_page_from_compact_response,
    run_ollama_evidence_parse,
)
from modules.parse_orchestrator.metrics import build_metrics
from modules.parse_orchestrator.orchestrator import run_orchestrated_parse
from modules.parse_orchestrator.strategy_selector import select_strategy
from modules.parse_orchestrator.vision_runner import (
    MULTI_REGION_MVP_WARNING,
    run_vision_parser,
)


def _runtime_context(tmp_path: Path) -> dict:
    screenshot = tmp_path / "capture.png"
    Image.new("RGB", (320, 240), "white").save(screenshot)
    return {
        "task_id": "test_task",
        "task_type": "form",
        "screenshot_path": str(screenshot),
        "model_input_region": {"x": 0, "y": 0, "width": 320, "height": 240},
        "supported_question_types": ["unknown"],
    }


def _region(region_id: str, region_type: str = "card", safe: bool = True) -> dict:
    return {
        "region_id": region_id,
        "region_type_hint": region_type,
        "crop_path": f"runtime_state/crops/{region_id}.png",
        "annotated_crop_path": f"runtime_state/crops/{region_id}_annotated.png",
        "crop_quality": {
            "safe_for_detail_parse": safe,
            "crop_quality": "good" if safe else "risky",
            "fallback_recommendation": "use_annotated_overview",
            "content_touching_edges": not safe,
            "missing_question_context_possible": False,
            "possible_half_cut_text_or_controls": False,
        },
    }


def _layout(
    tmp_path: Path, *, scores: dict | None = None, recommended: list[str] | None = None
) -> dict:
    overview = tmp_path / "overview.png"
    Image.new("RGB", (320, 240), "white").save(overview)
    regions = [_region("R9"), _region("R10"), _region("R2", "header")]
    return {
        "annotated_overview": str(overview),
        "full_screenshot": {"path": _runtime_context(tmp_path)["screenshot_path"]},
        "regions": regions,
        "layout_hints": {
            "detector_scores": scores
            if scores is not None
            else {"form": 1.0, "survey": 0.0, "image_task": 0.0},
            "possible_page_types": ["form"],
            "recommended_regions_for_detail_parse": recommended
            if recommended is not None
            else ["R9", "R10", "R2"],
        },
    }


def _config() -> dict:
    return {
        "default_mode": "fake",
        "max_model_calls": 3,
        "prefer_annotated_crops": True,
        "include_annotated_overview_with_unsafe_crops": True,
        "fallback_to_full_screenshot": True,
        "safe_crop_required_for_crop_only_parse": True,
        "minimum_detector_score_for_direct_parse": 0.5,
        "allowed_parser_types": [
            "form",
            "survey",
            "image_task",
            "drag_drop",
            "matrix",
            "modal",
            "general",
            "scene_scan",
        ],
    }


def _layout_with_option_evidence(tmp_path: Path) -> dict:
    layout = _layout(tmp_path)
    layout["text_blocks"] = [
        {
            "text_id": "T1",
            "text": "Compared to what already exists?",
            "bbox_norm": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.04},
        },
        {
            "text_id": "T2",
            "text": "This is essentially the same as what already exists",
            "bbox_norm": {"x": 0.2, "y": 0.4, "width": 0.5, "height": 0.04},
            "associated_element_id": "E2",
            "associated_region_id": "R9",
        },
    ]
    layout["elements"] = [
        {
            "element_id": "E2",
            "region_id": "R9",
            "element_type_hint": "checkbox_like",
            "click_point_norm": {"x": 0.18, "y": 0.42},
        }
    ]
    layout["relationships"] = [
        {
            "relationship_id": "REL1",
            "relationship_type": "possible_option_label",
            "source_id": "T2",
            "target_id": "E2",
            "confidence": 0.7,
        }
    ]
    return layout


def _layout_with_yes_no_evidence(tmp_path: Path) -> dict:
    layout = _layout(tmp_path)
    layout["text_blocks"] = [
        {
            "text_id": "T1",
            "text": "Do you make benefits decisions?",
            "bbox_norm": {"x": 0.2, "y": 0.3, "width": 0.5, "height": 0.04},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T2",
            "text": "OYes",
            "bbox_norm": {"x": 0.22, "y": 0.42, "width": 0.08, "height": 0.04},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T3",
            "text": "ONo",
            "bbox_norm": {"x": 0.22, "y": 0.48, "width": 0.08, "height": 0.04},
            "associated_region_id": "R9",
        },
    ]
    layout["elements"] = [
        {
            "element_id": "E2",
            "region_id": "R9",
            "element_type_hint": "icon_like",
            "click_point_norm": {"x": 0.21, "y": 0.43},
        },
        {
            "element_id": "E3",
            "region_id": "R9",
            "element_type_hint": "icon_like",
            "click_point_norm": {"x": 0.21, "y": 0.49},
        },
    ]
    layout["relationships"] = [
        {
            "relationship_id": "REL1",
            "relationship_type": "nearby_text",
            "source_id": "T2",
            "target_id": "E2",
            "confidence": 0.35,
        },
        {
            "relationship_id": "REL2",
            "relationship_type": "nearby_text",
            "source_id": "T3",
            "target_id": "E3",
            "confidence": 0.35,
        },
    ]
    return layout


def _layout_with_two_yes_no_cards(tmp_path: Path) -> dict:
    layout = _layout_with_yes_no_evidence(tmp_path)
    layout["text_blocks"].extend(
        [
            {
                "text_id": "T4",
                "text": "Do you make benefits decisions?",
                "bbox_norm": {"x": 0.2, "y": 0.6, "width": 0.5, "height": 0.04},
                "associated_region_id": "R10",
            },
            {
                "text_id": "T5",
                "text": "OYes",
                "bbox_norm": {"x": 0.22, "y": 0.72, "width": 0.08, "height": 0.04},
                "associated_region_id": "R10",
            },
            {
                "text_id": "T6",
                "text": "ONo",
                "bbox_norm": {"x": 0.22, "y": 0.78, "width": 0.08, "height": 0.04},
                "associated_region_id": "R10",
            },
        ]
    )
    layout["elements"].extend(
        [
            {
                "element_id": "E5",
                "region_id": "R10",
                "element_type_hint": "icon_like",
                "click_point_norm": {"x": 0.21, "y": 0.73},
            },
            {
                "element_id": "E6",
                "region_id": "R10",
                "element_type_hint": "icon_like",
                "click_point_norm": {"x": 0.21, "y": 0.79},
            },
        ]
    )
    layout["relationships"].extend(
        [
            {
                "relationship_id": "REL3",
                "relationship_type": "nearby_text",
                "source_id": "T5",
                "target_id": "E5",
                "confidence": 0.35,
            },
            {
                "relationship_id": "REL4",
                "relationship_type": "nearby_text",
                "source_id": "T6",
                "target_id": "E6",
                "confidence": 0.35,
            },
        ]
    )
    return layout


def _layout_with_comparison_choice_evidence(tmp_path: Path) -> dict:
    layout = _layout(tmp_path)
    layout["text_blocks"] = [
        {
            "text_id": "T17",
            "text": "Fromthelistbelowwhichbestdescribesyourthinking about thisidea",
            "bbox_norm": {"x": 0.35, "y": 0.29, "width": 0.33, "height": 0.025},
            "associated_region_id": "R10",
        },
        {
            "text_id": "T18",
            "text": "compared towhat alreadyexisting on theVirginMediawebsite?Select",
            "bbox_norm": {"x": 0.35, "y": 0.32, "width": 0.34, "height": 0.026},
            "associated_region_id": "R10",
        },
        {
            "text_id": "T19",
            "text": "one answer only.",
            "bbox_norm": {"x": 0.35, "y": 0.35, "width": 0.08, "height": 0.022},
            "associated_region_id": "R10",
        },
        {
            "text_id": "T20",
            "text": "Concept:",
            "bbox_norm": {"x": 0.35, "y": 0.39, "width": 0.04, "height": 0.02},
            "associated_region_id": "R11",
        },
        {
            "text_id": "T21",
            "text": "an app designed to guide you through your entire broadband setup",
            "bbox_norm": {"x": 0.39, "y": 0.39, "width": 0.28, "height": 0.02},
            "associated_region_id": "R11",
        },
        {
            "text_id": "T25",
            "text": "OIdo not see anyreasontouse this",
            "bbox_norm": {"x": 0.36, "y": 0.51, "width": 0.13, "height": 0.022},
            "associated_region_id": "R11",
        },
        {
            "text_id": "T26",
            "text": "Whatexistsalreadyisbetterthan this",
            "bbox_norm": {"x": 0.37, "y": 0.57, "width": 0.13, "height": 0.019},
            "associated_region_id": "R12",
        },
        {
            "text_id": "T27",
            "text": "Thisisessentially the same aswhat already exists",
            "bbox_norm": {"x": 0.37, "y": 0.62, "width": 0.17, "height": 0.019},
            "associated_region_id": "R13",
        },
        {
            "text_id": "T28",
            "text": "Thiswouldbeslightlybetter thanwhatalready exists",
            "bbox_norm": {"x": 0.37, "y": 0.68, "width": 0.18, "height": 0.019},
            "associated_region_id": "R14",
        },
        {
            "text_id": "T29",
            "text": "Thiswouldbemuchmoreuseful thanwhatcurrentlyexists",
            "bbox_norm": {"x": 0.37, "y": 0.73, "width": 0.2, "height": 0.019},
            "associated_region_id": "R14",
        },
        {
            "text_id": "T31",
            "text": "Please explain your answer in detail:",
            "bbox_norm": {"x": 0.35, "y": 0.78, "width": 0.13, "height": 0.022},
            "associated_region_id": "R14",
        },
    ]
    layout["elements"] = [
        {
            "element_id": f"E{text_id[1:]}",
            "region_id": region_id,
            "element_type_hint": control_type,
            "click_point_norm": click_point,
        }
        for text_id, region_id, control_type, click_point in [
            ("T18", "R10", "unknown", {"x": 0.51, "y": 0.31}),
            ("T21", "R11", "icon_like", {"x": 0.5, "y": 0.4}),
            ("T25", "R11", "icon_like", {"x": 0.36, "y": 0.52}),
            ("T26", "R12", "checkbox_like", {"x": 0.36, "y": 0.58}),
            ("T27", "R13", "checkbox_like", {"x": 0.36, "y": 0.63}),
            ("T28", "R14", "unknown", {"x": 0.36, "y": 0.69}),
            ("T29", "R14", "input_like", {"x": 0.36, "y": 0.74}),
        ]
    ]
    layout["relationships"] = [
        {
            "relationship_id": f"REL{text_id[1:]}",
            "relationship_type": relationship_type,
            "source_id": text_id,
            "target_id": f"E{text_id[1:]}",
            "confidence": confidence,
        }
        for text_id, relationship_type, confidence in [
            ("T18", "nearby_text", 0.35),
            ("T21", "nearby_text", 0.35),
            ("T25", "nearby_text", 0.35),
            ("T26", "possible_option_label", 0.6),
            ("T27", "nearby_text", 0.35),
            ("T28", "nearby_text", 0.35),
            ("T29", "nearby_text", 0.35),
        ]
    ]
    return layout


def _layout_with_likert_choice_evidence(tmp_path: Path) -> dict:
    layout = _layout(tmp_path)
    layout["text_blocks"] = [
        {
            "text_id": "T10",
            "text": "How likely are you to use this service?",
            "bbox_norm": {"x": 0.32, "y": 0.24, "width": 0.28, "height": 0.03},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T11",
            "text": "Select one answer only.",
            "bbox_norm": {"x": 0.32, "y": 0.28, "width": 0.16, "height": 0.025},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T20",
            "text": "Very unlikely",
            "bbox_norm": {"x": 0.36, "y": 0.38, "width": 0.1, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T21",
            "text": "Unlikely",
            "bbox_norm": {"x": 0.36, "y": 0.44, "width": 0.07, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T22",
            "text": "Neutral",
            "bbox_norm": {"x": 0.36, "y": 0.5, "width": 0.06, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T23",
            "text": "Likely",
            "bbox_norm": {"x": 0.36, "y": 0.56, "width": 0.05, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T24",
            "text": "Very likely",
            "bbox_norm": {"x": 0.36, "y": 0.62, "width": 0.09, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T30",
            "text": "Continue",
            "bbox_norm": {"x": 0.65, "y": 0.9, "width": 0.05, "height": 0.02},
            "associated_region_id": "R10",
        },
    ]
    layout["elements"] = [
        {
            "element_id": f"E{text_id[1:]}",
            "region_id": "R9",
            "element_type_hint": "icon_like",
            "click_point_norm": {"x": 0.34, "y": y + 0.01},
        }
        for text_id, y in [
            ("T20", 0.38),
            ("T21", 0.44),
            ("T22", 0.5),
            ("T23", 0.56),
            ("T24", 0.62),
        ]
    ]
    layout["relationships"] = [
        {
            "relationship_id": f"REL{text_id[1:]}",
            "relationship_type": "nearby_text",
            "source_id": text_id,
            "target_id": f"E{text_id[1:]}",
            "confidence": 0.35,
        }
        for text_id in ["T20", "T21", "T22", "T23", "T24"]
    ]
    return layout


def _layout_with_concept_then_choice_evidence(tmp_path: Path) -> dict:
    layout = _layout(tmp_path)
    layout["text_blocks"] = [
        {
            "text_id": "T10",
            "text": "What best describes your reaction to this idea?",
            "bbox_norm": {"x": 0.32, "y": 0.22, "width": 0.34, "height": 0.03},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T11",
            "text": "Concept:",
            "bbox_norm": {"x": 0.32, "y": 0.31, "width": 0.05, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T12",
            "text": "This service would keep all setup steps in one place.",
            "bbox_norm": {"x": 0.38, "y": 0.31, "width": 0.28, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T20",
            "text": "Strongly disagree",
            "bbox_norm": {"x": 0.36, "y": 0.44, "width": 0.12, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T21",
            "text": "Disagree",
            "bbox_norm": {"x": 0.36, "y": 0.5, "width": 0.07, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T22",
            "text": "Agree",
            "bbox_norm": {"x": 0.36, "y": 0.56, "width": 0.05, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T23",
            "text": "Strongly agree",
            "bbox_norm": {"x": 0.36, "y": 0.62, "width": 0.11, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T31",
            "text": "Please explain your answer in detail:",
            "bbox_norm": {"x": 0.32, "y": 0.7, "width": 0.18, "height": 0.02},
            "associated_region_id": "R9",
        },
        {
            "text_id": "T32",
            "text": "Type your response here",
            "bbox_norm": {"x": 0.34, "y": 0.75, "width": 0.12, "height": 0.02},
            "associated_region_id": "R9",
        },
    ]
    layout["elements"] = [
        {
            "element_id": f"E{text_id[1:]}",
            "region_id": "R9",
            "element_type_hint": "checkbox_like",
            "click_point_norm": {"x": 0.34, "y": y + 0.01},
        }
        for text_id, y in [
            ("T20", 0.44),
            ("T21", 0.5),
            ("T22", 0.56),
            ("T23", 0.62),
        ]
    ]
    layout["relationships"] = [
        {
            "relationship_id": f"REL{text_id[1:]}",
            "relationship_type": "possible_option_label",
            "source_id": text_id,
            "target_id": f"E{text_id[1:]}",
            "confidence": 0.6,
        }
        for text_id in ["T20", "T21", "T22", "T23"]
    ]
    return layout


def test_load_layout_index_fixture() -> None:
    layout = load_layout_index()
    assert layout["layout_hints"]["recommended_regions_for_detail_parse"]


def test_select_form_strategy_when_form_detector_highest(tmp_path: Path) -> None:
    plan, _ = select_strategy(_runtime_context(tmp_path), _layout(tmp_path), _config())
    assert plan.selected_strategy == "direct_region_parse"
    assert plan.selected_parser_type == "form"


def test_selected_regions_come_from_recommended_regions(tmp_path: Path) -> None:
    plan, _ = select_strategy(_runtime_context(tmp_path), _layout(tmp_path), _config())
    assert plan.selected_region_ids == ["R9", "R10"]


def test_unsafe_crop_triggers_fallback_policy(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    layout["regions"][0] = _region("R9", safe=False)
    plan, _ = select_strategy(_runtime_context(tmp_path), layout, _config())
    assert "R9" in plan.crop_safety_summary["unsafe_region_ids"]
    assert plan.use_annotated_overview is True


def test_severely_unsafe_crop_chooses_overview_strategy(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    unsafe = _region("R9", safe=False)
    unsafe["crop_quality"]["fallback_recommendation"] = "use_full_screenshot"
    layout["regions"][0] = unsafe
    plan, _ = select_strategy(_runtime_context(tmp_path), layout, _config())
    assert "R9" in plan.crop_safety_summary["severely_unsafe_region_ids"]
    assert plan.selected_strategy == "annotated_overview_parse"


def test_missing_layout_index_returns_clear_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match="Please run perception_indexer first."):
        load_layout_index(missing)


def test_fake_mode_produces_runtime_outputs() -> None:
    report = run_orchestrated_parse(mode="fake")
    assert report["selected_strategy"]
    assert Path("runtime_state/latest_parse_plan.json").exists()
    assert Path("runtime_state/latest_parse_metrics.json").exists()
    assert Path("runtime_state/latest_orchestrated_parse.json").exists()


def test_fake_mode_outputs_are_valid_json() -> None:
    run_orchestrated_parse(mode="fake")
    for path in [
        Path("runtime_state/latest_parse_plan.json"),
        Path("runtime_state/latest_parse_metrics.json"),
        Path("runtime_state/latest_orchestrated_parse.json"),
    ]:
        assert json.loads(path.read_text(encoding="utf-8"))


def test_zero_detector_scores_selects_general_annotated_overview(tmp_path: Path) -> None:
    layout = _layout(tmp_path, scores={"form": 0.0, "survey": 0.0}, recommended=["R9"])
    plan, _ = select_strategy(_runtime_context(tmp_path), layout, _config())
    assert plan.selected_strategy == "annotated_overview_parse"
    assert plan.selected_parser_type == "general"


def test_no_browser_header_footer_region_selected_when_business_cards_exist(tmp_path: Path) -> None:
    layout = _layout(tmp_path, recommended=["R2", "R9", "R10"])
    plan, _ = select_strategy(_runtime_context(tmp_path), layout, _config())
    assert "R2" not in plan.selected_region_ids
    assert plan.selected_region_ids == ["R9", "R10"]


def test_vision_runner_passes_parser_type_and_input_image(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_parse_latest_runtime_context(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {
            "page": {"page_type": "unknown", "confidence": 0.1},
            "questions": [],
            "navigation_buttons": [],
            "uncertainties": [],
        }

    monkeypatch.setattr(
        "modules.vision_parser.parser.parse_latest_runtime_context",
        fake_parse_latest_runtime_context,
    )
    result = run_vision_parser(
        {
            "selected_mode": "fake",
            "selected_parser_type": "form",
            "selected_input_images": ["runtime_state/crops/R9_card_license_annotated.png"],
        }
    )

    assert captured["mode"] == "fake"
    assert captured["parser_type"] == "form"
    assert captured["output_level"] == "standard"
    assert captured["input_image"] == "runtime_state/crops/R9_card_license_annotated.png"
    assert result.model_calls_count == 1


def test_vision_runner_passes_light_output_level_for_doubao(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_parse_latest_runtime_context(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {
            "page": {"page_type": "unknown", "confidence": 0.1},
            "questions": [],
            "navigation_buttons": [],
            "uncertainties": [],
        }

    monkeypatch.setattr(
        "modules.vision_parser.parser.parse_latest_runtime_context",
        fake_parse_latest_runtime_context,
    )
    run_vision_parser(
        {
            "selected_mode": "doubao",
            "selected_parser_type": "form",
            "selected_input_images": ["runtime_state/crops/R9_card_license_annotated.png"],
        }
    )

    assert captured["mode"] == "doubao"
    assert captured["output_level"] == "light"


def test_select_strategy_accepts_fake_output_level_config(tmp_path: Path) -> None:
    config = _config()
    config["output_level"] = "light"
    plan, _ = select_strategy(_runtime_context(tmp_path), _layout(tmp_path), config, mode="fake")

    assert plan.selected_mode == "fake"
    assert plan.selected_output_level == "light"


def test_ollama_evidence_payload_keeps_text_control_relationships(tmp_path: Path) -> None:
    evidence = build_evidence_payload(
        _layout_with_option_evidence(tmp_path),
        _runtime_context(tmp_path),
        _config(),
        {"selected_region_ids": ["R9", "R10"]},
    )

    assert evidence["option_candidates"] == [
        {
            "text_id": "T2",
            "text": "This is essentially the same as what already exists",
            "control_element_id": "E2",
            "control_type": "checkbox_like",
            "relationship_type": "possible_option_label",
            "confidence": 0.7,
            "text_bbox_norm": {"x": 0.2, "y": 0.4, "width": 0.5, "height": 0.04},
            "control_click_point_norm": {"x": 0.18, "y": 0.42},
        }
    ]


def test_ollama_evidence_parse_returns_grounded_parsed_page(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_call_ollama(**_kwargs: object) -> str:
        return json.dumps(
            {
                "page_type": "questionnaire",
                "question_type": "single_choice",
                "question_text_ids": ["T1"],
                "option_text_ids": ["T2"],
                "confidence": 0.9,
                "uncertainties": [],
            }
        )

    monkeypatch.setattr(
        "modules.parse_orchestrator.ollama_evidence_parser.call_ollama",
        fake_call_ollama,
    )

    result = run_ollama_evidence_parse(
        {"task_id": "test_task", "selected_parser_type": "survey"},
        _layout_with_option_evidence(tmp_path),
        _runtime_context(tmp_path),
        _config(),
    )

    assert result.validation_passed is True
    assert result.model_calls_count == 1
    assert result.parsed_page["metadata"]["source"] == "ollama_evidence_parse"
    assert result.parsed_page["questions"][0]["answer_options"][0]["control_element_id"] == "E2"


def test_ollama_evidence_parse_repairs_yes_no_response_drift(tmp_path: Path) -> None:
    layout = _layout_with_yes_no_evidence(tmp_path)
    evidence = build_evidence_payload(
        layout,
        _runtime_context(tmp_path),
        _config(),
        {"selected_region_ids": ["R9"]},
    )

    parsed = parsed_page_from_compact_response(
        json.dumps(
            {
                "texts_and_elements": [
                    {"text": "Do you make benefits decisions?", "element_id": "E1"},
                    {"text": "OYes", "element_id": "E2"},
                    {"text": "ONo", "element_id": "E3"},
                ]
            }
        ),
        evidence,
        _runtime_context(tmp_path),
    )

    question = parsed["questions"][0]
    assert question["question_stem"]["text"] == "Do you make benefits decisions?"
    assert [option["option_id"] for option in question["answer_options"]] == ["T2", "T3"]
    assert [option["text"] for option in question["answer_options"]] == ["Yes", "No"]
    assert [option["raw_text"] for option in question["answer_options"]] == ["OYes", "ONo"]
    assert parsed["requires_human_review"] is True
    assert question["requires_human_review"] is True


def test_ollama_evidence_parse_recovers_repeated_yes_no_cards(tmp_path: Path) -> None:
    layout = _layout_with_two_yes_no_cards(tmp_path)
    evidence = build_evidence_payload(
        layout,
        _runtime_context(tmp_path),
        _config(),
        {"selected_region_ids": ["R9", "R10"]},
    )

    parsed = parsed_page_from_compact_response(
        json.dumps({"form_elements": [{"type": "radio", "options": ["A", "B"]}]}),
        evidence,
        _runtime_context(tmp_path),
    )

    assert len(parsed["questions"]) == 2
    assert [question["question_id"] for question in parsed["questions"]] == ["q1", "q2"]
    assert [
        [option["option_id"] for option in question["answer_options"]]
        for question in parsed["questions"]
    ] == [["T2", "T3"], ["T5", "T6"]]
    assert parsed["requires_human_review"] is True
    assert all(question["requires_human_review"] is True for question in parsed["questions"])
    assert "duplicate_yes_no_card_stack" in {
        uncertainty["type"] for uncertainty in parsed["uncertainties"]
    }


def test_ollama_evidence_parse_repairs_comparison_choice_response_drift(tmp_path: Path) -> None:
    layout = _layout_with_comparison_choice_evidence(tmp_path)
    evidence = build_evidence_payload(
        layout,
        _runtime_context(tmp_path),
        _config(),
        {"selected_region_ids": ["R10", "R11", "R12", "R13", "R14"]},
    )

    parsed = parsed_page_from_compact_response(
        json.dumps({"form_elements": [{"type": "radio", "options": ["A", "B"]}]}),
        evidence,
        _runtime_context(tmp_path),
    )

    question = parsed["questions"][0]
    assert question["question_type"] == "single_choice"
    assert question["question_stem"]["text"] == (
        "Fromthelistbelowwhichbestdescribesyourthinking about thisidea "
        "compared towhat alreadyexisting on theVirginMediawebsite?Select "
        "one answer only."
    )
    assert [option["option_id"] for option in question["answer_options"]] == [
        "T25",
        "T26",
        "T27",
        "T28",
        "T29",
    ]
    assert [option["control_element_id"] for option in question["answer_options"]] == [
        "E25",
        "E26",
        "E27",
        "E28",
        "E29",
    ]


def test_ollama_evidence_parse_repairs_generic_likert_choice_response_drift(tmp_path: Path) -> None:
    layout = _layout_with_likert_choice_evidence(tmp_path)
    evidence = build_evidence_payload(
        layout,
        _runtime_context(tmp_path),
        _config(),
        {"selected_region_ids": ["R9", "R10"]},
    )

    parsed = parsed_page_from_compact_response(
        json.dumps({"fields": [{"label": "unusable model response"}]}),
        evidence,
        _runtime_context(tmp_path),
    )

    question = parsed["questions"][0]
    assert question["question_stem"]["text"] == "How likely are you to use this service? Select one answer only."
    assert [option["text"] for option in question["answer_options"]] == [
        "Very unlikely",
        "Unlikely",
        "Neutral",
        "Likely",
        "Very likely",
    ]


def test_ollama_evidence_parse_repairs_choice_after_concept_before_text_input(tmp_path: Path) -> None:
    layout = _layout_with_concept_then_choice_evidence(tmp_path)
    evidence = build_evidence_payload(
        layout,
        _runtime_context(tmp_path),
        _config(),
        {"selected_region_ids": ["R9"]},
    )

    parsed = parsed_page_from_compact_response(
        json.dumps({"fields": [{"label": "unusable model response"}]}),
        evidence,
        _runtime_context(tmp_path),
    )

    question = parsed["questions"][0]
    assert question["question_stem"]["text"] == "What best describes your reaction to this idea?"
    assert [option["option_id"] for option in question["answer_options"]] == ["T20", "T21", "T22", "T23"]


def test_orchestrator_uses_ollama_evidence_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_context = _runtime_context(tmp_path)
    layout = _layout_with_option_evidence(tmp_path)
    captured = {}

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: runtime_context,
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_layout_index", lambda: layout)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_parse_plan", lambda _p: None)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_parse_metrics", lambda _m: None)
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.save_orchestrated_parse",
        lambda _p: None,
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_report", lambda _r: None)

    def fake_run_ollama(plan: dict, layout_index: dict, runtime_context: dict, config: dict) -> object:
        from modules.parse_orchestrator.ollama_evidence_parser import OllamaEvidenceResult

        captured["mode"] = plan["selected_mode"]
        return OllamaEvidenceResult(
            parsed_page={
                "page": {"page_type": "questionnaire", "confidence": 0.9},
                "questions": [
                    {
                        "question_id": "q1",
                        "question_type": "single_choice",
                        "question_stem": {"text": "Question?"},
                        "answer_options": [{"option_id": "T2", "text": "Option"}],
                    }
                ],
            },
            validation_report={"validation_passed": True},
            model_calls_count=1,
            validation_passed=True,
        )

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.run_ollama_evidence_parse",
        fake_run_ollama,
    )

    report = run_orchestrated_parse(mode="ollama")

    assert captured["mode"] == "ollama"
    assert report["model_calls_count"] == 1
    assert report["validation_passed"] is True
    assert report["requires_human_review"] is False


def test_orchestrator_propagates_parsed_page_human_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_context = _runtime_context(tmp_path)
    layout = _layout_with_option_evidence(tmp_path)

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: runtime_context,
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_layout_index", lambda: layout)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_parse_plan", lambda _p: None)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_parse_metrics", lambda _m: None)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_orchestrated_parse", lambda _p: None)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_report", lambda _r: None)

    def fake_run_ollama(plan: dict, layout_index: dict, runtime_context: dict, config: dict) -> object:
        from modules.parse_orchestrator.ollama_evidence_parser import OllamaEvidenceResult

        return OllamaEvidenceResult(
            parsed_page={
                "requires_human_review": True,
                "page": {"page_type": "questionnaire", "confidence": 0.9},
                "questions": [
                    {
                        "question_id": "q1",
                        "question_type": "single_choice",
                        "question_stem": {"text": "Question?"},
                        "answer_options": [{"option_id": "T2", "text": "Option"}],
                        "requires_human_review": True,
                    }
                ],
            },
            validation_report={"validation_passed": True},
            model_calls_count=1,
            validation_passed=True,
        )

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.run_ollama_evidence_parse",
        fake_run_ollama,
    )

    report = run_orchestrated_parse(mode="ollama")

    assert report["validation_passed"] is True
    assert report["requires_human_review"] is True


def test_orchestrator_does_not_doubao_fallback_after_ollama_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_context = _runtime_context(tmp_path)
    layout = _layout_with_option_evidence(tmp_path)
    called_vision = False

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: runtime_context,
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_layout_index", lambda: layout)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_parse_plan", lambda _p: None)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_parse_metrics", lambda _m: None)
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.save_orchestrated_parse",
        lambda _p: None,
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_report", lambda _r: None)

    def fake_run_ollama(*_args: object, **_kwargs: object) -> object:
        from modules.parse_orchestrator.ollama_evidence_parser import OllamaEvidenceResult

        return OllamaEvidenceResult(
            parsed_page={"page": {"page_type": "unknown", "confidence": 0.0}, "questions": []},
            validation_report={"validation_passed": False},
            model_calls_count=1,
            validation_passed=False,
            error="empty ollama parse",
        )

    def fake_run_vision_parser(_plan: dict) -> object:
        nonlocal called_vision
        called_vision = True
        raise AssertionError("Ollama mode should not silently fallback to Doubao.")

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.run_ollama_evidence_parse",
        fake_run_ollama,
    )
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.run_vision_parser",
        fake_run_vision_parser,
    )

    report = run_orchestrated_parse(mode="ollama")

    assert called_vision is False
    assert report["model_calls_count"] == 1
    assert report["requires_human_review"] is True


def test_vision_runner_warns_multi_region_mvp(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_parse_latest_runtime_context(**kwargs: object) -> dict:
        return {
            "page": {"page_type": "unknown", "confidence": 0.1},
            "questions": [],
            "navigation_buttons": [],
            "uncertainties": [],
        }

    monkeypatch.setattr(
        "modules.vision_parser.parser.parse_latest_runtime_context",
        fake_parse_latest_runtime_context,
    )
    result = run_vision_parser(
        {
            "selected_mode": "fake",
            "selected_parser_type": "form",
            "selected_input_images": ["a.png", "b.png"],
        }
    )

    assert MULTI_REGION_MVP_WARNING in result.warnings


def test_metrics_accepts_validation_passed_key(tmp_path: Path) -> None:
    metrics = build_metrics(
        plan={"plan_id": "p1", "selected_input_images": []},
        parsed_page={"page": {"page_type": "form", "confidence": 0.9}},
        validation_report={"validation_passed": True},
        model_calls_count=1,
        elapsed_time_ms=1,
        fallback_used=False,
        fallback_reason="",
        warnings=[],
    )

    assert metrics.validation_passed is True


def test_orchestrator_falls_back_to_doubao_overview_for_non_actionable_parse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_context = _runtime_context(tmp_path)
    layout = _layout(tmp_path)
    calls: list[dict] = []

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: runtime_context,
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_layout_index", lambda: layout)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_parse_plan", lambda _p: None)
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.save_parse_metrics",
        lambda _m: None,
    )
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.save_orchestrated_parse",
        lambda _p: None,
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_report", lambda _r: None)

    def fake_run_vision_parser(plan: dict) -> object:
        calls.append(plan)
        if plan["selected_mode"] == "doubao":
            parsed = {
                "page": {"page_type": "form", "confidence": 0.9},
                "questions": [
                    {
                        "question_id": "q1",
                        "question_type": "single_choice",
                        "question_stem": {"text": "Question?"},
                        "answer_options": [{"option_id": "a1", "text": "Yes"}],
                    }
                ],
            }
        else:
            parsed = {"page": {"page_type": "unknown", "confidence": 0.1}, "questions": []}
        from modules.parse_orchestrator.vision_runner import VisionRunResult

        return VisionRunResult(
            parsed_page=parsed,
            validation_report={"validation_passed": True},
            model_calls_count=1,
        )

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.run_vision_parser",
        fake_run_vision_parser,
    )

    report = run_orchestrated_parse(mode="fake")

    assert len(calls) == 2
    assert calls[1]["selected_mode"] == "doubao"
    assert calls[1]["selected_input_images"] == [str(layout["annotated_overview"])]
    assert report["validation_passed"] is True
    assert report["requires_human_review"] is False


def test_orchestrator_reports_failed_doubao_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_context = _runtime_context(tmp_path)
    layout = _layout(tmp_path)

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: runtime_context,
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_layout_index", lambda: layout)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_parse_plan", lambda _p: None)
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.save_parse_metrics",
        lambda _m: None,
    )
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.save_orchestrated_parse",
        lambda _p: None,
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.save_report", lambda _r: None)

    def fake_run_vision_parser(plan: dict) -> object:
        from modules.parse_orchestrator.vision_runner import VisionRunResult

        if plan["selected_mode"] == "doubao":
            return VisionRunResult(
                parsed_page={"page": {"page_type": "unknown"}, "questions": []},
                validation_report={"validation_passed": False},
                model_calls_count=1,
                error="network timeout",
            )
        return VisionRunResult(
            parsed_page={"page": {"page_type": "unknown"}, "questions": []},
            validation_report={"validation_passed": True},
            model_calls_count=1,
        )

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.run_vision_parser",
        fake_run_vision_parser,
    )

    report = run_orchestrated_parse(mode="fake")

    assert report["requires_human_review"] is True
    assert report["model_calls_count"] == 2
    assert "Doubao fallback failed: network timeout" in report["warnings"]
