from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import mouse_keyboard
from .human_simulator import HumanSimulator, HumanSimulatorConfig
from .schema import utc_now_iso
from .selection_verifier import verify_selected_state
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
        return None, [
            {
                "code": "gate_missing",
                "message": "latest_execution_gate.json is missing.",
            }
        ]
    try:
        return load_json(gate_path), []
    except (OSError, json.JSONDecodeError) as exc:
        return None, [{"code": "gate_invalid", "message": f"Unable to load execution gate: {exc}"}]


def _candidate_point(candidate: dict[str, Any]) -> dict[str, int] | None:
    point = candidate.get("click_point_screen")
    if not isinstance(point, dict):
        return None
    try:
        return {"x": int(round(float(point["x"]))), "y": int(round(float(point["y"])))}
    except (KeyError, TypeError, ValueError):
        return None


def _capture_after_click(capture_api: Any, runtime: Path) -> tuple[Path, dict[str, Any]]:
    if capture_api is None:
        from modules.action_executor import capture_after_click

        return capture_after_click.capture_after_click(runtime_state_dir=runtime)
    if hasattr(capture_api, "capture_after_click"):
        return capture_api.capture_after_click(runtime_state_dir=runtime)
    return capture_api.capture_locked_target(runtime_state_dir=runtime)


def _verification_status(result: Any) -> str:
    if not isinstance(result, dict):
        return "inconclusive"
    return str(result.get("status") or "inconclusive")


def _execute_record(
    record: dict[str, Any],
    *,
    runtime: Path,
    pause_ms: int,
    mouse_api: Any,
    capture_api: Any,
    verifier_api: Any,
    verify_click: bool,
    post_click_pause_ms: int,
) -> tuple[bool, dict[str, Any] | None]:
    if record.get("skill") == "scroll":
        direction = str(record.get("direction") or "down")
        amount = int(record.get("amount") or 3)
        signed_amount = -abs(amount) if direction == "down" else abs(amount)
        point = (
            record.get("click_point_screen")
            if isinstance(record.get("click_point_screen"), dict)
            else {}
        )
        try:
            actual_position = mouse_api.scroll(
                signed_amount,
                point.get("x") if point else None,
                point.get("y") if point else None,
            )
        except Exception as exc:  # noqa: BLE001
            record["status"] = "scroll_failed"
            return False, {
                "code": "scroll_failed",
                "message": str(exc),
                "action_id": record.get("action_id", ""),
            }
        if isinstance(actual_position, dict):
            record["actual_cursor_position"] = actual_position
        record["status"] = "scrolled"
        return True, None

    if record.get("skill") == "drag":
        try:
            result = mouse_api.drag_screen_points(
                record["start_point_screen"],
                record["end_point_screen"],
                pause_ms=pause_ms,
            )
        except Exception as exc:  # noqa: BLE001
            record["status"] = "drag_failed"
            return False, {
                "code": "drag_failed",
                "message": str(exc),
                "action_id": record.get("action_id", ""),
            }
        if isinstance(result, dict):
            record.update(result)
        record["status"] = "dragged"
        return True, None

    if record.get("skill") == "type_text":
        point = _candidate_point(
            {
                "click_point_screen": record.get("click_point_screen"),
            }
        )
        if point is None:
            record["status"] = "missing_text_target"
            return False, {
                "code": "missing_text_target",
                "message": "type_text action requires click_point_screen.",
                "action_id": record.get("action_id", ""),
            }
        try:
            actual_position = mouse_api.click_screen_point(
                point["x"],
                point["y"],
                pause_ms=pause_ms,
            )
            if post_click_pause_ms > 0:
                time.sleep(post_click_pause_ms / 1000.0)
            mouse_api.type_text(str(record.get("text") or ""))
        except Exception as exc:  # noqa: BLE001
            record["status"] = "type_failed"
            return False, {
                "code": "type_text_failed",
                "message": str(exc),
                "action_id": record.get("action_id", ""),
            }
        record["click_point_screen"] = point
        if isinstance(actual_position, dict):
            record["actual_cursor_position"] = actual_position
        record["status"] = "typed"
        return True, None

    attempts: list[dict[str, Any]] = []
    candidates = record.get("click_candidates")
    if not isinstance(candidates, list) or not candidates:
        candidates = [
            {
                "source": "click_point_screen",
                "click_point_screen": record["click_point_screen"],
                "is_primary": True,
            }
        ]

    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        point = _candidate_point(candidate)
        if point is None:
            attempts.append(
                {
                    "candidate_index": index,
                    "status": "skipped",
                    "reason": "missing_candidate_click_point_screen",
                }
            )
            continue

        attempt: dict[str, Any] = {
            "candidate_index": index,
            "source": candidate.get("source", ""),
            "click_point_screen": point,
        }
        try:
            actual_position = mouse_api.click_screen_point(
                point["x"],
                point["y"],
                pause_ms=pause_ms,
            )
        except Exception as exc:  # noqa: BLE001
            attempt["status"] = "click_failed"
            attempt["error"] = str(exc)
            attempts.append(attempt)
            continue

        if isinstance(actual_position, dict):
            attempt["actual_cursor_position"] = actual_position

        if post_click_pause_ms > 0:
            time.sleep(post_click_pause_ms / 1000.0)

        should_verify = verify_click and record.get("skill") != "click_navigation"
        if not should_verify:
            attempt["status"] = "clicked"
            attempts.append(attempt)
            record["click_point_screen"] = point
            if isinstance(actual_position, dict):
                record["actual_cursor_position"] = actual_position
            record["status"] = "clicked"
            return True, None

        try:
            capture_path, provenance = _capture_after_click(capture_api, runtime)
        except Exception as exc:  # noqa: BLE001
            attempt["status"] = "verification_blocked"
            attempt["verification"] = {
                "status": "inconclusive",
                "reason": f"capture_failed: {exc}",
            }
            attempts.append(attempt)
            record["status"] = "verification_blocked"
            record["click_attempts"] = attempts
            return False, {
                "code": "click_verification_blocked",
                "message": str(exc),
                "action_id": record.get("action_id", ""),
            }

        verifier = verifier_api or verify_selected_state
        try:
            verification = verifier(record, candidate, capture_path, provenance)
        except Exception as exc:  # noqa: BLE001
            verification = {
                "status": "inconclusive",
                "reason": f"verifier_failed: {exc}",
            }
        attempt["capture_path"] = str(capture_path)
        attempt["capture_provenance"] = provenance
        attempt["verification"] = verification if isinstance(verification, dict) else {}
        status = _verification_status(verification)
        if status == "selected":
            attempt["status"] = "clicked_verified"
            attempts.append(attempt)
            record["click_point_screen"] = point
            if isinstance(actual_position, dict):
                record["actual_cursor_position"] = actual_position
            record["verified_candidate_index"] = index
            record["verification"] = attempt["verification"]
            record["status"] = "clicked_verified"
            record["click_attempts"] = attempts
            return True, None
        if status != "not_selected":
            attempt["status"] = "verification_blocked"
            attempts.append(attempt)
            record["status"] = "verification_blocked"
            record["click_attempts"] = attempts
            return False, {
                "code": "click_verification_inconclusive",
                "message": str(
                    (attempt["verification"] or {}).get("reason")
                    or "Click verification was inconclusive."
                ),
                "action_id": record.get("action_id", ""),
            }
        attempt["status"] = "not_selected"
        attempts.append(attempt)

    record["status"] = "not_selected"
    record["click_attempts"] = attempts
    return False, {
        "code": "click_not_verified",
        "message": "No click candidate produced a verified selected state.",
        "action_id": record.get("action_id", ""),
    }


