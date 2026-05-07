from __future__ import annotations

import json
from pathlib import Path


ROOT = Path.cwd()
RUNTIME_DIR = ROOT / "runtime_state"
DECISION_PATH = RUNTIME_DIR / "latest_answer_decision.json"
ORCHESTRATED_PARSE_PATH = RUNTIME_DIR / "latest_orchestrated_parse.json"
SESSION_PATH = RUNTIME_DIR / "latest_survey_session.json"
MANUAL_REVIEW_INPUT_PATH = RUNTIME_DIR / "manual_review_input.json"
REVIEWED_DECISION_PATH = RUNTIME_DIR / "latest_reviewed_answer_decision.json"
HUMAN_REVIEW_REPORT_PATH = RUNTIME_DIR / "latest_human_review_report.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def save_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def load_inputs() -> tuple[dict, dict, dict, dict]:
    return (
        load_json(MANUAL_REVIEW_INPUT_PATH),
        load_json(DECISION_PATH),
        load_json(ORCHESTRATED_PARSE_PATH),
        load_json(SESSION_PATH),
    )

