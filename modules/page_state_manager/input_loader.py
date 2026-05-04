from __future__ import annotations

import json
from pathlib import Path


ROOT = Path.cwd()
RUNTIME_DIR = ROOT / "runtime_state"

PARSE_PATHS = [
    RUNTIME_DIR / "latest_orchestrated_parse.json",
    RUNTIME_DIR / "latest_local_parse.json",
    RUNTIME_DIR / "latest_parsed_page.json",
]


def read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def extract_parsed_page(payload: dict) -> dict:
    if "parsed_page" in payload and isinstance(payload["parsed_page"], dict):
        return payload["parsed_page"]
    return payload


def load_latest_parse() -> tuple[dict, str]:
    for path in PARSE_PATHS:
        payload = read_json(path)
        if payload is not None:
            return extract_parsed_page(payload), str(path)
    raise FileNotFoundError("No parse file found in runtime_state.")


def load_latest_answer_decision() -> dict | None:
    return read_json(RUNTIME_DIR / "latest_answer_decision.json")
