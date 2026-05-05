from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RUNTIME_DIR = Path("runtime_state")
EXECUTION_GATE_PATH = RUNTIME_DIR / "latest_execution_gate.json"
RESOLVED_ACTION_PLAN_PATH = RUNTIME_DIR / "latest_resolved_action_plan.json"
SCHEDULER_RUN_PATH = RUNTIME_DIR / "latest_scheduler_run.json"
SCHEDULER_REPORT_PATH = RUNTIME_DIR / "latest_scheduler_report.json"


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


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    return load_json(EXECUTION_GATE_PATH), load_json(RESOLVED_ACTION_PLAN_PATH)


def save_scheduler_run(scheduler_run: dict[str, Any]) -> Path:
    return save_json(SCHEDULER_RUN_PATH, scheduler_run)


def save_report(report: dict[str, Any]) -> Path:
    return save_json(SCHEDULER_REPORT_PATH, report)

