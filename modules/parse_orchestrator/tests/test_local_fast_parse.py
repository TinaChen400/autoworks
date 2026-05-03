from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from modules.parse_orchestrator.local_form_parser import parse_form_layout
from modules.parse_orchestrator.local_parse_quality import detect_survey_signals, score_local_parse
from modules.parse_orchestrator.local_survey_parser import parse_survey_layout
from modules.parse_orchestrator.orchestrator import run_orchestrated_parse


def _runtime_context(tmp_path: Path) -> dict:
    screenshot = tmp_path / "capture.png"
    Image.new("RGB", (320, 240), "white").save(screenshot)
    return {"task_id": "task_local", "task_type": "form", "screenshot_path": str(screenshot)}


def _box(x: float, y: float, width: float = 0.1, height: float = 0.04) -> dict:
    return {"x": x, "y": y, "width": width, "height": height}


def _layout(tmp_path: Path, *, empty_ocr: bool = False, score: float = 0.95) -> dict:
    overview = tmp_path / "overview.png"
    Image.new("RGB", (320, 240), "white").save(overview)
    text_blocks = [] if empty_ocr else [
        {
            "text_id": "T1",
            "text": "Account",
            "bbox_norm": _box(0.12, 0.12),
            "associated_region_id": "R10",
            "metadata": {"text_role": "section_title"},
        },
        {
            "text_id": "T2",
            "text": "Use your contact information.",
            "bbox_norm": _box(0.12, 0.18, 0.3),
            "associated_region_id": "R10",
            "metadata": {"text_role": "instruction_text"},
        },
        {
            "text_id": "T3",
            "text": "Email",
            "bbox_norm": _box(0.12, 0.28),
            "associated_region_id": "R10",
            "metadata": {"text_role": "field_label"},
        },
        {
            "text_id": "T4",
            "text": "Continue",
            "bbox_norm": _box(0.56, 0.72),
            "associated_region_id": "R10",
            "metadata": {"text_role": "button_text"},
        },
    ]
    return {
        "annotated_overview": str(overview),
        "full_screenshot": {"path": _runtime_context(tmp_path)["screenshot_path"]},
        "regions": [
            {
                "region_id": "R10",
                "region_type_hint": "card",
                "bbox_norm": _box(0.1, 0.1, 0.8, 0.8),
                "text_ids": [block["text_id"] for block in text_blocks],
                "element_ids": ["E1", "E2"],
                "crop_quality": {
                    "safe_for_detail_parse": True,
                    "fallback_recommendation": "none",
                },
                "metadata": {"section_title_text": "Account"},
            }
        ],
        "elements": [
            {
                "element_id": "E1",
                "region_id": "R10",
                "element_type_hint": "input_like",
                "bbox_norm": _box(0.32, 0.27, 0.3),
                "click_point_norm": {"x": 0.47, "y": 0.29},
                "associated_text_ids": ["T3"] if not empty_ocr else [],
                "label_text": "Email" if not empty_ocr else "",
            },
            {
                "element_id": "E2",
                "region_id": "R10",
                "element_type_hint": "button_like",
                "bbox_norm": _box(0.55, 0.7, 0.16),
                "click_point_norm": {"x": 0.63, "y": 0.72},
                "associated_text_ids": ["T4"] if not empty_ocr else [],
                "label_text": "Continue" if not empty_ocr else "",
            },
        ],
        "text_blocks": text_blocks,
        "relationships": [],
        "layout_hints": {
            "detector_scores": {"form": score, "survey": 0.1},
            "possible_page_types": ["form"],
            "recommended_regions_for_detail_parse": ["R10"],
        },
    }


