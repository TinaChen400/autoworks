from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.parse_orchestrator.input_loader import read_json, write_json

PARSE_PLAN_PATH = Path("runtime_state/latest_parse_plan.json")
PARSE_METRICS_PATH = Path("runtime_state/latest_parse_metrics.json")
ORCHESTRATED_PARSE_PATH = Path("runtime_state/latest_orchestrated_parse.json")
ORCHESTRATOR_REPORT_PATH = Path("runtime_state/latest_parse_orchestrator_report.json")


def save_parse_plan(plan: dict[str, Any]) -> None:
    write_json(PARSE_PLAN_PATH, plan)


def save_parse_metrics(metrics: dict[str, Any]) -> None:
    write_json(PARSE_METRICS_PATH, metrics)


def save_orchestrated_parse(orchestrated_parse: dict[str, Any]) -> None:
    write_json(ORCHESTRATED_PARSE_PATH, orchestrated_parse)


def save_report(report: dict[str, Any]) -> None:
    write_json(ORCHESTRATOR_REPORT_PATH, report)


def load_if_exists(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return {}
    return read_json(source)

