from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .os_click_backend import OsClickBackend
from .real_click_guard import merged_config, validate_preflight
from .schema import utc_now_iso


RUNTIME_DIR = Path("runtime_state")
CONFIG_PATH = Path("config/local_real_click_test.json")
RUN_PATH = RUNTIME_DIR / "latest_local_real_click_run.json"
REPORT_PATH = RUNTIME_DIR / "latest_local_real_click_report.json"


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
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
        runtime / "latest_local_real_click_run.json",
        runtime / "latest_local_real_click_report.json",
    )


def _empty_run(status: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "local_real_click_run_id": f"local_real_click_run_{uuid4().hex}",
        "task_id": "",
        "session_id": "",
        "status": status,
        "real_execution": False,
        "target_environment": config.get("target_environment", "local_html_only"),
        "action_id": "",
        "logical_skill": "",
        "option_id": "",
        "option_text": "",
        "click_point_screen": {},
        "guards_passed": False,
        "clicks_attempted": 0,
        "clicks_completed": 0,
        "created_at": utc_now_iso(),
    }


def _run_payload(
    status: str,
    config: dict[str, Any],
    preflight: dict[str, Any],
    *,
    guards_passed: bool,
    real_execution: bool,
    clicks_attempted: int,
    clicks_completed: int,
) -> dict[str, Any]:
    return {
        "local_real_click_run_id": f"local_real_click_run_{uuid4().hex}",
        "task_id": preflight.get("task_id", ""),
        "session_id": preflight.get("session_id", ""),
        "status": status,
        "real_execution": real_execution,
        "target_environment": config.get("target_environment", "local_html_only"),
        "action_id": preflight.get("action_id", ""),
        "logical_skill": preflight.get("logical_skill", ""),
        "option_id": preflight.get("option_id", ""),
        "option_text": preflight.get("option_text", ""),
        "click_point_screen": preflight.get("click_point_screen", {}),
        "guards_passed": guards_passed,
        "clicks_attempted": clicks_attempted,
        "clicks_completed": clicks_completed,
        "created_at": utc_now_iso(),
    }


def _report_payload(
    status: str,
    issues: list[dict[str, Any]],
    warnings: list[str],
    *,
    real_execution: bool,
    clicks_completed: int,
) -> dict[str, Any]:
    return {
        "validation_passed": not issues,
        "status": status,
        "issues": issues,
        "warnings": warnings,
        "real_execution": real_execution,
        "clicks_completed": clicks_completed,
        "created_at": utc_now_iso(),
    }


def _preflight_preview(preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": preflight.get("action_id", ""),
        "option_id": preflight.get("option_id", ""),
        "option_text": preflight.get("option_text", ""),
        "click_point_screen": preflight.get("click_point_screen", {}),
        "countdown_seconds": preflight.get("countdown_seconds", 0),
        "real_execution": True,
    }


def _print_preflight(preflight: dict[str, Any]) -> None:
    preview = _preflight_preview(preflight)
    print(json.dumps(preview, indent=2, ensure_ascii=False))


def _countdown(countdown_seconds: int, abort_file: str, sleep_fn: Any) -> bool:
    abort_path = Path(abort_file)
    for _remaining in range(max(0, countdown_seconds), 0, -1):
        if abort_path.exists():
            return False
        sleep_fn(1)
    return not abort_path.exists()


def run(
    source: str = "auto",
    *,
    confirm_local_html_test: bool = False,
    runtime_dir: str | Path = RUNTIME_DIR,
    config_path: str | Path = CONFIG_PATH,
    backend: Any | None = None,
    sleep_fn: Any = time.sleep,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _ = source
    runtime = Path(runtime_dir)
    config = merged_config(load_json(config_path))
    guard = load_json(runtime / "latest_execution_safety_guard.json")
    kvm_calibration = load_json(runtime / "latest_kvm_calibration.json")
    action_executor_preview = load_json(runtime / "latest_action_executor_preview.json")

    preflight, issues, warnings = validate_preflight(
        config,
        guard,
        kvm_calibration,
        action_executor_preview,
        confirm_local_html_test,
        runtime,
    )
    run_path, report_path = paths_for_runtime(runtime)

    if preflight is None:
        issue_codes = {item.get("code") for item in issues}
        status = (
            "cancelled"
            if issue_codes == {"abort_file_present"}
            else "blocked"
        )
        run_payload = _empty_run(status, config)
        report = _report_payload(
            status,
            issues,
            warnings,
            real_execution=False,
            clicks_completed=0,
        )
        save_json(run_path, run_payload)
        save_json(report_path, report)
        return run_payload, report

    if config.get("write_preflight_preview") is True:
        _print_preflight(preflight)

    if not _countdown(preflight["countdown_seconds"], preflight["abort_file"], sleep_fn):
        issue = {
            "code": "abort_file_present",
            "message": "Abort file appeared during countdown.",
            "abort_file": preflight["abort_file"],
        }
        run_payload = _run_payload(
            "cancelled",
            config,
            preflight,
            guards_passed=True,
            real_execution=True,
            clicks_attempted=0,
            clicks_completed=0,
        )
        report = _report_payload(
            "cancelled",
            [issue],
            warnings,
            real_execution=True,
            clicks_completed=0,
        )
        save_json(run_path, run_payload)
        save_json(report_path, report)
        return run_payload, report

    click_backend = backend if backend is not None else OsClickBackend()
    point = preflight["click_point_screen"]
    try:
        click_backend.click(point["x"], point["y"])
    except Exception as exc:  # pragma: no cover - exercised only by real backend failures.
        failure = {"code": "click_backend_failed", "message": str(exc)}
        run_payload = _run_payload(
            "failed",
            config,
            preflight,
            guards_passed=True,
            real_execution=True,
            clicks_attempted=1,
            clicks_completed=0,
        )
        report = _report_payload(
            "failed",
            [failure],
            warnings,
            real_execution=True,
            clicks_completed=0,
        )
        save_json(run_path, run_payload)
        save_json(report_path, report)
        return run_payload, report

    run_payload = _run_payload(
        "completed",
        config,
        preflight,
        guards_passed=True,
        real_execution=True,
        clicks_attempted=1,
        clicks_completed=1,
    )
    report = _report_payload(
        "completed",
        [],
        warnings,
        real_execution=True,
        clicks_completed=1,
    )
    save_json(run_path, run_payload)
    save_json(report_path, report)
    return run_payload, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run one guarded real click against the local HTML test page."
    )
    parser.add_argument("--source", choices=["auto"], default="auto")
    parser.add_argument("--confirm-local-html-test", action="store_true")
    args = parser.parse_args(argv)

    run_payload, report = run(
        args.source,
        confirm_local_html_test=args.confirm_local_html_test,
    )
    print(
        "Saved runtime_state/latest_local_real_click_run.json "
        f"(status={run_payload.get('status')}, "
        f"clicks_completed={run_payload.get('clicks_completed')})."
    )
    print(
        "Saved runtime_state/latest_local_real_click_report.json "
        f"(validation_passed={report.get('validation_passed')})."
    )


if __name__ == "__main__":
    main()
