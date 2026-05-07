from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import mouse_keyboard
from .schema import utc_now_iso
from .safety_guard import validate_gate_for_real_execution


RUNTIME_DIR = Path("runtime_state")
EXECUTION_GATE_PATH = RUNTIME_DIR / "latest_execution_gate.json"
ACTION_EXECUTOR_RUN_PATH = RUNTIME_DIR / "latest_action_executor_run.json"
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


def paths_for_runtime(runtime_dir: str | Path) -> tuple[Path, Path, Path]:
    runtime = Path(runtime_dir)
    return (
        runtime / "latest_execution_gate.json",
        runtime / "latest_action_executor_run.json",
        runtime / "latest_action_executor_report.json",
    )


def _base_report(
    validation: dict[str, Any],
    dry_run: bool,
    execution_attempted: bool,
    executed_action_count: int,
    skipped_action_count: int,
    created_at: str,
) -> dict[str, Any]:
    return {
        "validation_passed": bool(validation.get("validation_passed")),
        "real_execution": (not dry_run) and execution_attempted,
        "execution_attempted": execution_attempted,
        "executed_action_count": executed_action_count,
        "skipped_action_count": skipped_action_count,
        "action_records": list(validation.get("action_records", [])),
        "errors": list(validation.get("errors", [])),
        "warnings": list(validation.get("warnings", [])),
        "created_at": created_at,
    }


def _load_gate_for_report(gate_path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not gate_path.exists():
        return None, [{"code": "gate_missing", "message": "latest_execution_gate.json is missing."}]
    try:
        return load_json(gate_path), []
    except (OSError, json.JSONDecodeError) as exc:
        return None, [{"code": "gate_invalid", "message": f"Unable to load execution gate: {exc}"}]


def run(
    source: str = "auto",
    dry_run: bool = False,
    pause_ms: int = 120,
    runtime_dir: str | Path | None = None,
    mouse_api: Any = mouse_keyboard,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _ = source
    gate_path, run_path, report_path = (
        (EXECUTION_GATE_PATH, ACTION_EXECUTOR_RUN_PATH, ACTION_EXECUTOR_REPORT_PATH)
        if runtime_dir is None
        else paths_for_runtime(runtime_dir)
    )
    created_at = utc_now_iso()
    gate, load_errors = _load_gate_for_report(gate_path)
    validation = validate_gate_for_real_execution(gate, dry_run)
    if load_errors:
        validation["errors"] = load_errors
        validation["validation_passed"] = False
        validation["action_records"] = []

    execution_attempted = False
    executed_action_count = 0
    action_records = list(validation.get("action_records", []))

    if validation.get("validation_passed") is True:
        execution_attempted = True
        if dry_run:
            executed_action_count = len(action_records)
        else:
            for record in action_records:
                point = record["click_point_screen"]
                try:
                    mouse_api.click_screen_point(point["x"], point["y"], pause_ms=pause_ms)
                except Exception as exc:  # noqa: BLE001
                    record["status"] = "failed"
                    validation.setdefault("errors", []).append(
                        {
                            "code": "mouse_click_failed",
                            "message": str(exc),
                            "action_id": record.get("action_id", ""),
                        }
                    )
                    continue
                record["status"] = "clicked"
                executed_action_count += 1

    skipped_action_count = max(int(validation.get("action_count", 0)) - executed_action_count, 0)
    validation["action_records"] = action_records
    if validation.get("errors"):
        validation["validation_passed"] = False

    report = _base_report(
        validation,
        dry_run,
        execution_attempted,
        executed_action_count,
        skipped_action_count,
        created_at,
    )
    if report["validation_passed"]:
        status = "completed"
    elif execution_attempted:
        status = "failed"
    else:
        status = "blocked"
    run_payload = {
        "action_executor_run_id": f"action_executor_run_{uuid4().hex}",
        "task_id": gate.get("task_id", "") if isinstance(gate, dict) else "",
        "session_id": gate.get("session_id", "") if isinstance(gate, dict) else "",
        "source_execution_gate_id": (
            gate.get("execution_gate_id", "") if isinstance(gate, dict) else ""
        ),
        "source": "execution_gate",
        "status": status,
        "dry_run": dry_run,
        **report,
    }

    save_json(run_path, run_payload)
    save_json(report_path, report)
    return run_payload, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Execute approved click actions from latest_execution_gate.json."
    )
    parser.add_argument("--source", choices=["auto"], default="auto")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pause-ms", type=int, default=120)
    args = parser.parse_args(argv)
    run_payload, report = run(args.source, dry_run=args.dry_run, pause_ms=args.pause_ms)
    print(
        "Saved runtime_state/latest_action_executor_run.json "
        f"(status={run_payload.get('status')}, real_execution={report.get('real_execution')})."
    )
    print(
        "Saved runtime_state/latest_action_executor_report.json "
        f"(validation_passed={report.get('validation_passed')}, "
        f"executed_action_count={report.get('executed_action_count')})."
    )


if __name__ == "__main__":
    main()
