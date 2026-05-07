from __future__ import annotations

import json
from pathlib import Path


ROOT = Path.cwd()
RUNTIME_DIR = ROOT / "runtime_state"
DEFAULT_PARSE_PATH = RUNTIME_DIR / "latest_orchestrated_parse.json"

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
    if "parsed_page" in payload:
        raise ValueError("parsed_page must be an object")
    return payload


def resolve_parse_source(source: str | Path = "auto") -> Path:
    if str(source) == "auto":
        return DEFAULT_PARSE_PATH.resolve(strict=False)
    return Path(source).resolve(strict=False)


def load_parse(source: str | Path = "auto") -> tuple[dict, str]:
    path = resolve_parse_source(source)
    payload = read_json(path)
    if payload is None:
        raise FileNotFoundError(f"Parse source not found: {path}")
    if not isinstance(payload, dict):
        raise ValueError(f"Parse source must contain a JSON object: {path}")
    parsed_page = extract_parsed_page(payload)
    if not isinstance(parsed_page, dict):
        raise ValueError(f"Parsed page must be a JSON object: {path}")
    return parsed_page, str(path)


def load_latest_parse(source: str | Path = "auto") -> tuple[dict, str]:
    return load_parse(source)


def load_latest_answer_decision() -> dict | None:
    return read_json(RUNTIME_DIR / "latest_answer_decision.json")
