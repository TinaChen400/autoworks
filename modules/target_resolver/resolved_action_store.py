from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RUNTIME_DIR = Path("runtime_state")
ACTION_PLAN_PATH = RUNTIME_DIR / "latest_action_plan.json"
ORCHESTRATED_PARSE_PATH = RUNTIME_DIR / "latest_orchestrated_parse.json"
LAYOUT_INDEX_PATH = RUNTIME_DIR / "latest_layout_index.json"
RUNTIME_CONTEXT_PATH = RUNTIME_DIR / "latest_runtime_context.json"
RESOLVED_ACTION_PLAN_PATH = RUNTIME_DIR / "latest_resolved_action_plan.json"
TARGET_RESOLVER_REPORT_PATH = RUNTIME_DIR / "latest_target_resolver_report.json"


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


def load_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        load_json(ACTION_PLAN_PATH),
        load_json(ORCHESTRATED_PARSE_PATH),
        load_json(LAYOUT_INDEX_PATH),
        load_json(RUNTIME_CONTEXT_PATH),
    )


def save_resolved_action_plan(plan: dict[str, Any]) -> Path:
    return save_json(RESOLVED_ACTION_PLAN_PATH, plan)


def save_report(report: dict[str, Any]) -> Path:
    return save_json(TARGET_RESOLVER_REPORT_PATH, report)

