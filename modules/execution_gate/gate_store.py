from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RUNTIME_DIR = Path("runtime_state")
RESOLVED_ACTION_PLAN_PATH = RUNTIME_DIR / "latest_resolved_action_plan.json"
TARGET_RESOLVER_REPORT_PATH = RUNTIME_DIR / "latest_target_resolver_report.json"
ACTION_PLAN_REPORT_PATH = RUNTIME_DIR / "latest_action_plan_report.json"
ANSWER_ENGINE_REPORT_PATH = RUNTIME_DIR / "latest_answer_engine_report.json"
SURVEY_SESSION_PATH = RUNTIME_DIR / "latest_survey_session.json"
EXECUTION_GATE_PATH = RUNTIME_DIR / "latest_execution_gate.json"
EXECUTION_GATE_REPORT_PATH = RUNTIME_DIR / "latest_execution_gate_report.json"


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def save_json(path: str | Path, payload: dict[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return destination


def load_inputs() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    return (
        load_json(RESOLVED_ACTION_PLAN_PATH),
        load_json(TARGET_RESOLVER_REPORT_PATH),
        load_json(ACTION_PLAN_REPORT_PATH),
        load_json(ANSWER_ENGINE_REPORT_PATH),
        load_json(SURVEY_SESSION_PATH),
    )


def save_execution_gate(gate: dict[str, Any]) -> Path:
    return save_json(EXECUTION_GATE_PATH, gate)


def save_report(report: dict[str, Any]) -> Path:
    return save_json(EXECUTION_GATE_REPORT_PATH, report)
