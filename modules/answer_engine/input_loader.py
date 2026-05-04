from __future__ import annotations

import json
from pathlib import Path


ROOT = Path.cwd()
RUNTIME_DIR = ROOT / "runtime_state"

SOURCE_PATHS = {
    "orchestrated": RUNTIME_DIR / "latest_orchestrated_parse.json",
    "local": RUNTIME_DIR / "latest_local_parse.json",
    "parsed": RUNTIME_DIR / "latest_parsed_page.json",
}


def read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def extract_parsed_page(payload: dict) -> dict:
    if "parsed_page" in payload and isinstance(payload["parsed_page"], dict):
        return payload["parsed_page"]
    return payload


def load_parse(source: str = "auto") -> tuple[dict, str]:
    if source != "auto":
        path = SOURCE_PATHS[source]
        payload = read_json(path)
        if payload is None:
            raise FileNotFoundError(f"Parse source not found: {path}")
        return extract_parsed_page(payload), str(path)

    for name in ("orchestrated", "local", "parsed"):
        path = SOURCE_PATHS[name]
        payload = read_json(path)
        if payload is not None:
            return extract_parsed_page(payload), str(path)
    raise FileNotFoundError("No parse file found in runtime_state.")


def load_session() -> dict | None:
    return read_json(RUNTIME_DIR / "latest_survey_session.json")


def load_config() -> dict:
    path = ROOT / "config" / "answer_engine.json"
    payload = read_json(path)
    if payload is not None:
        return payload
    return {
        "require_human_review_by_default": True,
        "allow_local_rule_answers": True,
        "allow_llm_answerer": False,
        "minimum_confidence_without_review": 0.85,
        "personal_fact_questions_require_evidence": True,
        "all_of_the_above_requires_all_evidence": True,
        "answer_tone": "honest, concise, natural",
        "language": "English",
        "style": "simple British English",
    }
