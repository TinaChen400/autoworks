from __future__ import annotations

from modules.perception_indexer.detectors.base import DetectorResult


def run_matrix_detector(_regions, _elements, _text_blocks) -> DetectorResult:
    return DetectorResult(
        detector_name="matrix",
        score=0.0,
        possible_page_type="matrix",
        warnings=["Detector not implemented yet."],
    )
