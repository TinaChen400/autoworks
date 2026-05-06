from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RUNTIME_STATE_DIR = Path("runtime_state")
RUNTIME_CONTEXT_PATH = RUNTIME_STATE_DIR / "latest_runtime_context.json"
LAYOUT_INDEX_PATH = RUNTIME_STATE_DIR / "latest_layout_index.json"
ANNOTATED_OVERVIEW_PATH = RUNTIME_STATE_DIR / "latest_annotated_overview.png"
CROPS_DIR = RUNTIME_STATE_DIR / "crops"
CONFIG_PATH = Path("config/parse_orchestrator.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "default_mode": "fake",
    "output_level": None,
    "max_model_calls": 3,
    "prefer_annotated_crops": True,
    "include_annotated_overview_with_unsafe_crops": True,
    "fallback_to_full_screenshot": True,
    "safe_crop_required_for_crop_only_parse": True,
    "minimum_detector_score_for_direct_parse": 0.5,
    "prefer_local_parser": True,
    "local_parser_min_confidence": 0.75,
    "fallback_to_doubao": True,
    "allowed_parser_types": [
        "form",
        "survey",
        "image_task",
        "drag_drop",
        "matrix",
        "modal",
        "general",
        "scene_scan",
    ],
}


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def write_json(path: str | Path, data: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    if not Path(path).exists():
        return dict(DEFAULT_CONFIG)
    loaded = read_json(path)
    config = dict(DEFAULT_CONFIG)
    config.update(loaded)
    return config


def load_runtime_context(path: str | Path = RUNTIME_CONTEXT_PATH) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError("Please run context_mapper first.")
    context = read_json(source)
    screenshot_path = context.get("screenshot_path")
    if not screenshot_path or not Path(screenshot_path).exists():
        raise FileNotFoundError("Please run window_capture Capture first.")
    return context


def load_layout_index(path: str | Path = LAYOUT_INDEX_PATH) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError("Please run perception_indexer first.")
    return read_json(source)


def path_exists(path: str | Path | None) -> bool:
    return bool(path) and Path(str(path)).exists()


def region_by_id(layout_index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(region.get("region_id")): region
        for region in layout_index.get("regions", [])
        if region.get("region_id")
    }

