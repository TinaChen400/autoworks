from __future__ import annotations

from modules.perception_indexer.detectors.base import DetectorResult


def run_image_task_detector(_regions, _elements, _text_blocks) -> DetectorResult:
    return DetectorResult(
        detector_name="image_task",
        score=0.0,
        possible_page_type="image_task",
        warnings=["Detector not implemented yet."],
    )