def _survey_layout(tmp_path: Path, *, with_options: bool = True) -> dict:
    overview = tmp_path / "survey_overview.png"
    Image.new("RGB", (320, 240), "white").save(overview)
    options = [
        ("T3", "Amazon Central", 0.42),
        ("T4", "Amazon Seller", 0.48),
        ("T5", "Seller Central", 0.54),
        ("T6", "Supplier Central", 0.60),
        ("T7", "Vendor Central", 0.66),
        ("T8", "All of the above", 0.72),
    ] if with_options else []
    text_blocks = [
        {
            "text_id": "T1",
            "text": "Which of the following accounts do you have experience using?",
            "bbox_norm": _box(0.16, 0.20, 0.62, 0.06),
            "associated_region_id": "R10",
            "metadata": {"text_role": "question_stem"},
        },
        {
            "text_id": "T2",
            "text": "Please select all that apply.",
            "bbox_norm": _box(0.16, 0.30, 0.34),
            "associated_region_id": "R10",
            "metadata": {"text_role": "instruction_text"},
        },
        *[
            {
                "text_id": text_id,
                "text": text,
                "bbox_norm": _box(0.22, y, 0.25),
                "associated_region_id": "R10",
                "metadata": {"text_role": "unknown"},
            }
            for text_id, text, y in options
        ],
        {
            "text_id": "T9",
            "text": "Next",
            "bbox_norm": _box(0.70, 0.82, 0.12),
            "associated_region_id": "R10",
            "metadata": {"text_role": "button_text"},
        },
    ]
    elements = [
        {
            "element_id": f"E{i}",
            "region_id": "R10",
            "element_type_hint": "input_like",
            "bbox_norm": _box(0.18, y, 0.03),
            "click_point_norm": {"x": 0.195, "y": y + 0.02},
            "associated_text_ids": [text_id],
            "label_text": text,
        }
        for i, (text_id, text, y) in enumerate(options, start=1)
    ]
    elements.append(
        {
            "element_id": "E99",
            "region_id": "R10",
            "element_type_hint": "button_like",
            "bbox_norm": _box(0.70, 0.80, 0.12),
            "click_point_norm": {"x": 0.76, "y": 0.82},
            "associated_text_ids": ["T9"],
            "label_text": "Next",
        }
    )
    return {
        "annotated_overview": str(overview),
        "full_screenshot": {"path": _runtime_context(tmp_path)["screenshot_path"]},
        "regions": [
            {
                "region_id": "R10",
                "region_type_hint": "card",
                "bbox_norm": _box(0.1, 0.1, 0.8, 0.8),
                "text_ids": [block["text_id"] for block in text_blocks],
                "element_ids": [element["element_id"] for element in elements],
                "crop_quality": {
                    "safe_for_detail_parse": True,
                    "fallback_recommendation": "none",
                },
                "metadata": {"section_title_text": ""},
            }
        ],
        "elements": elements,
        "text_blocks": text_blocks,
        "relationships": [],
        "layout_hints": {
            "detector_scores": {"form": 0.95, "survey": 0.2},
            "possible_page_types": ["form"],
            "recommended_regions_for_detail_parse": ["R10"],
        },
    }


def _compact_ocr_survey_layout(tmp_path: Path) -> dict:
    layout = _survey_layout(tmp_path)
    replacements = {
        "T1": "Whichof thefollowing accountsdoyouhaveexperience usingthatwecan provide tasksforyoutotryout?",
        "T2": "Pleaseselectallthatapply",
        "T3": "AmazonCentral",
        "T4": "AmazonSeller",
        "T8": "Allof the above",
    }
    for block in layout["text_blocks"]:
        if block["text_id"] in replacements:
            block["text"] = replacements[block["text_id"]]
            if block["text_id"] not in {"T1", "T2", "T9"}:
                block["metadata"] = {"text_role": "unknown"}
    for element in layout["elements"]:
        text_ids = element.get("associated_text_ids", [])
        if text_ids and text_ids[0] in replacements:
            element["label_text"] = replacements[text_ids[0]]
    layout["layout_hints"]["detector_scores"] = {"form": 0.95, "survey": 0.0}
    return layout


def _noisy_scoped_survey_layout(tmp_path: Path) -> dict:
    layout = _compact_ocr_survey_layout(tmp_path)
    noisy_blocks = [
        ("TB1", "X", 0.88, 0.18),
        ("TB2", "app.usertesting.com/my_dashboard/available_tests_v3", 0.30, 0.05),
        ("TB7", "锛塃NG", 0.96, 0.50),
        ("TB6", "锛塃NG", 0.24, 0.45),
        ("TB3", "测试乱码", 0.24, 0.44),
        ("TB4", "14:34", 0.82, 0.93),
        ("TB5", "03/05/2026", 0.88, 0.93),
        ("T10", "How would you describe your proficiency in English?", 0.22, 0.76),
        ("T11", "I do not speak English", 0.24, 0.80),
        ("T12", "Beginner", 0.24, 0.84),
        ("T13", "AmazonCentral", 0.22, 0.48),
        ("T14", "RetailCenter", 0.22, 0.36),
    ]
    for text_id, text, x, y in noisy_blocks:
        layout["text_blocks"].append(
            {
                "text_id": text_id,
                "text": text,
                "bbox_norm": _box(x, y, 0.25),
                "associated_region_id": "R10",
                "metadata": {"text_role": "unknown"},
            }
        )
        layout["regions"][0]["text_ids"].append(text_id)
    return layout


