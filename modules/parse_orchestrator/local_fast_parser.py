from __future__ import annotations

from typing import Any

from modules.parse_orchestrator.local_form_parser import parse_form_layout
from modules.parse_orchestrator.local_parse_quality import (
    detect_local_page_signals,
)
from modules.parse_orchestrator.local_survey_parser import parse_survey_layout
from modules.parse_orchestrator.strategy_selector import select_local_fast_parse_type


def run_local_fast_parse(
    layout_index: dict[str, Any],
    runtime_context: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    page_type, detector_score, skip_reason = select_local_fast_parse_type(layout_index, config)
    min_confidence = float(config.get("local_fast_parse_min_confidence", 0.7))
    local_signals = detect_local_page_signals(layout_index)
    survey_signals = dict(local_signals.get("survey_signals") or {})
    form_signals = dict(local_signals.get("form_signals") or {})
    selected_local_parser = str(local_signals.get("selected_local_parser") or page_type)
    if selected_local_parser == "survey":
        page_type = "survey"
        detector_score = max(
            detector_score,
            float(dict(local_signals.get("detector_scores") or {}).get("survey", 0.0) or 0.0),
            0.7,
        )
        skip_reason = ""
    elif selected_local_parser == "form" and page_type != "form":
        page_type = "form"
    if not page_type:
        return {
            "attempted": False,
            "parsed_page": {},
            "quality": {
                "confidence": 0.0,
                "requires_remote_parse": True,
                "reasons": [skip_reason],
            },
            "requires_remote_parse": True,
            "fallback_reason": skip_reason,
            "detected_local_page_type": local_signals.get("detected_local_page_type", "unknown"),
            "selected_local_parser": "",
            "survey_signals": survey_signals,
            "form_signals": form_signals,
            "detector_override_applied": bool(local_signals.get("detector_override_applied", False)),
            "warnings": list(local_signals.get("warnings") or []),
            "source": "local_fast_parse",
        }
    if page_type == "form":
        result = parse_form_layout(
            layout_index,
            runtime_context,
            detector_score=detector_score,
            min_confidence=min_confidence,
        )
    elif page_type == "survey":
        result = parse_survey_layout(
            layout_index,
            runtime_context,
            detector_score=detector_score,
            min_confidence=min_confidence,
        )
    else:
        result = {
            "parsed_page": {},
            "quality": {
                "confidence": 0.0,
                "requires_remote_parse": True,
                "reasons": [f"No local parser for {page_type}."],
            },
            "requires_remote_parse": True,
        }
    result["attempted"] = True
    result["detector_score"] = detector_score
    result["local_page_type"] = page_type
    quality = dict(result.get("quality") or {})
    result["detected_local_page_type"] = quality.get(
        "detected_local_page_type",
        local_signals.get("detected_local_page_type", page_type),
    )
    result["selected_local_parser"] = page_type
    result["survey_signals"] = quality.get("survey_signals", survey_signals)
    result["form_signals"] = quality.get("form_signals", form_signals)
    result["detector_override_applied"] = bool(local_signals.get("detector_override_applied", False))
    result["warnings"] = list(local_signals.get("warnings") or [])
    diagnostics = dict(result.get("diagnostics") or {})
    for key in [
        "current_question_scope",
        "excluded_option_candidates",
        "selected_option_candidate_ids",
        "next_question_boundary",
    ]:
        if key in diagnostics:
            result[key] = diagnostics[key]
    result["requires_remote_parse"] = bool(result.get("requires_remote_parse", True))
    result["fallback_reason"] = "; ".join(result.get("quality", {}).get("reasons", []))
    return result
