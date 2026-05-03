from __future__ import annotations

from modules.perception_indexer.detectors import (
    DetectorResult,
    run_drag_drop_detector,
    run_form_detector,
    run_image_task_detector,
    run_matrix_detector,
    run_modal_detector,
    run_survey_detector,
)


def run_detectors(regions, elements, text_blocks) -> list[DetectorResult]:
    return [
        run_form_detector(regions, elements, text_blocks),
        run_survey_detector(regions, elements, text_blocks),
        run_image_task_detector(regions, elements, text_blocks),
        run_drag_drop_detector(regions, elements, text_blocks),
        run_matrix_detector(regions, elements, text_blocks),
        run_modal_detector(regions, elements, text_blocks),
    ]


def detector_scores(results: list[DetectorResult]) -> dict[str, float]:
    return {result.detector_name: result.score for result in results}


def possible_page_types_from_scores(results: list[DetectorResult]) -> list[str]:
    positive = [result for result in results if result.score > 0]
    if not positive:
        return ["unknown"]
    ordered = sorted(positive, key=lambda result: result.score, reverse=True)
    return [result.possible_page_type for result in ordered]


def implemented_detectors(results: list[DetectorResult]) -> list[str]:
    return [result.detector_name for result in results if result.score > 0 or not result.warnings]


def pending_detectors(results: list[DetectorResult]) -> list[str]:
    return [
        result.detector_name
        for result in results
        if "Detector not implemented yet." in result.warnings
    ]
