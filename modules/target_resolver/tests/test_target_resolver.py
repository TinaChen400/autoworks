from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.target_resolver import resolved_action_store
from modules.target_resolver.target_resolver import resolve_action_plan, run


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_paths(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime_state"
    monkeypatch.setattr(resolved_action_store, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(resolved_action_store, "ACTION_PLAN_PATH", runtime / "latest_action_plan.json")
    monkeypatch.setattr(
        resolved_action_store,
        "ORCHESTRATED_PARSE_PATH",
        runtime / "latest_orchestrated_parse.json",
    )
    monkeypatch.setattr(resolved_action_store, "LAYOUT_INDEX_PATH", runtime / "latest_layout_index.json")
    monkeypatch.setattr(
        resolved_action_store,
        "RUNTIME_CONTEXT_PATH",
        runtime / "latest_runtime_context.json",
    )
    monkeypatch.setattr(
        resolved_action_store,
        "RESOLVED_ACTION_PLAN_PATH",
        runtime / "latest_resolved_action_plan.json",
    )
    monkeypatch.setattr(
        resolved_action_store,
        "TARGET_RESOLVER_REPORT_PATH",
        runtime / "latest_target_resolver_report.json",
    )


def _action_plan(skill: str = "click_option", option_id: str = "o1") -> dict:
    target = {"question_id": "q1"}
    if option_id:
        target["option_id"] = option_id
    if skill == "click_navigation":
        target = {"button_id": "nav_next", "action": "next_page", "text": "Next"}
    return {
        "action_plan_id": "action_plan_1",
        "task_id": "task1",
        "session_id": "session_1",
        "status": "ready",
        "actions": [
            {
                "action_id": "a1",
                "skill": skill,
                "target": target,
                "params": {},
                "requires_review": skill == "request_human_review",
            }
        ],
        "warnings": [],
    }


def _orchestrated_parse() -> dict:
    return {
        "parsed_page": {
            "questions": [
                {
                    "question_id": "q1",
                    "answer_options": [
                        {
                            "option_id": "o1",
                            "text": "Retail Central",
                            "selection_control": "radio",
                        }
                    ],
                }
            ]
        }
    }


def _orchestrated_parse_with_option_geometry(
    click_point_norm: dict | None = None,
    bbox_norm: dict | None = None,
    selection_control: str = "radio",
    control_click_point_norm: dict | None = None,
    control_bbox_norm: dict | None = None,
    control_element_id: str = "",
    text: str = "Retail Central",
) -> dict:
    option = {
        "option_id": "o1",
        "text": text,
        "selection_control": selection_control,
    }
    if click_point_norm is not None:
        option["click_point_norm"] = click_point_norm
    if bbox_norm is not None:
        option["bbox_norm"] = bbox_norm
    if control_click_point_norm is not None:
        option["control_click_point_norm"] = control_click_point_norm
    if control_bbox_norm is not None:
        option["control_bbox_norm"] = control_bbox_norm
    if control_element_id:
        option["control_element_id"] = control_element_id
    return {"parsed_page": {"questions": [{"question_id": "q1", "answer_options": [option]}]}}


def _orchestrated_parse_with_navigation() -> dict:
    payload = _orchestrated_parse()
    payload["parsed_page"]["navigation_buttons"] = [
        {
            "button_id": "nav_next",
            "action": "next_page",
            "text": "Next",
            "click_point_norm": {"x": 0.5, "y": 0.6},
            "confidence": 0.95,
        }
    ]
    return payload


def _layout_index() -> dict:
    return {
        "elements": [
            {
                "element_id": "E1",
                "element_type_hint": "radio_like",
                "click_point_norm": {"x": 0.25, "y": 0.5},
                "click_point_raw": {"x": 50, "y": 80},
                "confidence": 0.9,
            }
        ],
        "text_blocks": [
            {
                "text_id": "T1",
                "text": "Retail Central",
                "bbox_norm": {"x": 0.2, "y": 0.45, "width": 0.2, "height": 0.1},
                "confidence": 0.95,
                "source": "test",
            }
        ],
        "relationships": [
            {
                "relationship_id": "REL1",
                "relationship_type": "possible_option_label",
                "source_id": "T1",
                "target_id": "E1",
                "confidence": 0.8,
            }
        ],
    }


def _empty_layout_index() -> dict:
    return {"elements": [], "text_blocks": [], "relationships": []}


def _layout_index_with_nearby_visual_control() -> dict:
    return {
        "elements": [
            {
                "element_id": "E_near",
                "element_type_hint": "icon_like",
                "click_point_norm": {"x": 0.392, "y": 0.544},
                "click_point_raw": {"x": 78, "y": 54},
                "confidence": 0.45,
            }
        ],
        "text_blocks": [],
        "relationships": [],
    }


def _layout_index_with_competing_nearby_visual_controls() -> dict:
    return {
        "elements": [
            {
                "element_id": "E_wrong",
                "element_type_hint": "checkbox_like",
                "click_point_norm": {"x": 0.392, "y": 0.544},
                "confidence": 0.9,
            },
            {
                "element_id": "E_right",
                "element_type_hint": "icon_like",
                "click_point_norm": {"x": 0.405, "y": 0.565},
                "confidence": 0.35,
            },
        ],
        "text_blocks": [],
        "relationships": [],
    }


def _runtime_context() -> dict:
    return {
        "model_input_region": {"x": 10, "y": 20, "width": 200, "height": 100},
        "anchor_frame": {"x": 100, "y": 200, "width": 800, "height": 600},
        "coordinate_policy": {
            "formula": "raw_x = model_input_region.x + norm_x * model_input_region.width; raw_y = model_input_region.y + norm_y * model_input_region.height; screen_x = anchor_frame.x + raw_x; screen_y = anchor_frame.y + raw_y"
        },
    }


def test_request_human_review_preservation() -> None:
    plan = _action_plan("request_human_review", "")

    resolved, report = resolve_action_plan(plan, _orchestrated_parse(), _layout_index(), _runtime_context())

    assert report["validation_passed"] is True
    assert resolved["actions"][0]["skill"] == "request_human_review"
    assert resolved["actions"][0]["target"] == {"question_id": "q1"}
    assert "click_point_norm" not in json.dumps(resolved["actions"][0])


def test_click_option_resolves_from_parsed_click_point_norm() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(click_point_norm={"x": 0.3925, "y": 0.5575}),
        _layout_index(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["click_point_norm"] == {"x": 0.3925, "y": 0.5575}
    assert target["click_point_raw"] == {"x": 88, "y": 76}
    assert target["click_point_screen"] == {"x": 188, "y": 276}
    assert target["resolver_confidence"] == 0.85
    assert target["resolver_confidence"] >= 0.5
    assert target["resolver_source"] == "parsed_option_geometry"


def test_click_navigation_resolves_from_navigation_button_geometry() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_navigation", ""),
        _orchestrated_parse_with_navigation(),
        _empty_layout_index(),
        _runtime_context(),
    )

    assert report["validation_passed"] is True
    action = resolved["actions"][0]
    assert action["skill"] == "click_navigation"
    target = action["target"]
    assert target["button_id"] == "nav_next"
    assert target["action"] == "next_page"
    assert target["click_point_screen"] == {"x": 210, "y": 280}
    assert target["resolver_source"] == "parsed_navigation_button"


def test_click_option_resolves_from_parsed_bbox_center_when_click_point_missing() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(
            bbox_norm={"x": 0.37, "y": 0.54, "width": 0.045, "height": 0.035},
            selection_control="text",
        ),
        _layout_index(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["click_point_norm"] == {"x": 0.3925, "y": 0.5575}
    assert target["click_point_raw"] == {"x": 88, "y": 76}
    assert target["click_point_screen"] == {"x": 188, "y": 276}
    assert target["resolver_confidence"] == 0.8
    assert target["resolver_source"] == "parsed_option_bbox_center"


def test_radio_option_with_inferred_bbox_center_uses_left_biased_control_point() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(
            click_point_norm={"x": 0.4, "y": 0.565},
            bbox_norm={"x": 0.36, "y": 0.55, "width": 0.08, "height": 0.03},
            selection_control="radio",
        ),
        _empty_layout_index(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["click_point_norm"] == {"x": 0.38, "y": 0.556}
    assert target["click_point_raw"] == {"x": 86, "y": 76}
    assert target["resolver_source"] == "radio_control_left_bias"
    assert target["original_click_point_norm"] == {"x": 0.4, "y": 0.565}
    assert target["adjusted_click_point_norm"] == {"x": 0.38, "y": 0.556}
    assert target["selection_control"] == "radio"
    assert target["adjustment_reason"] == "parsed click point was inferred from option bbox center"
    assert target["click_candidates"][0]["source"] == "radio_control_left_bias"
    assert target["click_candidates"][0]["is_primary"] is True
    assert target["click_candidates"][0]["click_point_raw"] == {"x": 86, "y": 76}


def test_checkbox_option_with_inferred_bbox_center_uses_left_biased_control_point() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(
            click_point_norm={"x": 0.4, "y": 0.565},
            bbox_norm={"x": 0.36, "y": 0.55, "width": 0.08, "height": 0.03},
            selection_control="checkbox",
        ),
        _empty_layout_index(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["click_point_norm"] == {"x": 0.38, "y": 0.556}
    assert target["resolver_source"] == "radio_control_left_bias"
    assert target["selection_control"] == "checkbox"
    assert target["click_candidates"][0]["source"] == "radio_control_left_bias"


def test_non_radio_option_keeps_original_parsed_click_point_norm() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(
            click_point_norm={"x": 0.4, "y": 0.565},
            bbox_norm={"x": 0.36, "y": 0.55, "width": 0.08, "height": 0.03},
            selection_control="text",
        ),
        _empty_layout_index(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["click_point_norm"] == {"x": 0.4, "y": 0.565}
    assert target["resolver_source"] == "parsed_option_geometry"
    assert "adjusted_click_point_norm" not in target


def test_control_click_point_norm_is_preferred_over_left_bias_fallback() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(
            click_point_norm={"x": 0.4, "y": 0.565},
            bbox_norm={"x": 0.36, "y": 0.55, "width": 0.08, "height": 0.03},
            selection_control="radio",
            control_click_point_norm={"x": 0.365, "y": 0.565},
        ),
        _empty_layout_index(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["click_point_norm"] == {"x": 0.365, "y": 0.565}
    assert target["resolver_source"] == "parsed_control_click_point"
    assert "adjusted_click_point_norm" not in target


def test_click_option_resolution() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse(),
        _layout_index(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["question_id"] == "q1"
    assert target["option_id"] == "o1"
    assert target["option_text"] == "Retail Central"
    assert target["control_element_id"] == "E1"
    assert target["control_type"] == "radio_like"
    assert target["click_point_norm"] == {"x": 0.25, "y": 0.5}
    assert target["click_point_raw"] == {"x": 60, "y": 70}
    assert target["click_point_screen"] == {"x": 160, "y": 270}
    assert target["resolver_confidence"] == 0.8
    assert target["resolver_source"] == "possible_option_label"
    assert target["click_candidates"] == [
        {
            "source": "possible_option_label",
            "click_point_norm": {"x": 0.25, "y": 0.5},
            "click_point_raw": {"x": 60, "y": 70},
            "click_point_screen": {"x": 160, "y": 270},
            "confidence": 0.8,
            "control_element_id": "E1",
            "control_type": "radio_like",
            "is_primary": True,
        }
    ]


def test_radio_option_candidates_include_nearby_detected_control_without_ocr() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(
            click_point_norm={"x": 0.4, "y": 0.565},
            bbox_norm={"x": 0.36, "y": 0.55, "width": 0.08, "height": 0.03},
            selection_control="radio",
        ),
        _layout_index_with_nearby_visual_control(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    candidate_sources = [candidate["source"] for candidate in target["click_candidates"]]
    assert report["validation_passed"] is True
    assert target["click_point_raw"] == {"x": 88, "y": 74}
    assert target["resolver_source"] == "nearby_detected_control"
    assert target["control_element_id"] == "E_near"
    assert target["resolver_confidence"] == 0.82
    assert candidate_sources[0] == "nearby_detected_control"
    assert target["click_candidates"][0]["is_primary"] is True
    assert "nearby_detected_control" in candidate_sources
    nearby = next(candidate for candidate in target["click_candidates"] if candidate["source"] == "nearby_detected_control")
    assert nearby["click_point_raw"] == {"x": 88, "y": 74}
    assert nearby["control_element_id"] == "E_near"


def test_radio_option_prefers_nearby_detected_control_over_parsed_control_point() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(
            click_point_norm={"x": 0.4, "y": 0.565},
            bbox_norm={"x": 0.36, "y": 0.55, "width": 0.08, "height": 0.03},
            selection_control="radio",
            control_click_point_norm={"x": 0.405, "y": 0.565},
            control_element_id="E_right",
        ),
        _layout_index_with_nearby_visual_control(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["resolver_source"] == "nearby_detected_control"
    assert target["click_point_norm"] == {"x": 0.392, "y": 0.544}
    assert target["click_point_raw"] == {"x": 88, "y": 74}
    assert target["resolver_confidence"] == 0.82
    assert target["click_candidates"][0]["source"] == "nearby_detected_control"
    assert target["click_candidates"][0]["is_primary"] is True
    assert "parsed_control_click_point" in [
        candidate["source"] for candidate in target["click_candidates"]
    ]


def test_short_yes_no_radio_prefers_option_text_click_point() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(
            click_point_norm={"x": 0.411459, "y": 0.859259},
            bbox_norm={"x": 0.397917, "y": 0.849074, "width": 0.027083, "height": 0.02037},
            selection_control="radio",
            control_click_point_norm={"x": 0.416146, "y": 0.856481},
            control_element_id="E_right",
            text="No",
        ),
        _layout_index_with_competing_nearby_visual_controls(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["resolver_source"] == "parsed_option_click_point"
    assert target["click_point_norm"] == {"x": 0.411459, "y": 0.859259}
    assert target["click_candidates"][0]["source"] == "parsed_option_click_point"
    assert target["click_candidates"][0]["is_primary"] is True


def test_radio_option_prefers_matching_control_id_over_higher_confidence_neighbor() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(
            click_point_norm={"x": 0.4, "y": 0.565},
            bbox_norm={"x": 0.36, "y": 0.55, "width": 0.08, "height": 0.03},
            selection_control="radio",
            control_click_point_norm={"x": 0.405, "y": 0.565},
            control_element_id="E_right",
        ),
        _layout_index_with_competing_nearby_visual_controls(),
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["resolver_source"] == "nearby_detected_control"
    assert target["control_element_id"] == "E_right"
    assert target["click_point_norm"] == {"x": 0.405, "y": 0.565}
    assert target["click_candidates"][0]["control_element_id"] == "E_right"


def test_radio_option_filters_controls_above_current_option_row() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "o1"),
        _orchestrated_parse_with_option_geometry(
            click_point_norm={"x": 0.4, "y": 0.565},
            bbox_norm={"x": 0.36, "y": 0.55, "width": 0.08, "height": 0.03},
            selection_control="radio",
            control_click_point_norm={"x": 0.405, "y": 0.565},
            control_element_id="E_right",
        ),
        {
            "elements": [
                {
                    "element_id": "E_above",
                    "element_type_hint": "checkbox_like",
                    "click_point_norm": {"x": 0.392, "y": 0.532},
                    "confidence": 0.9,
                },
                {
                    "element_id": "E_right",
                    "element_type_hint": "icon_like",
                    "click_point_norm": {"x": 0.405, "y": 0.565},
                    "confidence": 0.35,
                },
            ],
            "text_blocks": [],
            "relationships": [],
        },
        _runtime_context(),
    )

    target = resolved["actions"][0]["target"]
    assert report["validation_passed"] is True
    assert target["click_candidates"][0]["control_element_id"] == "E_right"
    assert "E_above" not in [
        candidate.get("control_element_id") for candidate in target["click_candidates"]
    ]


def test_invalid_option_id_generates_validation_issue() -> None:
    resolved, report = resolve_action_plan(
        _action_plan("click_option", "missing"),
        _orchestrated_parse(),
        _layout_index(),
        _runtime_context(),
    )

    assert resolved["status"] == "invalid"
    assert report["validation_passed"] is False
    assert report["issues"][0]["type"] == "option_not_found"
    assert resolved["actions"][0]["target"] == {"question_id": "q1", "option_id": "missing"}


def test_no_coordinates_are_attached_to_request_human_review() -> None:
    plan = _action_plan("request_human_review", "")
    plan["actions"][0]["target"]["click_point_norm"] = {"x": 0.1, "y": 0.2}

    resolved, report = resolve_action_plan(plan, _orchestrated_parse(), _layout_index(), _runtime_context())

    assert report["validation_passed"] is True
    assert "click_point_norm" not in resolved["actions"][0]["target"]
    assert "click_point_raw" not in resolved["actions"][0]["target"]
    assert "click_point_screen" not in resolved["actions"][0]["target"]


def test_generated_resolved_action_plan_is_valid_json_without_bom(tmp_path, monkeypatch) -> None:
    _patch_paths(monkeypatch, tmp_path)
    runtime = tmp_path / "runtime_state"
    _write_json(runtime / "latest_action_plan.json", _action_plan("click_option", "o1"))
    _write_json(runtime / "latest_orchestrated_parse.json", _orchestrated_parse())
    _write_json(runtime / "latest_layout_index.json", _layout_index())
    _write_json(runtime / "latest_runtime_context.json", _runtime_context())

    run("auto")
    resolved_path = runtime / "latest_resolved_action_plan.json"

    assert not resolved_path.read_bytes().startswith(b"\xef\xbb\xbf")
    subprocess.run(
        [sys.executable, "-m", "json.tool", str(resolved_path)],
        check=True,
        capture_output=True,
        text=True,
    )
