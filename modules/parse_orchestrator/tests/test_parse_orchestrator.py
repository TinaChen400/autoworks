from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from modules.parse_orchestrator.input_loader import load_layout_index
from modules.parse_orchestrator.metrics import build_metrics
from modules.parse_orchestrator.orchestrator import run_orchestrated_parse
from modules.parse_orchestrator.parse_plan_store import ORCHESTRATED_PARSE_PATH
from modules.parse_orchestrator.strategy_selector import select_strategy
from modules.parse_orchestrator.vision_runner import (
    MULTI_REGION_MVP_WARNING,
    PARSED_PAGE_PATH,
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


def test_metrics_prefers_validation_passed_field() -> None:
    metrics = build_metrics(
        plan={},
        parsed_page={},
        validation_report={"validation_passed": True, "valid": False, "errors": []},
        model_calls_count=1,
        elapsed_time_ms=0,
        fallback_used=False,
        fallback_reason="",
        warnings=[],
    )

    assert metrics.validation_passed is True


def test_metrics_accepts_legacy_valid_field() -> None:
    metrics = build_metrics(
        plan={},
        parsed_page={},
        validation_report={"valid": True, "errors": []},
        model_calls_count=1,
        elapsed_time_ms=0,
        fallback_used=False,
        fallback_reason="",
        warnings=[],
    )

    assert metrics.validation_passed is True


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


def test_vision_runner_current_failure_does_not_reuse_stale_parsed_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    PARSED_PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARSED_PAGE_PATH.write_text(
        json.dumps(
            {
                "parse_id": "old_parse",
                "task_id": "old_task",
                "page": {"page_type": "form", "language": "en", "page_status": "active_question_page", "confidence": 0.9},
                "questions": [
                    {
                        "question_id": "old_like_dislike",
                        "question_type": "text_input",
                        "question_stem": {"text": "What did you like or dislike?", "bbox_norm": None},
                    }
                ],
                "navigation_buttons": [],
                "uncertainties": [],
            }
        ),
        encoding="utf-8",
    )

    def fail_parse_latest_runtime_context(**_kwargs: object) -> dict:
        raise RuntimeError("simulated current parse failure")

    monkeypatch.setattr(
        "modules.vision_parser.parser.parse_latest_runtime_context",
        fail_parse_latest_runtime_context,
    )
    result = run_vision_parser(
        {
            "task_id": "current_task",
            "selected_mode": "fake",
            "selected_parser_type": "survey",
            "selected_input_images": ["runtime_state/crops/R9_card_license_annotated.png"],
        }
    )

    assert result.validation_passed is False
    assert result.parsed_page["task_id"] == "current_task"
    assert result.parsed_page["page"]["page_status"] == "parse_failed"
    assert result.parsed_page["questions"] == []
    assert result.parsed_page["metadata"]["parse_failed"] is True
    assert result.parsed_page["metadata"]["selected_parser_type"] == "survey"
    assert result.parsed_page["uncertainties"][0]["message"] == "simulated current parse failure"


def test_orchestrated_parse_failure_excludes_stale_like_dislike_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    PARSED_PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARSED_PAGE_PATH.write_text(
        json.dumps(
            {
                "parse_id": "old_parse",
                "task_id": "old_task",
                "page": {"page_type": "form", "language": "en", "page_status": "active_question_page", "confidence": 0.9},
                "questions": [
                    {
                        "question_id": "old_like_dislike",
                        "question_type": "text_input",
                        "question_stem": {"text": "What did you like or dislike?", "bbox_norm": None},
                    }
                ],
                "navigation_buttons": [],
                "uncertainties": [],
            }
        ),
        encoding="utf-8",
    )

    def fail_parse_latest_runtime_context(**_kwargs: object) -> dict:
        raise RuntimeError("simulated current parse failure")

    monkeypatch.setattr(
        "modules.vision_parser.parser.parse_latest_runtime_context",
        fail_parse_latest_runtime_context,
    )

    report = run_orchestrated_parse(mode="fake")
    orchestrated = json.loads(ORCHESTRATED_PARSE_PATH.read_text(encoding="utf-8"))

    assert report["requires_human_review"] is True
    assert orchestrated["requires_human_review"] is True
    assert orchestrated["parsed_page"]["page"]["page_status"] == "parse_failed"
    assert orchestrated["parsed_page"]["questions"] == []
    assert "like or dislike" not in json.dumps(orchestrated["parsed_page"])
