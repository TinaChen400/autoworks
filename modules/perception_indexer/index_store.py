from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LAYOUT_INDEX_PATH = Path("runtime_state/latest_layout_index.json")
ANNOTATED_OVERVIEW_PATH = Path("runtime_state/latest_annotated_overview.png")
PERCEPTION_REPORT_PATH = Path("runtime_state/latest_perception_report.json")
CROPS_DIR = Path("runtime_state/crops")
CONFIG_PATH = Path("config/perception_indexer.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "ocr_backend": "disabled",
    "crop_margin_percent": 0.08,
    "crop_margin_min_px": 40,
    "min_element_area_px": 80,
    "max_element_area_ratio": 0.40,
    "annotate_regions": True,
    "annotate_elements": True,
    "annotate_text_blocks": True,
    "show_browser_elements": False,
    "show_low_confidence_elements": False,
    "show_removed_card_candidates": False,
    "min_element_confidence_for_annotation": 0.35,
}


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    with CONFIG_PATH.open("r", encoding="utf-8-sig") as file:
        loaded = json.load(file)
    config = dict(DEFAULT_CONFIG)
    config.update(loaded)
    return config


def write_json(path: str | Path, data: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def save_layout_index(layout_index: dict[str, Any]) -> None:
    write_json(LAYOUT_INDEX_PATH, layout_index)


def save_perception_report(report: dict[str, Any]) -> None:
    write_json(PERCEPTION_REPORT_PATH, report)
