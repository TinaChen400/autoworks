from __future__ import annotations

from modules.perception_indexer.detectors.base import DetectorResult


def run_modal_detector(_regions, _elements, _text_blocks) -> DetectorResult:
    return DetectorResult(
        detector_name="modal",
        score=0.0,
        possible_page_type="modal",
        warnings=["Detector not implemented yet."],
    )
