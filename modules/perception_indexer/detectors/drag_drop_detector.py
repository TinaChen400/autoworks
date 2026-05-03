from __future__ import annotations

from modules.perception_indexer.detectors.base import DetectorResult


def run_drag_drop_detector(_regions, _elements, _text_blocks) -> DetectorResult:
    return DetectorResult(
        detector_name="drag_drop",
        score=0.0,
        possible_page_type="drag_drop",
        warnings=["Detector not implemented yet."],
    )
