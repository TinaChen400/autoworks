from __future__ import annotations

import json
from pathlib import Path


ROOT = Path.cwd()
RUNTIME_DIR = ROOT / "runtime_state"
SESSION_PATH = RUNTIME_DIR / "latest_survey_session.json"
DECISION_PATH = RUNTIME_DIR / "latest_answer_decision.json"
ANSWER_REPORT_PATH = RUNTIME_DIR / "latest_answer_engine_report.json"
ACTION_PLAN_PATH = RUNTIME_DIR / "latest_action_plan.json"
ACTION_PLAN_REPORT_PATH = RUNTIME_DIR / "latest_action_plan_report.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def save_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def load_inputs() -> tuple[dict, dict, dict]:
    return load_json(SESSION_PATH), load_json(DECISION_PATH), load_json(ANSWER_REPORT_PATH)


def save_action_plan(plan: dict) -> Path:
    return save_json(ACTION_PLAN_PATH, plan)


def save_report(report: dict) -> Path:
    return save_json(ACTION_PLAN_REPORT_PATH, report)
