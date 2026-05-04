from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RUNTIME_CONTEXT_PATH = Path("runtime_state/latest_runtime_context.json")
MODEL_INPUT_PATH = Path("runtime_state/latest_model_input.png")
RAW_RESPONSE_PATH = Path("runtime_state/latest_raw_vision_response.txt")
PARSED_PAGE_PATH = Path("runtime_state/latest_parsed_page.json")
VALIDATION_REPORT_PATH = Path("runtime_state/latest_vision_validation_report.json")
PROMPT_PATH = Path("runtime_state/latest_vision_prompt.txt")
DIAGNOSTICS_PATH = Path("runtime_state/latest_vision_diagnostics.json")


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def write_json(path: str | Path, data: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def write_text(path: str | Path, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def load_runtime_context(path: str | Path = RUNTIME_CONTEXT_PATH) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError("Please run context_mapper first.")
    return read_json(source)
