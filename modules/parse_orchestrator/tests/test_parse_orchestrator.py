from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from modules.parse_orchestrator.input_loader import load_layout_index
from modules.parse_orchestrator.ollama_evidence_parser import (
    build_evidence_payload,
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