def _unclear_survey_layout(tmp_path: Path) -> dict:
    layout = _survey_layout(tmp_path)
    layout["text_blocks"] = [
        block for block in layout["text_blocks"] if block["text_id"] not in {"T1", "T2"}
    ]
    layout["regions"][0]["text_ids"] = [block["text_id"] for block in layout["text_blocks"]]
    return layout


def _config() -> dict:
    return {
        "default_mode": "fake",
        "max_model_calls": 3,
        "enable_local_fast_parse": True,
        "local_fast_parse_min_confidence": 0.7,
        "local_fast_parse_allowed_types": ["form", "survey"],
        "fallback_to_vision_parser_when_local_low_confidence": True,
        "minimum_detector_score_for_direct_parse": 0.5,
        "prefer_annotated_crops": True,
        "include_annotated_overview_with_unsafe_crops": True,
        "allowed_parser_types": ["form", "survey", "general"],
    }


def test_local_form_parser_extracts_form_sections_from_card_regions(tmp_path: Path) -> None:
    result = parse_form_layout(_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.95)
    sections = result["parsed_page"]["form_sections"]
    assert sections[0]["section_id"] == "R10"
    assert sections[0]["title"] == "Account"


def test_local_form_parser_extracts_input_fields_and_labels(tmp_path: Path) -> None:
    result = parse_form_layout(_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.95)
    fields = result["parsed_page"]["form_sections"][0]["input_fields"]
    assert fields[0]["field_id"] == "E1"
    assert fields[0]["label"] == "Email"
    assert fields[0]["field_type"] == "email"


def test_local_form_parser_extracts_buttons_and_text(tmp_path: Path) -> None:
    result = parse_form_layout(_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.95)
    buttons = result["parsed_page"]["navigation_buttons"]
    assert buttons[0]["button_id"] == "E2"
    assert buttons[0]["label"] == "Continue"
    assert buttons[0]["action"] == "continue"


def test_local_parse_quality_returns_high_confidence_for_good_form_layout(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    parsed = parse_form_layout(layout, _runtime_context(tmp_path), detector_score=0.95)["parsed_page"]
    quality = score_local_parse(layout, parsed, page_type="form", detector_score=0.95)
    assert quality["confidence"] >= 0.7
    assert quality["requires_remote_parse"] is False


def test_local_parse_quality_returns_low_confidence_when_ocr_empty(tmp_path: Path) -> None:
    layout = _layout(tmp_path, empty_ocr=True)
    parsed = parse_form_layout(layout, _runtime_context(tmp_path), detector_score=0.95)["parsed_page"]
    quality = score_local_parse(layout, parsed, page_type="form", detector_score=0.95)
    assert quality["confidence"] < 0.7
    assert quality["requires_remote_parse"] is True


def test_survey_text_select_all_is_not_parsed_as_form(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: _runtime_context(tmp_path),
    )
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_layout_index",
        lambda: _survey_layout(tmp_path),
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)

    report = run_orchestrated_parse(mode="fake", prefer_local=True)

    assert report["parse_source"] == "local_fast_parse"
    assert report["selected_parser_type"] == "form"
    assert report["local_page_type"] == "questionnaire"
    assert report["local_parse_confidence"] >= 0.7
    parsed = Path("runtime_state/latest_orchestrated_parse.json").read_text(encoding="utf-8")
    assert '"page_type": "questionnaire"' in parsed
    assert '"form_sections": []' in parsed


def test_compact_ocr_survey_routes_to_survey_on_orchestrator_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: _runtime_context(tmp_path),
    )
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_layout_index",
        lambda: _compact_ocr_survey_layout(tmp_path),
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)

    report = run_orchestrated_parse(mode="fake", prefer_local=True)
    local_parse = json.loads(Path("runtime_state/latest_local_parse.json").read_text(encoding="utf-8"))
    orchestrated = json.loads(
        Path("runtime_state/latest_orchestrated_parse.json").read_text(encoding="utf-8")
    )
    parsed_page = orchestrated["parsed_page"]

    assert report["parse_source"] == "local_fast_parse"
    assert report["local_page_type"] == "questionnaire"
    assert local_parse["selected_local_parser"] == "survey"
    assert local_parse["detector_override_applied"] is True
    assert "form_detector_overridden_by_survey_signals" in local_parse["warnings"]
    assert parsed_page["page"]["page_type"] == "questionnaire"
    assert parsed_page["questions"][0]["question_type"] == "multiple_choice"
    assert parsed_page["questions"][0]["answer_options"]
    assert parsed_page["form_sections"] == []
    assert report["model_calls_count"] == 0