def run(
    source: str = "auto",
    dry_run: bool = False,
    pause_ms: int = 120,
    runtime_dir: str | Path | None = None,
    mouse_api: Any = mouse_keyboard,
    capture_api: Any = None,
    verifier_api: Any = None,
    verify_click: bool = True,
    post_click_pause_ms: int = 250,
    simulator_api: Any = None,
    human_config: HumanSimulatorConfig | None = None,
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
            runtime = RUNTIME_DIR if runtime_dir is None else Path(runtime_dir)
            simulator = simulator_api or HumanSimulator(mouse_api=mouse_api, config=human_config)
            for record in action_records:
                clicked, error = _execute_record(
                    record,
                    runtime=runtime,
                    pause_ms=pause_ms,
                    mouse_api=simulator,
                    capture_api=capture_api,
                    verifier_api=verifier_api,
                    verify_click=verify_click,
                    post_click_pause_ms=post_click_pause_ms,
                )
                if error is not None:
                    validation.setdefault("errors", []).append(
                        error
                    )
                if clicked:
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
    parser.add_argument("--post-click-pause-ms", type=int, default=250)
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--no-humanize-mouse", action="store_true")
    parser.add_argument("--no-humanize-typing", action="store_true")
    parser.add_argument("--nondeterministic", action="store_true")
    parser.add_argument("--typo-rate", type=float, default=0.0)
    args = parser.parse_args(argv)
    human_config = HumanSimulatorConfig(
        humanize_mouse=not args.no_humanize_mouse,
        humanize_typing=not args.no_humanize_typing,
        deterministic=not args.nondeterministic,
        typo_rate=max(0.0, min(1.0, args.typo_rate)),
    )
    run_payload, report = run(
        args.source,
        dry_run=args.dry_run,
        pause_ms=args.pause_ms,
        post_click_pause_ms=args.post_click_pause_ms,
        verify_click=not args.skip_verify,
        human_config=human_config,
    )
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
