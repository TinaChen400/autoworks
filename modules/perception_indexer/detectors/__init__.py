from modules.perception_indexer.detectors.base import DetectorResult
from modules.perception_indexer.detectors.drag_drop_detector import run_drag_drop_detector
from modules.perception_indexer.detectors.form_detector import run_form_detector
from modules.perception_indexer.detectors.image_task_detector import run_image_task_detector
from modules.perception_indexer.detectors.matrix_detector import run_matrix_detector
from modules.perception_indexer.detectors.modal_detector import run_modal_detector
from modules.perception_indexer.detectors.survey_detector import run_survey_detector

__all__ = [
    "DetectorResult",
    "run_drag_drop_detector",
    "run_form_detector",
    "run_image_task_detector",
    "run_matrix_detector",
    "run_modal_detector",
    "run_survey_detector",
]