def test_survey_options_are_extracted_as_answer_options(tmp_path: Path) -> None:
    result = parse_survey_layout(_survey_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.9)
    question = result["parsed_page"]["questions"][0]
    option_texts = [option["text"] for option in question["answer_options"]]
    assert "Amazon Central" in option_texts
    assert "All of the above" in option_texts
    assert result["parsed_page"]["form_sections"] == []


def test_multiple_choice_detected_from_select_all_that_apply(tmp_path: Path) -> None:
    result = parse_survey_layout(_survey_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.9)
    assert result["parsed_page"]["questions"][0]["question_type"] == "multiple_choice"


def test_survey_parser_excludes_url_time_date_and_noise(tmp_path: Path) -> None:
    result = parse_survey_layout(
        _noisy_scoped_survey_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.9
    )
    option_texts = [
        option["text"] for option in result["parsed_page"]["questions"][0]["answer_options"]
    ]
    joined = " ".join(option_texts)
    assert "app.usertesting.com" not in joined
    assert "14:34" not in joined
    assert "03/05/2026" not in joined
    assert "测试乱码" not in joined
    assert "X" not in option_texts


def test_survey_parser_stops_at_next_question(tmp_path: Path) -> None:
    result = parse_survey_layout(
        _noisy_scoped_survey_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.9
    )
    option_texts = [
        option["text"] for option in result["parsed_page"]["questions"][0]["answer_options"]
    ]
    assert "How would you describe your proficiency in English?" not in option_texts
    assert "I do not speak English" not in option_texts
    assert "Beginner" not in option_texts
    assert result["diagnostics"]["next_question_boundary"]


def test_survey_parser_extracts_current_question_options_and_dedupes(tmp_path: Path) -> None:
    result = parse_survey_layout(
        _noisy_scoped_survey_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.9
    )
    option_texts = [
        option["text"] for option in result["parsed_page"]["questions"][0]["answer_options"]
    ]
    compact = ["".join(text.lower().split()) for text in option_texts]
    assert "retailcenter" in compact
    assert "amazoncentral" in compact
    assert "amazonseller" in compact
    assert "alloftheabove" in compact
    assert compact.count("amazoncentral") == 1
    assert result["diagnostics"]["selected_option_candidate_ids"]


def test_garbled_ocr_excluded_from_stacked_option_texts(tmp_path: Path) -> None:
    signals = detect_survey_signals(_noisy_scoped_survey_layout(tmp_path))
    stacked = " ".join(signals["stacked_option_texts"])
    assert "锛塃NG" not in stacked
    assert "娴嬭瘯涔辩爜" not in stacked


def test_garbled_text_does_not_appear_verbatim_in_diagnostics(tmp_path: Path) -> None:
    result = parse_survey_layout(
        _noisy_scoped_survey_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.9
    )
    excluded = result["diagnostics"]["excluded_option_candidates"]
    serialized = json.dumps(excluded, ensure_ascii=False)
    assert "锛塃NG" not in serialized
    assert "娴嬭瘯涔辩爜" not in serialized
    assert any(
        item["text"] == "[filtered_system_or_garbled_text]"
        and item["reason"] == "garbled_or_system_text_filtered"
        for item in excluded
    )


def test_out_of_scope_garbled_text_is_sanitized_in_diagnostics(tmp_path: Path) -> None:
    result = parse_survey_layout(
        _noisy_scoped_survey_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.9
    )
    excluded = result["diagnostics"]["excluded_option_candidates"]
    assert not any(item["id"] == "TB7" and item["text"] == "锛塃NG" for item in excluded)
    assert any(
        item["id"] == "TB7"
        and item["text"] == "[filtered_system_or_garbled_text]"
        and item["reason"] == "garbled_or_system_text_filtered"
        for item in excluded
    )


def test_legitimate_answer_options_remain_unchanged_after_garbled_filter(tmp_path: Path) -> None:
    result = parse_survey_layout(
        _noisy_scoped_survey_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.9
    )
    option_texts = [
        option["text"] for option in result["parsed_page"]["questions"][0]["answer_options"]
    ]
    compact = ["".join(text.lower().split()) for text in option_texts]
    assert "retailcenter" in compact
    assert "amazoncentral" in compact
    assert "amazonseller" in compact
    assert "alloftheabove" in compact


def test_survey_parser_requires_remote_parse_without_clear_scope(tmp_path: Path) -> None:
    result = parse_survey_layout(
        _unclear_survey_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.9
    )
    assert result["requires_remote_parse"] is True
    assert result["quality"]["confidence"] < 0.7
    assert "unable_to_isolate_current_question_scope" in result["fallback_reason"]


