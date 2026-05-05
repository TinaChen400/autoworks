from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RUNTIME_DIR = Path("runtime_state")
EXECUTION_GATE_PATH = RUNTIME_DIR / "latest_execution_gate.json"
SCHEDULER_RUN_PATH = RUNTIME_DIR / "latest_scheduler_run.json"
RESOLVED_ACTION_PLAN_PATH = RUNTIME_DIR / "latest_resolved_action_plan.json"
ACTION_EXECUTOR_PREVIEW_PATH = RUNTIME_DIR / "latest_action_executor_preview.json"
ACTION_EXECUTOR_REPORT_PATH = RUNTIME_DIR / "latest_action_executor_report.json"


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


def paths_for_runtime(runtime_dir: str | Path) -> tuple[Path, Path]:
    runtime = Path(runtime_dir)
    return (
        runtime / "latest_action_executor_preview.json",
        runtime / "latest_action_executor_report.json",
    )


def load_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        load_json(EXECUTION_GATE_PATH),
        load_json(SCHEDULER_RUN_PATH),
        load_json(RESOLVED_ACTION_PLAN_PATH),
    )


def save_preview(preview: dict[str, Any], path: str | Path = ACTION_EXECUTOR_PREVIEW_PATH) -> Path:
    return save_json(path, preview)


def save_report(report: dict[str, Any], path: str | Path = ACTION_EXECUTOR_REPORT_PATH) -> Path:
    return save_json(path, report)
