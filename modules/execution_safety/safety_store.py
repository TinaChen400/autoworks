from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RUNTIME_DIR = Path("runtime_state")
CONFIG_DIR = Path("config")
EXECUTION_SAFETY_CONFIG_PATH = CONFIG_DIR / "execution_safety.json"
EXECUTION_GATE_PATH = RUNTIME_DIR / "latest_execution_gate.json"
SCHEDULER_RUN_PATH = RUNTIME_DIR / "latest_scheduler_run.json"
ACTION_EXECUTOR_PREVIEW_PATH = RUNTIME_DIR / "latest_action_executor_preview.json"
KVM_CALIBRATION_PATH = RUNTIME_DIR / "latest_kvm_calibration.json"
KVM_CALIBRATION_REPORT_PATH = RUNTIME_DIR / "latest_kvm_calibration_report.json"
EXECUTION_SAFETY_GUARD_PATH = RUNTIME_DIR / "latest_execution_safety_guard.json"
EXECUTION_SAFETY_GUARD_REPORT_PATH = RUNTIME_DIR / "latest_execution_safety_guard_report.json"


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


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
        runtime / "latest_execution_safety_guard.json",
        runtime / "latest_execution_safety_guard_report.json",
    )


def load_inputs(
    runtime_dir: str | Path | None = None,
    config_path: str | Path | None = None,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    runtime = Path(runtime_dir) if runtime_dir is not None else RUNTIME_DIR
    config = Path(config_path) if config_path is not None else EXECUTION_SAFETY_CONFIG_PATH
    return (
        load_json(config),
        load_json(runtime / "latest_execution_gate.json"),
        load_json(runtime / "latest_scheduler_run.json"),
        load_json(runtime / "latest_action_executor_preview.json"),
        load_json(runtime / "latest_kvm_calibration.json"),
        load_json(runtime / "latest_kvm_calibration_report.json"),
    )


def save_guard(guard: dict[str, Any], path: str | Path = EXECUTION_SAFETY_GUARD_PATH) -> Path:
    return save_json(path, guard)


def save_report(
    report: dict[str, Any],
    path: str | Path = EXECUTION_SAFETY_GUARD_REPORT_PATH,
) -> Path:
    return save_json(path, report)
