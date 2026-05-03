from __future__ import annotations

import json
from pathlib import Path


ROOT = Path.cwd()
RUNTIME_DIR = ROOT / "runtime_state"
DECISION_PATH = RUNTIME_DIR / "latest_answer_decision.json"
REPORT_PATH = RUNTIME_DIR / "latest_answer_engine_report.json"


def save_decision(decision: dict) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with DECISION_PATH.open("w", encoding="utf-8") as handle:
        json.dump(decision, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return DECISION_PATH


def save_report(report: dict) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return REPORT_PATH