def test_form_confidence_drops_when_survey_signals_present(tmp_path: Path) -> None:
    layout = _survey_layout(tmp_path)
    parsed = parse_form_layout(layout, _runtime_context(tmp_path), detector_score=0.95)["parsed_page"]
    quality = score_local_parse(layout, parsed, page_type="form", detector_score=0.95)
    assert quality["confidence"] < 0.7
    assert quality["requires_remote_parse"] is True
    assert quality["survey_signals"]["present"] is True


def test_local_survey_parser_high_confidence_requires_question_and_options(tmp_path: Path) -> None:
    good = parse_survey_layout(
        _survey_layout(tmp_path), _runtime_context(tmp_path), detector_score=0.9
    )
    weak = parse_survey_layout(
        _survey_layout(tmp_path, with_options=False),
        _runtime_context(tmp_path),
        detector_score=0.9,
    )
    assert good["quality"]["confidence"] >= 0.7
    assert good["requires_remote_parse"] is False
    assert weak["quality"]["confidence"] < 0.7
    assert weak["requires_remote_parse"] is True


def test_low_confidence_survey_local_parse_falls_back_to_vision_parser(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: _runtime_context(tmp_path),
    )
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_layout_index",
        lambda: _survey_layout(tmp_path, with_options=False),
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)

    class FakeVisionResult:
        parsed_page = {"page": {"page_type": "unknown", "confidence": 0.1}, "questions": []}
        validation_report = {"valid": True}
        model_calls_count = 1
        warnings = []
        error = ""

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.run_vision_parser",
        lambda _plan: FakeVisionResult(),
    )

    report = run_orchestrated_parse(mode="fake", prefer_local=True)

    assert report["parse_source"] == "vision_parser"
    assert report["remote_fallback_used"] is True
    assert "fewer than two answer options" in " ".join(report["warnings"])


def test_orchestrator_uses_local_fast_parse_when_confidence_is_high(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: _runtime_context(tmp_path),
    )
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_layout_index",
        lambda: _layout(tmp_path),
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.run_vision_parser",
        lambda _plan: (_ for _ in ()).throw(AssertionError("vision parser should not run")),
    )

    report = run_orchestrated_parse(mode="fake")

    assert report["parse_source"] == "local_fast_parse"
    assert report["model_calls_count"] == 0


def test_orchestrator_sets_model_calls_zero_when_local_succeeds(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: _runtime_context(tmp_path),
    )
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_layout_index",
        lambda: _layout(tmp_path),
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)

    report = run_orchestrated_parse(mode="doubao", prefer_local=True)

    assert report["model_calls_count"] == 0
    assert report["remote_fallback_used"] is False


def test_orchestrator_falls_back_to_vision_parser_when_local_low_confidence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: _runtime_context(tmp_path),
    )
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_layout_index",
        lambda: _layout(tmp_path, empty_ocr=True),
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)

    class FakeVisionResult:
        parsed_page = {"page": {"page_type": "unknown", "confidence": 0.1}, "questions": []}
        validation_report = {"valid": True}
        model_calls_count = 1
        warnings = []
        error = ""

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.run_vision_parser",
        lambda _plan: FakeVisionResult(),
    )

    report = run_orchestrated_parse(mode="fake", prefer_local=True)

    assert report["parse_source"] == "vision_parser"
    assert report["remote_fallback_used"] is True
    assert report["model_calls_count"] == 1


def test_no_local_skips_local_parser(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_runtime_context",
        lambda: _runtime_context(tmp_path),
    )
    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.load_layout_index",
        lambda: _layout(tmp_path),
    )
    monkeypatch.setattr("modules.parse_orchestrator.orchestrator.load_config", _config)

    class FakeVisionResult:
        parsed_page = {"page": {"page_type": "unknown", "confidence": 0.1}, "questions": []}
        validation_report = {"valid": True}
        model_calls_count = 1
        warnings = []
        error = ""

    monkeypatch.setattr(
        "modules.parse_orchestrator.orchestrator.run_vision_parser",
        lambda _plan: FakeVisionResult(),
    )

    report = run_orchestrated_parse(mode="fake", no_local=True)

    assert report["parse_source"] == "vision_parser"
    assert report["remote_fallback_used"] is False
    assert report["model_calls_count"] == 1


def test_existing_fake_mode_still_works() -> None:
    report = run_orchestrated_parse(mode="fake", no_local=True)
    assert report["selected_strategy"]
    assert Path("runtime_state/latest_orchestrated_parse.json").exists()
