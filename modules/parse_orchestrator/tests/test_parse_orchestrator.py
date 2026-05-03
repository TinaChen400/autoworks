from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from modules.parse_orchestrator.input_loader import load_layout_index
from modules.parse_orchestrator.orchestrator import run_orchestrated_parse
from modules.parse_orchestrator.strategy_selector import select_strategy


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
