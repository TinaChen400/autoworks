from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.autoworks_runner.pipeline_state import PROJECT_ROOT, PipelineState, read_json
from modules.autoworks_runner.pipeline_steps import (
    PipelineStepDefinition,
    existing_outputs,
    missing_outputs,
    module_is_available,
    run_python_module,
)
from modules.page_state_manager.session_lite import classify_flow_status


RUNTIME_STATE_DIR = PROJECT_ROOT / "runtime_state"
RUNTIME_CAPTURE_PATH = RUNTIME_STATE_DIR / "latest_capture.png"
SESSION_LOOP_REPORT_PATH = RUNTIME_STATE_DIR / "latest_session_loop_report.json"
NO_LOCKED_TARGET_MESSAGE = (
    "No locked target window. Please snap and lock the KVM/remote window before running preview."
)
NO_VALID_CAPTURE_MESSAGE = (
    "No valid existing capture found. Please use capture panel to snap, lock, and capture first."
)

MODULES = {
    "context_mapper": "modules.context_mapper.capture_context",
    "perception_indexer": "modules.perception_indexer.indexer",
    "parse_orchestrator": "modules.parse_orchestrator.orchestrator",
    "page_state_manager": "modules.page_state_manager.session_manager",
    "answer_engine": "modules.answer_engine.answer_engine",
    "action_plan": "modules.action_plan.action_plan_builder",
    "target_resolver": "modules.target_resolver.target_resolver",
    "execution_gate": "modules.execution_gate.execution_gate",
    "human_review": "modules.human_review.human_review_processor",
    "click_preview": "modules.action_executor.preview_adapter",
    "action_executor": "modules.action_executor.action_executor",
}

RUNTIME_OUTPUTS = {
    "target_lock_check": {
        "lock": RUNTIME_STATE_DIR / "latest_locked_target.json",
    },
    "window_capture": {
        "screenshot": RUNTIME_CAPTURE_PATH,
        "provenance": RUNTIME_STATE_DIR / "latest_capture_provenance.json",
    },
    "existing_capture_check": {
        "screenshot": RUNTIME_CAPTURE_PATH,
        "provenance": RUNTIME_STATE_DIR / "latest_capture_provenance.json",
    },
    "context_mapper": {
        "runtime_context": RUNTIME_STATE_DIR / "latest_runtime_context.json",
    },
    "perception_indexer": {
        "layout_index": RUNTIME_STATE_DIR / "latest_layout_index.json",
        "annotated_overview": RUNTIME_STATE_DIR / "latest_annotated_overview.png",
        "report": RUNTIME_STATE_DIR / "latest_perception_report.json",
    },
    "parse_orchestrator": {
        "parse": RUNTIME_STATE_DIR / "latest_orchestrated_parse.json",
        "report": RUNTIME_STATE_DIR / "latest_parse_orchestrator_report.json",
    },
    "parse_quality_gate": {
        "parse": RUNTIME_STATE_DIR / "latest_orchestrated_parse.json",
    },
    "page_state_manager": {
        "session": RUNTIME_STATE_DIR / "latest_survey_session.json",
        "report": RUNTIME_STATE_DIR / "latest_session_update_report.json",
    },
    "answer_engine": {
        "decision": RUNTIME_STATE_DIR / "latest_answer_decision.json",
        "report": RUNTIME_STATE_DIR / "latest_answer_engine_report.json",
    },
    "action_plan": {
        "plan": RUNTIME_STATE_DIR / "latest_action_plan.json",
        "report": RUNTIME_STATE_DIR / "latest_action_plan_report.json",
    },
    "target_resolver": {
        "resolved_plan": RUNTIME_STATE_DIR / "latest_resolved_action_plan.json",
        "report": RUNTIME_STATE_DIR / "latest_target_resolver_report.json",
    },
    "execution_gate": {
        "gate": RUNTIME_STATE_DIR / "latest_execution_gate.json",
        "report": RUNTIME_STATE_DIR / "latest_execution_gate_report.json",
    },
    "human_review": {
        "reviewed_decision": RUNTIME_STATE_DIR / "latest_reviewed_answer_decision.json",
        "report": RUNTIME_STATE_DIR / "latest_human_review_report.json",
    },
    "click_preview": {
        "preview": RUNTIME_STATE_DIR / "latest_action_executor_preview.json",
    },
    "action_executor": {
        "report": RUNTIME_STATE_DIR / "latest_action_executor_report.json",
        "scheduler_run": RUNTIME_STATE_DIR / "latest_scheduler_run.json",
    },
}

PIPELINE_STEPS = [
    "target_lock_check",
    "window_capture",
    "existing_capture_check",
    "context_mapper",
    "perception_indexer",
    "parse_orchestrator",
    "parse_quality_gate",
    "page_state_manager",
    "answer_engine",
    "action_plan",
    "target_resolver",
    "execution_gate",
    "human_review",
    "click_preview",
    "action_executor",
]


def run_once(
    *,
    task_id: str = "tts01",
    mode: str = "preview",
    parser_mode: str = "doubao",
    output_level: str = "standard",
    max_model_calls: int = 3,
    ocr_backend: str = "disabled",
    allow_fake: bool = False,
    allow_fixture: bool = False,
    use_existing_capture: bool = False,
    runtime_state_dir: Path = RUNTIME_STATE_DIR,
) -> dict[str, Any]:
    runtime_state_dir = Path(runtime_state_dir)
    steps = build_step_definitions(
        mode=mode,
        task_id=task_id,
        parser_mode=parser_mode,
        output_level=output_level,
        max_model_calls=max_model_calls,
        ocr_backend=ocr_backend,
        runtime_state_dir=runtime_state_dir,
        use_existing_capture=use_existing_capture,
    )
    state = PipelineState(
        steps=[step.name for step in steps],
        runtime_state_dir=runtime_state_dir,
        mode=mode,
        task_id=task_id,
    )
    state.initialize()
    run_started_at = datetime.fromisoformat(state.started_at) if state.started_at else datetime.now()

    for step in steps:
        if step.name == "action_executor":
            if mode != "click-once":
                state.finish_step(
                    step.name,
                    "skipped",
                    summary="action executor is disabled outside click-once mode",
                    output_paths=existing_outputs(
                        step.expected_outputs,
                        min_mtime=run_started_at,
                    ),
                    warnings=[],
                    errors=[],
                    metadata={"required": step.required},
                )
                continue
            allowed, reason = approved_for_execution(runtime_state_dir, run_started_at=run_started_at)
            if not allowed:
                finish_not_allowed(state, step, reason, run_started_at=run_started_at)
                state.complete("blocked")
                return state.to_dict()

        if step.name == "context_mapper":
            allowed, reason = capture_provenance_allows_context(
                runtime_state_dir,
                run_started_at=run_started_at,
                allow_fixture=allow_fixture,
            )
            if not allowed:
                finish_blocked_precondition(state, step, reason, run_started_at=run_started_at)
                state.block_remaining(step.name, reason)
                state.complete("blocked")
                return state.to_dict()

        if step.name == "perception_indexer":
            allowed, reason = runtime_context_uses_fresh_capture(
                runtime_state_dir,
                run_started_at=run_started_at,
            )
            if not allowed:
                finish_blocked_precondition(state, step, reason, run_started_at=run_started_at)
                state.block_remaining(step.name, reason)
                state.complete("blocked")
                return state.to_dict()

        if step.name == "parse_orchestrator":
            allowed, reason = annotated_overview_after_capture(runtime_state_dir)
            if not allowed:
                finish_blocked_precondition(state, step, reason, run_started_at=run_started_at)
                state.block_remaining(step.name, reason)
                state.complete("blocked")
                return state.to_dict()
            input_errors = parse_input_freshness_errors(
                runtime_state_dir,
                run_started_at=run_started_at,
                use_existing_capture=use_existing_capture,
            )
            if input_errors:
                summary = "parse_orchestrator inputs are missing or stale"
                state.finish_step(
                    step.name,
                    "blocked",
                    summary=summary,
                    output_paths={},
                    warnings=[],
                    errors=input_errors,
                    metadata={"required": step.required, "stale_file_errors": input_errors},
                )
                state.write_event("stale_file_errors", step=step.name, errors=input_errors)
                state.block_remaining(step.name, summary)
                state.metadata["image_provenance"] = collect_image_provenance(runtime_state_dir)
                state.write_event(
                    "image_provenance",
                    step=step.name,
                    provenance=state.metadata["image_provenance"],
                )
                state.complete("blocked")
                return state.to_dict()

        state.start_step(step.name)
        result = run_pipeline_step(
            step,
            runtime_state_dir=runtime_state_dir,
            run_started_at=run_started_at,
            allow_fake=allow_fake,
            allow_fixture=allow_fixture,
            use_existing_capture=use_existing_capture,
        )
        status = result["status"]
        if status == "skipped" and step.required:
            status = "blocked"
            result["summary"] = result.get("summary") or f"required step {step.name} was skipped"
            result.setdefault("errors", []).append(result["summary"])

        if status == "success" and step.name == "execution_gate":
            allowed, reason = gate_allows_execution(runtime_state_dir, run_started_at=run_started_at)
            if not allowed:
                status = "not_allowed"
                result["summary"] = reason
        elif status == "success" and step.name == "human_review":
            if mode == "click-once":
                approved, reason = human_review_approved(runtime_state_dir, run_started_at=run_started_at)
                if not approved:
                    status = "waiting_review"
                    result["summary"] = reason
            else:
                clear, reason = human_review_clear_for_preview(
                    runtime_state_dir,
                    run_started_at=run_started_at,
                )
                if not clear:
                    status = "waiting_review"
                    result["summary"] = reason
        state.finish_step(
            step.name,
            status,
            summary=result.get("summary", ""),
            output_paths=result.get("output_paths", {}),
            warnings=result.get("warnings", []),
            errors=result.get("errors", []),
            metadata={**result.get("metadata", {}), "required": step.required},
        )
        if step.name in {"window_capture", "existing_capture_check"}:
            state.metadata["capture_provenance"] = result.get("metadata", {})
            state.metadata.update(result.get("metadata", {}))
        state.metadata["image_provenance"] = collect_image_provenance(runtime_state_dir)
        state.write_event(
            "image_provenance",
            step=step.name,
            provenance=state.metadata["image_provenance"],
        )
        state.write()

        if status == "failed" and step.required:
            state.block_remaining(step.name, result.get("summary", "required step failed"))
            state.complete("failed")
            return state.to_dict()
        if status in {"blocked", "not_allowed"} and step.required:
            state.block_remaining(step.name, result.get("summary", "required step blocked"))
            state.complete("blocked")
            return state.to_dict()
        if status == "waiting_review" and step.required:
            state.block_remaining(step.name, result.get("summary", "waiting for human review"))
            state.complete("waiting_review")
            return state.to_dict()

    state.metadata["image_provenance"] = collect_image_provenance(runtime_state_dir)
    state.complete(compute_overall_status(state.to_dict()["steps"], steps))
    return state.to_dict()


def run_session_until_terminal(
    *,
    task_id: str = "tts01",
    parser_mode: str = "doubao",
    output_level: str = "standard",
    max_model_calls: int = 3,
    ocr_backend: str = "disabled",
    allow_fake: bool = False,
    allow_fixture: bool = False,
    max_pages: int = 50,
    wait_after_navigation_seconds: float = 1.0,
    runtime_state_dir: Path = RUNTIME_STATE_DIR,
) -> dict[str, Any]:
    runtime_state_dir = Path(runtime_state_dir)
    runs: list[dict[str, Any]] = []
    stop_reason = "max_pages_reached"
    for page_number in range(1, max_pages + 1):
        state = run_once(
            task_id=task_id,
            mode="click-once",
            parser_mode=parser_mode,
            output_level=output_level,
            max_model_calls=max_model_calls,
            ocr_backend=ocr_backend,
            allow_fake=allow_fake,
            allow_fixture=allow_fixture,
            use_existing_capture=False,
            runtime_state_dir=runtime_state_dir,
        )
        session = read_json(runtime_state_dir / "latest_survey_session.json")
        action_plan = read_json(runtime_state_dir / "latest_action_plan.json")
        executor_report = read_json(runtime_state_dir / "latest_action_executor_report.json")
        flow_status = str(session.get("flow_status") or "")
        action_plan_status = str(action_plan.get("status") or "")
        executed_count = int(executor_report.get("executed_action_count") or 0)
        run_summary = {
            "page_number": page_number,
            "run_id": state.get("run_id", ""),
            "overall_status": state.get("overall_status", ""),
            "flow_status": flow_status,
            "action_plan_status": action_plan_status,
            "executed_action_count": executed_count,
        }
        runs.append(run_summary)

        if flow_status in {"finished", "kicked_out"}:
            stop_reason = f"terminal_flow_status:{flow_status}"
            break
        if action_plan_status == "no_action":
            stop_reason = "no_action"
            break
        if state.get("overall_status") in {"blocked", "waiting_review", "failed"}:
            stop_reason = f"pipeline_{state.get('overall_status')}"
            break
        if executed_count <= 0:
            stop_reason = "no_actions_executed"
            break
        if wait_after_navigation_seconds > 0:
            import time

            time.sleep(wait_after_navigation_seconds)

    report = {
        "status": "completed" if stop_reason.startswith("terminal_flow_status") else "stopped",
        "stop_reason": stop_reason,
        "run_count": len(runs),
        "max_pages": max_pages,
        "runs": runs,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    output_path = runtime_state_dir / "latest_session_loop_report.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_step_definitions(
    *,
    mode: str,
    task_id: str,
    parser_mode: str,
    output_level: str,
    max_model_calls: int,
    ocr_backend: str,
    runtime_state_dir: Path,
    use_existing_capture: bool = False,
) -> list[PipelineStepDefinition]:
    outputs = outputs_for_runtime(runtime_state_dir)
    click_preview_available = module_is_available(MODULES["click_preview"])
    common_required = {
        "target_lock_check",
        "window_capture",
        "existing_capture_check",
        "context_mapper",
        "perception_indexer",
        "parse_orchestrator",
        "parse_quality_gate",
        "page_state_manager",
        "answer_engine",
        "action_plan",
        "target_resolver",
    }
    if mode == "click-once":
        common_required.update({"execution_gate", "human_review", "action_executor"})
    elif mode == "preview" and click_preview_available:
        common_required.add("click_preview")

    capture_steps = []
    if not use_existing_capture:
        capture_steps.extend(
            [
                PipelineStepDefinition(
                    name="target_lock_check",
                    required=True,
                    module_name=None,
                    expected_outputs=outputs["target_lock_check"],
                    kind="target_lock_check",
                ),
                PipelineStepDefinition(
                    name="window_capture",
                    required=True,
                    module_name=None,
                    expected_outputs=outputs["window_capture"],
                    kind="function",
                ),
            ]
        )

    steps = [
        *capture_steps,
        PipelineStepDefinition(
            name="existing_capture_check",
            required=True,
            module_name=None,
            expected_outputs=outputs["existing_capture_check"],
            kind="existing_capture_check",
        ),
        PipelineStepDefinition(
            name="context_mapper",
            required=True,
            module_name=MODULES["context_mapper"],
            args=[
                "--task",
                task_id,
                "--screenshot",
                str(runtime_state_dir / "latest_capture.png"),
                "--output",
                str(runtime_state_dir / "latest_runtime_context.json"),
            ],
            expected_outputs=outputs["context_mapper"],
        ),
        PipelineStepDefinition(
            name="perception_indexer",
            required=True,
            module_name=MODULES["perception_indexer"],
            args=["--ocr", ocr_backend],
            expected_outputs=outputs["perception_indexer"],
        ),
        PipelineStepDefinition(
            name="parse_orchestrator",
            required=True,
            module_name=MODULES["parse_orchestrator"],
            args=[
                "--mode",
                parser_mode,
                "--output-level",
                output_level,
                "--max-model-calls",
                str(max_model_calls),
            ],
            expected_outputs=outputs["parse_orchestrator"],
        ),
        PipelineStepDefinition(
            name="parse_quality_gate",
            required=True,
            module_name=None,
            expected_outputs=outputs["parse_quality_gate"],
            kind="quality_gate",
        ),
        PipelineStepDefinition(
            name="page_state_manager",
            required="page_state_manager" in common_required,
            module_name=MODULES["page_state_manager"],
            args=["--task", task_id],
            expected_outputs=outputs["page_state_manager"],
        ),
        PipelineStepDefinition(
            name="answer_engine",
            required="answer_engine" in common_required,
            module_name=MODULES["answer_engine"],
            expected_outputs=outputs["answer_engine"],
        ),
        PipelineStepDefinition(
            name="action_plan",
            required="action_plan" in common_required,
            module_name=MODULES["action_plan"],
            expected_outputs=outputs["action_plan"],
        ),
        PipelineStepDefinition(
            name="target_resolver",
            required="target_resolver" in common_required,
            module_name=MODULES["target_resolver"],
            expected_outputs=outputs["target_resolver"],
        ),
        PipelineStepDefinition(
            name="execution_gate",
            required="execution_gate" in common_required,
            module_name=MODULES["execution_gate"],
            expected_outputs=outputs["execution_gate"],
        ),
        PipelineStepDefinition(
            name="human_review",
            required="human_review" in common_required,
            module_name=MODULES["human_review"],
            expected_outputs=outputs["human_review"],
        ),
        PipelineStepDefinition(
            name="click_preview",
            required="click_preview" in common_required,
            module_name=MODULES["click_preview"],
            expected_outputs=outputs["click_preview"],
            optional_when_missing=True,
        ),
        PipelineStepDefinition(
            name="action_executor",
            required="action_executor" in common_required,
            module_name=MODULES["action_executor"],
            expected_outputs=outputs["action_executor"],
        ),
    ]
    if mode in {"dry-run", "preview"}:
        return steps
    if mode == "click-once":
        return steps
    raise ValueError(f"unknown pipeline mode: {mode}")


def run_pipeline_step(
    step: PipelineStepDefinition,
    *,
    runtime_state_dir: Path,
    run_started_at: datetime,
    allow_fake: bool,
    allow_fixture: bool,
    use_existing_capture: bool = False,
) -> dict[str, Any]:
    if step.kind == "target_lock_check" and step.name == "target_lock_check":
        return run_target_lock_check(
            runtime_state_dir,
            run_started_at=run_started_at,
            allow_fixture=allow_fixture,
        )
    if step.kind == "function" and step.name == "window_capture":
        return run_window_capture(
            runtime_state_dir,
            run_started_at=run_started_at,
            allow_fixture=allow_fixture,
        )
    if step.kind == "existing_capture_check" and step.name == "existing_capture_check":
        return run_existing_capture_check(runtime_state_dir, run_started_at=run_started_at)
    if step.kind == "quality_gate" and step.name == "parse_quality_gate":
        return run_parse_quality_gate(
            runtime_state_dir,
            run_started_at=run_started_at,
            allow_fake=allow_fake,
        )
    if step.optional_when_missing and not module_is_available(step.module_name):
        return {
            "status": "skipped",
            "summary": f"optional step {step.name} is not implemented",
            "output_paths": {},
            "warnings": [f"optional step {step.name} is not implemented"],
            "errors": [],
            "metadata": {"module": step.module_name},
        }
    if not step.module_name:
        return {
            "status": "skipped",
            "summary": f"step {step.name} has no module implementation",
            "output_paths": {},
            "warnings": [],
            "errors": [f"step {step.name} has no module implementation"],
            "metadata": {},
        }
    result = run_python_module(
        step.module_name,
        step.args,
        step.expected_outputs,
        cwd=PROJECT_ROOT,
        min_mtime=run_started_at,
    )
    if result["status"] == "success" and step.name == "perception_indexer":
        perception_issues = perception_output_issues(runtime_state_dir, run_started_at=run_started_at)
        if perception_issues:
            result["status"] = "failed"
            result["summary"] = "perception_indexer output mismatch: " + "; ".join(perception_issues)
            result.setdefault("errors", []).extend(perception_issues)
    if result["status"] == "failed" and step.name == "parse_orchestrator":
        message = " ".join(result.get("errors", []) + [result.get("summary", "")])
        if "Please run perception_indexer first" in message and perception_outputs_are_fresh(
            runtime_state_dir,
            run_started_at=run_started_at,
        ):
            result["summary"] = (
                "adapter/output mismatch: parse_orchestrator could not see fresh "
                "perception_indexer outputs"
            )
            result.setdefault("errors", []).append(result["summary"])
    if result["status"] == "success" and step.name == "parse_orchestrator":
        selected_mode = parse_selected_mode(runtime_state_dir)
        if selected_mode == "fake" and not allow_fake:
            result["status"] = "blocked"
            result["summary"] = "parse_orchestrator selected fake mode; rerun with --allow-fake to permit it"
            result.setdefault("errors", []).append(result["summary"])
        model_input_issue = stale_model_input_issue(runtime_state_dir, run_started_at=run_started_at)
        if model_input_issue:
            result["status"] = "blocked"
            result["summary"] = model_input_issue
            result.setdefault("errors", []).append(model_input_issue)
    if result["status"] == "success" and step.name == "page_state_manager":
        issues = page_state_manager_output_issues(runtime_state_dir, run_started_at=run_started_at)
        if issues:
            result["status"] = "failed"
            result["summary"] = "page_state_manager output invalid: " + "; ".join(issues)
            result.setdefault("errors", []).extend(issues)
    return result


def run_target_lock_check(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    try:
        from modules.window_capture.target_lock import validate_locked_target
    except Exception as exc:
        return {
            "status": "blocked",
            "summary": NO_LOCKED_TARGET_MESSAGE,
            "output_paths": {},
            "warnings": [],
            "errors": [NO_LOCKED_TARGET_MESSAGE, str(exc)],
            "metadata": {"target_locked": False},
        }

    ok, target, reason = validate_locked_target(runtime_state_dir)
    output_paths = existing_outputs(
        {"lock": runtime_state_dir / "latest_locked_target.json"},
        min_mtime=None,
    )
    metadata = capture_metadata_from_target(target)
    if not ok:
        if allow_fixture:
            return {
                "status": "success",
                "summary": "no locked target; fixture capture explicitly allowed",
                "output_paths": output_paths,
                "warnings": [reason or NO_LOCKED_TARGET_MESSAGE],
                "errors": [],
                "metadata": {
                    "target_locked": False,
                    "capture_source": "fixture",
                    "fixture_allowed": True,
                },
            }
        metadata["target_locked"] = False
        return {
            "status": "blocked",
            "summary": reason or NO_LOCKED_TARGET_MESSAGE,
            "output_paths": output_paths,
            "warnings": [],
            "errors": [reason or NO_LOCKED_TARGET_MESSAGE],
            "metadata": metadata,
        }
    metadata["target_locked"] = True
    return {
        "status": "success",
        "summary": "locked target window is valid",
        "output_paths": output_paths,
        "warnings": [],
        "errors": [],
        "metadata": metadata,
    }


def run_window_capture(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    try:
        from modules.window_capture.target_lock import capture_locked_target
    except Exception as exc:
        if allow_fixture:
            path, provenance = capture_fixture(runtime_state_dir, output_path=runtime_state_dir / "latest_capture.png")
            return {
                "status": "success",
                "summary": f"captured fixture screenshot to {path}",
                "output_paths": {
                    "screenshot": str(path),
                    "provenance": str(runtime_state_dir / "latest_capture_provenance.json"),
                },
                "warnings": [str(exc)],
                "errors": [],
                "metadata": provenance,
            }
        return {
            "status": "blocked",
            "summary": NO_LOCKED_TARGET_MESSAGE,
            "output_paths": {},
            "warnings": [],
            "errors": [NO_LOCKED_TARGET_MESSAGE, str(exc)],
            "metadata": {"target_locked": False, "capture_source": "none"},
        }

    output_path = runtime_state_dir / "latest_capture.png"
    provenance_path = runtime_state_dir / "latest_capture_provenance.json"
    try:
        path, provenance = capture_locked_target(
            runtime_state_dir=runtime_state_dir,
            output_path=output_path,
        )
    except Exception as exc:
        if not allow_fixture:
            return {
                "status": "blocked",
                "summary": str(exc) or NO_LOCKED_TARGET_MESSAGE,
                "output_paths": {},
                "warnings": [],
                "errors": [str(exc) or NO_LOCKED_TARGET_MESSAGE],
                "metadata": {"target_locked": False, "capture_source": "none"},
            }
        path, provenance = capture_fixture(runtime_state_dir, output_path=output_path)

    stale = missing_outputs(
        {"screenshot": path, "provenance": provenance_path},
        min_mtime=run_started_at,
    )
    if stale:
        return {
            "status": "failed",
            "summary": "window_capture output is missing or stale",
            "output_paths": {},
            "warnings": [],
            "errors": ["window_capture output is missing or stale: " + ", ".join(stale)],
            "metadata": provenance,
        }
    return {
        "status": "success",
        "summary": f"captured screenshot to {path}",
        "output_paths": {"screenshot": str(path), "provenance": str(provenance_path)},
        "warnings": [],
        "errors": [],
        "metadata": provenance,
    }


def run_existing_capture_check(runtime_state_dir: Path, *, run_started_at: datetime) -> dict[str, Any]:
    try:
        existing_capture_provenance = read_capture_provenance(runtime_state_dir)
        provenance = validate_existing_capture(runtime_state_dir / "latest_capture.png")
    except Exception as exc:
        return {
            "status": "blocked",
            "summary": NO_VALID_CAPTURE_MESSAGE,
            "output_paths": {},
            "warnings": [],
            "errors": [NO_VALID_CAPTURE_MESSAGE, str(exc)],
            "metadata": {
                "capture_source": "existing_capture",
                "target_locked": False,
            },
        }

    provenance_path = runtime_state_dir / "latest_capture_provenance.json"
    if existing_capture_provenance_references_capture(
        existing_capture_provenance,
        runtime_state_dir / "latest_capture.png",
    ):
        return {
            "status": "success",
            "summary": "validated runtime_state/latest_capture.png",
            "output_paths": {
                "screenshot": str(runtime_state_dir / "latest_capture.png"),
                "provenance": str(provenance_path),
            },
            "warnings": [],
            "errors": [],
            "metadata": existing_capture_provenance,
        }

    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "success",
        "summary": "validated runtime_state/latest_capture.png",
        "output_paths": {
            "screenshot": str(runtime_state_dir / "latest_capture.png"),
            "provenance": str(provenance_path),
        },
        "warnings": [],
        "errors": [],
        "metadata": provenance,
    }


def existing_capture_provenance_references_capture(
    provenance: dict[str, Any],
    capture_path: Path,
) -> bool:
    if not provenance:
        return False
    if provenance.get("capture_source") not in {"locked_target", "fixture"}:
        return False
    screenshot_path = str(provenance.get("screenshot_path") or provenance.get("capture_path") or "")
    if not screenshot_path:
        return False
    return Path(screenshot_path).resolve(strict=False) == capture_path.resolve(strict=False)


def validate_existing_capture(path: Path) -> dict[str, Any]:
    from PIL import Image

    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_file():
        raise ValueError(f"capture path is not a file: {path}")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image_width, image_height = image.size
    except Exception as exc:
        raise ValueError(f"capture is not a valid image: {path}") from exc
    if image_width <= 0 or image_height <= 0:
        raise ValueError(f"capture image has invalid dimensions: {image_width}x{image_height}")

    return {
        "capture_source": "existing_capture",
        "target_locked": False,
        "target_window_title": "",
        "target_window_handle": None,
        "locked_region": {},
        "bbox": {},
        "dpi_scale": None,
        "capture_path": str(path),
        "screenshot_path": str(path),
        "capture_mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "screenshot_mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "image_width": image_width,
        "image_height": image_height,
        "image_hash": file_sha256(path),
        "created_at": datetime.now().isoformat(),
    }


def capture_fixture(runtime_state_dir: Path, *, output_path: Path) -> tuple[Path, dict[str, Any]]:
    from PIL import Image

    fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "latest_capture.png"
    if not fixture_path.exists():
        raise RuntimeError("fixture capture requested but tests/fixtures/latest_capture.png is missing")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture_path, output_path)
    with Image.open(output_path) as image:
        image_width, image_height = image.size
    provenance = {
        "capture_source": "fixture",
        "target_locked": False,
        "target_window_title": "",
        "target_window_handle": None,
        "locked_region": {},
        "bbox": {},
        "dpi_scale": None,
        "screenshot_path": str(output_path),
        "screenshot_mtime": datetime.fromtimestamp(output_path.stat().st_mtime).isoformat(),
        "image_width": image_width,
        "image_height": image_height,
        "image_hash": file_sha256(output_path),
        "created_at": datetime.now().isoformat(),
    }
    provenance_path = runtime_state_dir / "latest_capture_provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path, provenance


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_parse_quality_gate(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
    allow_fake: bool,
) -> dict[str, Any]:
    expected_outputs = {"parse": runtime_state_dir / "latest_orchestrated_parse.json"}
    missing = missing_outputs(expected_outputs, min_mtime=run_started_at)
    if missing:
        return {
            "status": "blocked",
            "summary": "parse output is missing or stale",
            "output_paths": existing_outputs(expected_outputs, min_mtime=run_started_at),
            "warnings": [],
            "errors": ["parse output is missing or stale: " + ", ".join(missing)],
            "metadata": {},
        }

    orchestrated = read_json(expected_outputs["parse"])
    issues = parse_quality_issues(orchestrated, allow_fake=allow_fake)
    if issues:
        status = "waiting_review" if any("needs_human_review" in issue for issue in issues) else "blocked"
        return {
            "status": status,
            "summary": "; ".join(issues),
            "output_paths": existing_outputs(expected_outputs, min_mtime=run_started_at),
            "warnings": [],
            "errors": issues,
            "metadata": {
                "selected_mode": parse_selected_mode(runtime_state_dir),
                "quality_gate": "content",
            },
        }
    return {
        "status": "success",
        "summary": "parse content quality passed",
        "output_paths": existing_outputs(expected_outputs, min_mtime=run_started_at),
        "warnings": [],
        "errors": [],
        "metadata": {"quality_gate": "content"},
    }


def parse_input_freshness_errors(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
    use_existing_capture: bool = False,
) -> list[str]:
    capture_path = runtime_state_dir / "latest_capture.png"
    required_inputs = {
        "latest_runtime_context": runtime_state_dir / "latest_runtime_context.json",
        "latest_layout_index": runtime_state_dir / "latest_layout_index.json",
        "latest_annotated_overview": runtime_state_dir / "latest_annotated_overview.png",
    }
    if use_existing_capture:
        if not capture_path.exists():
            return ["missing or stale parse input: " + str(capture_path)]
        min_mtime = datetime.fromtimestamp(capture_path.stat().st_mtime)
    else:
        required_inputs["latest_capture"] = capture_path
        min_mtime = run_started_at

    stale = missing_outputs(required_inputs, min_mtime=min_mtime)
    return ["missing or stale parse input: " + path for path in stale]


def stale_model_input_issue(runtime_state_dir: Path, *, run_started_at: datetime) -> str:
    model_input_path = runtime_state_dir / "latest_model_input.png"
    if not model_input_path.exists():
        return ""
    if model_input_path.stat().st_mtime >= run_started_at.timestamp():
        return ""
    orchestrated = read_json(runtime_state_dir / "latest_orchestrated_parse.json")
    selected_images = orchestrated.get("parse_plan", {}).get("selected_input_images") or []
    input_image_used = (
        orchestrated.get("parsed_page", {}).get("metadata", {}).get("input_image_used") or ""
    )
    referenced = [*selected_images, input_image_used]
    if any(Path(str(path)).name == "latest_model_input.png" for path in referenced):
        return "latest_model_input.png is stale but was used by parse_orchestrator"
    return ""


def perception_output_issues(runtime_state_dir: Path, *, run_started_at: datetime) -> list[str]:
    issues: list[str] = []
    fixed_outputs = {
        "layout_index": runtime_state_dir / "latest_layout_index.json",
        "annotated_overview": runtime_state_dir / "latest_annotated_overview.png",
        "report": runtime_state_dir / "latest_perception_report.json",
    }
    stale = missing_outputs(fixed_outputs, min_mtime=run_started_at)
    if stale:
        issues.append("missing or stale fixed outputs: " + ", ".join(stale))

    crop_dir = runtime_state_dir / "crops"
    fresh_crops = [
        path
        for path in crop_dir.glob("R*.png")
        if path.is_file() and path.stat().st_mtime >= run_started_at.timestamp()
    ]
    if not fresh_crops:
        issues.append("missing fresh perception crop files in runtime_state/crops")
    return issues


def perception_outputs_are_fresh(runtime_state_dir: Path, *, run_started_at: datetime) -> bool:
    return not perception_output_issues(runtime_state_dir, run_started_at=run_started_at)


def page_state_manager_output_issues(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
) -> list[str]:
    expected_outputs = {
        "session": runtime_state_dir / "latest_survey_session.json",
        "report": runtime_state_dir / "latest_session_update_report.json",
    }
    stale = missing_outputs(expected_outputs, min_mtime=run_started_at)
    if stale:
        return ["missing or stale page_state_manager output: " + ", ".join(stale)]
    report = read_json(expected_outputs["report"])
    if report.get("ok") is not True:
        errors = report.get("errors") or ["latest_session_update_report.json ok is not true"]
        return [str(error) for error in errors]
    return []


def parse_quality_issues(orchestrated: dict[str, Any], *, allow_fake: bool) -> list[str]:
    issues: list[str] = []
    selected_mode = (
        orchestrated.get("parse_plan", {}).get("selected_mode")
        or orchestrated.get("parse_metrics", {}).get("mode_used")
    )
    if selected_mode == "fake" and not allow_fake:
        issues.append("fake parser output is schema-valid only and is not accepted")

    parsed_page = orchestrated.get("parsed_page") or {}
    if parsed_page_requires_human_review(parsed_page) or orchestrated.get("requires_human_review") is True:
        issues.append("needs_human_review: parse output requires human review")
    questions = parsed_page.get("questions") or []
    page = parsed_page.get("page") or {}
    page_type = str(page.get("page_type") or "").lower()
    visual_elements = parsed_page.get("visual_elements") or []
    navigation_buttons = parsed_page.get("navigation_buttons") or []
    if not questions:
        if classify_flow_status(parsed_page) in {"finished", "kicked_out"}:
            return issues
        if page_type == "image_task" and visual_elements:
            issues.append(
                "needs_human_review: image_task has visual elements but no answerable question"
            )
            if not navigation_buttons:
                issues.append("image_task has no actionable buttons")
            return issues
        issues.append("no question detected")
        return issues

    first_question = questions[0] or {}
    stem = first_question.get("question_stem") or {}
    if not str(stem.get("text") or "").strip():
        issues.append("question_stem.text is empty")

    answer_options = first_question.get("answer_options") or []
    input_fields = first_question.get("input_fields") or []
    developer_content = suspicious_developer_content(first_question, answer_options)
    if developer_content:
        issues.append(
            "blocked: captured content looks like a developer/local window, not the survey page: "
            + developer_content
        )
    if not answer_options and not input_fields:
        issues.append("answer_options and input_fields are both empty")
    if page_type == "image_task" and visual_elements and not answer_options and not navigation_buttons:
        issues.append("needs_human_review: image_task has no actionable answer options or buttons")

    confidence = parse_confidence(parsed_page, first_question)
    if confidence is None:
        issues.append("parse confidence is missing")
    elif confidence < 0.5:
        issues.append(f"parse confidence is too low: {confidence}")
    return issues


def parsed_page_requires_human_review(parsed_page: dict[str, Any]) -> bool:
    if parsed_page.get("requires_human_review") is True:
        return True
    page = parsed_page.get("page") if isinstance(parsed_page.get("page"), dict) else {}
    if page.get("requires_human_review") is True:
        return True
    questions = parsed_page.get("questions") or []
    return any(isinstance(question, dict) and question.get("requires_human_review") is True for question in questions)


def suspicious_developer_content(first_question: dict[str, Any], answer_options: list[Any]) -> str:
    texts = []
    stem = first_question.get("question_stem") if isinstance(first_question.get("question_stem"), dict) else {}
    texts.append(str(stem.get("text") or ""))
    for option in answer_options:
        if isinstance(option, dict):
            texts.append(str(option.get("text") or ""))
            texts.append(str(option.get("raw_text") or ""))
    combined = " ".join(texts).casefold()
    indicators = [
        "visual studio code",
        "browser_ctrl.py",
        "antigravity",
        "open agent manager",
        "import time",
        "powershell",
        "from utils.",
        "def ",
    ]
    hits = [indicator for indicator in indicators if indicator in combined]
    if not hits:
        return ""
    return ", ".join(hits[:4])


def parse_confidence(parsed_page: dict[str, Any], first_question: dict[str, Any]) -> float | None:
    candidates = [
        first_question.get("confidence"),
        (parsed_page.get("page") or {}).get("confidence"),
    ]
    for value in candidates:
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def parse_selected_mode(runtime_state_dir: Path) -> str:
    orchestrated = read_json(runtime_state_dir / "latest_orchestrated_parse.json")
    report = read_json(runtime_state_dir / "latest_parse_orchestrator_report.json")
    mode = (
        orchestrated.get("parse_plan", {}).get("selected_mode")
        or orchestrated.get("parse_metrics", {}).get("mode_used")
        or report.get("selected_mode")
    )
    return str(mode or "")


def collect_image_provenance(runtime_state_dir: Path) -> dict[str, Any]:
    orchestrated = read_json(runtime_state_dir / "latest_orchestrated_parse.json")
    parsed_page = orchestrated.get("parsed_page") or {}
    parse_plan = orchestrated.get("parse_plan") or {}
    provenance: dict[str, Any] = {}
    for prefix, path in {
        "screenshot": runtime_state_dir / "latest_capture.png",
        "runtime_context": runtime_state_dir / "latest_runtime_context.json",
        "layout_index": runtime_state_dir / "latest_layout_index.json",
        "annotated_overview": runtime_state_dir / "latest_annotated_overview.png",
        "model_input": runtime_state_dir / "latest_model_input.png",
        "parse_output": runtime_state_dir / "latest_orchestrated_parse.json",
    }.items():
        provenance[f"{prefix}_path"] = str(path)
        provenance[f"{prefix}_mtime"] = file_mtime_iso(path)
    provenance["selected_input_images"] = parse_plan.get("selected_input_images") or []
    provenance["input_image_used"] = (parsed_page.get("metadata") or {}).get("input_image_used", "")
    return provenance


def file_mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat()


def capture_metadata_from_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "capture_source": target.get("capture_source", ""),
        "target_locked": target.get("target_locked") is True,
        "target_window_title": target.get("target_window_title", ""),
        "target_window_handle": target.get("target_window_handle"),
        "locked_region": target.get("locked_region") or target.get("bbox") or {},
        "bbox": target.get("bbox") or target.get("locked_region") or {},
        "dpi_scale": target.get("dpi_scale"),
    }


def finish_blocked_precondition(
    state: PipelineState,
    step: PipelineStepDefinition,
    reason: str,
    *,
    run_started_at: datetime,
) -> None:
    state.finish_step(
        step.name,
        "blocked",
        summary=reason,
        output_paths=existing_outputs(step.expected_outputs, min_mtime=run_started_at),
        warnings=[],
        errors=[reason],
        metadata={"required": step.required},
    )


def finish_not_allowed(
    state: PipelineState,
    step: PipelineStepDefinition,
    reason: str,
    *,
    run_started_at: datetime,
) -> None:
    state.finish_step(
        step.name,
        "not_allowed",
        summary=reason,
        output_paths=existing_outputs(step.expected_outputs, min_mtime=run_started_at),
        warnings=[],
        errors=[reason],
        metadata={"required": step.required},
    )


def read_capture_provenance(runtime_state_dir: Path) -> dict[str, Any]:
    return read_json(runtime_state_dir / "latest_capture_provenance.json")


def capture_provenance_allows_context(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
    allow_fixture: bool,
) -> tuple[bool, str]:
    capture_path = runtime_state_dir / "latest_capture.png"
    provenance_path = runtime_state_dir / "latest_capture_provenance.json"
    if not capture_path.exists():
        return False, "latest_capture.png is missing or stale for this run"
    provenance = read_capture_provenance(runtime_state_dir)
    if provenance.get("capture_source") != "existing_capture" and missing_outputs(
        {"screenshot": capture_path},
        min_mtime=run_started_at,
    ):
        return False, "latest_capture.png is missing or stale for this run"
    if missing_outputs({"provenance": provenance_path}, min_mtime=run_started_at):
        return False, "latest_capture_provenance.json is missing or stale for this run"
    if provenance.get("screenshot_path") != str(capture_path):
        return False, "capture provenance does not reference runtime_state/latest_capture.png"
    if provenance.get("capture_source") == "existing_capture":
        return True, ""
    if provenance.get("target_locked") is True and provenance.get("capture_source") == "locked_target":
        return True, ""
    if allow_fixture and provenance.get("capture_source") == "fixture":
        return True, ""
    return False, NO_LOCKED_TARGET_MESSAGE


def runtime_context_uses_fresh_capture(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
) -> tuple[bool, str]:
    context_path = runtime_state_dir / "latest_runtime_context.json"
    capture_path = runtime_state_dir / "latest_capture.png"
    stale = missing_outputs({"runtime_context": context_path}, min_mtime=run_started_at)
    if stale:
        return False, "latest_runtime_context.json is missing or stale for this run"
    context = read_json(context_path)
    screenshot_path = str(context.get("screenshot_path") or context.get("capture_path") or "")
    if not screenshot_path:
        return False, "latest_runtime_context.json does not reference latest_capture.png"
    if Path(screenshot_path).resolve(strict=False) != capture_path.resolve(strict=False):
        return False, "latest_runtime_context.json does not reference the fresh latest_capture.png"
    if not capture_path.exists():
        return False, "latest_runtime_context.json references a missing screenshot_path"
    return True, ""


def annotated_overview_after_capture(runtime_state_dir: Path) -> tuple[bool, str]:
    capture_path = runtime_state_dir / "latest_capture.png"
    layout_path = runtime_state_dir / "latest_layout_index.json"
    annotated_path = runtime_state_dir / "latest_annotated_overview.png"
    if not capture_path.exists():
        return False, "latest_capture.png is missing"
    if not layout_path.exists():
        return False, "latest_layout_index.json is missing"
    if not annotated_path.exists():
        return False, "latest_annotated_overview.png is missing"
    if layout_path.stat().st_mtime < capture_path.stat().st_mtime:
        return False, "latest_layout_index.json is older than latest_capture.png"
    if annotated_path.stat().st_mtime < capture_path.stat().st_mtime:
        return False, "latest_annotated_overview.png is older than latest_capture.png"
    return True, ""


def compute_overall_status(
    step_records: list[dict[str, Any]],
    definitions: list[PipelineStepDefinition],
) -> str:
    required_by_name = {step.name: step.required for step in definitions}
    required_statuses = [
        record["status"] for record in step_records if required_by_name.get(record["name"], False)
    ]
    optional_statuses = [
        record["status"] for record in step_records if not required_by_name.get(record["name"], False)
    ]
    if "failed" in required_statuses:
        return "failed"
    if any(status in {"blocked", "not_allowed", "skipped"} for status in required_statuses):
        return "blocked"
    if "waiting_review" in required_statuses:
        return "waiting_review"
    if any(status != "success" for status in optional_statuses):
        return "partial_success"
    return "success"


def gate_allows_execution(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
) -> tuple[bool, str]:
    gate_path = runtime_state_dir / "latest_execution_gate.json"
    report_path = runtime_state_dir / "latest_execution_gate_report.json"
    stale = missing_outputs({"gate": gate_path, "report": report_path}, min_mtime=run_started_at)
    if stale:
        return False, "execution gate output is missing or stale: " + ", ".join(stale)
    gate = read_json(gate_path)
    report = read_json(report_path)
    if not gate and not report:
        return False, "execution gate output is missing"
    if gate.get("execution_allowed") is False or gate.get("status") in {"blocked", "not_allowed"}:
        reasons = gate.get("block_reasons") or report.get("issues") or ["execution gate blocked"]
        return False, "; ".join(str(reason) for reason in reasons)
    if report.get("validation_passed") is False:
        return False, "; ".join(str(issue) for issue in report.get("issues", ["gate validation failed"]))
    return True, "execution gate allowed"


def human_review_approved(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
) -> tuple[bool, str]:
    report_path = runtime_state_dir / "latest_human_review_report.json"
    decision_path = runtime_state_dir / "latest_reviewed_answer_decision.json"
    if missing_outputs({"report": report_path}, min_mtime=run_started_at):
        return False, "human review report is missing or stale"
    report = read_json(report_path)
    decision = (
        read_json(decision_path)
        if not missing_outputs({"decision": decision_path}, min_mtime=run_started_at)
        else {}
    )
    if report.get("requires_human_review") is True or decision.get("requires_human_review") is True:
        return False, "waiting for human review"
    unresolved = report.get("unresolved_question_ids") or decision.get("unresolved_question_ids") or []
    if unresolved:
        return False, "unresolved review items: " + ", ".join(str(item) for item in unresolved)
    if report.get("validation_passed") is False:
        return False, "; ".join(str(issue) for issue in report.get("issues", ["review validation failed"]))
    if decision.get("status") in {"rejected", "blocked"}:
        return False, f"human review status is {decision['status']}"
    if decision.get("approved") is False:
        return False, "human review rejected approval"
    approval_exists = (
        report.get("approved") is True
        or report.get("human_approved") is True
        or bool(report.get("approved_question_ids"))
        or decision.get("approved") is True
        or decision.get("status") in {"approved", "reviewed"}
    )
    if not approval_exists:
        return False, "human review approval is missing"
    return True, "human review approved"


def human_review_clear_for_preview(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
) -> tuple[bool, str]:
    report_path = runtime_state_dir / "latest_human_review_report.json"
    decision_path = runtime_state_dir / "latest_reviewed_answer_decision.json"
    if missing_outputs({"report": report_path}, min_mtime=run_started_at):
        return False, "human review report is missing or stale"
    report = read_json(report_path)
    decision = (
        read_json(decision_path)
        if not missing_outputs({"decision": decision_path}, min_mtime=run_started_at)
        else {}
    )
    if report.get("requires_human_review") is True or decision.get("requires_human_review") is True:
        return False, "waiting for human review"
    unresolved = report.get("unresolved_question_ids") or decision.get("unresolved_question_ids") or []
    if unresolved:
        return False, "unresolved review items: " + ", ".join(str(item) for item in unresolved)
    if report.get("validation_passed") is False:
        return False, "; ".join(str(issue) for issue in report.get("issues", ["review validation failed"]))
    if decision.get("status") in {"rejected", "blocked"}:
        return False, f"human review status is {decision['status']}"
    if decision.get("approved") is False:
        return False, "human review rejected approval"
    return True, "human review not required for preview"


def approved_action_plan_exists(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
) -> tuple[bool, str]:
    plan_path = runtime_state_dir / "latest_resolved_action_plan.json"
    if missing_outputs({"plan": plan_path}, min_mtime=run_started_at):
        return False, "approved action plan is missing or stale"
    plan = read_json(plan_path)
    if not plan:
        return False, "approved action plan is missing"
    actions = plan.get("resolved_actions") or plan.get("actions") or plan.get("executable_actions") or []
    if isinstance(actions, int):
        if actions <= 0:
            return False, "approved action plan has no actions"
    elif not actions:
        return False, "approved action plan has no actions"
    status = str(plan.get("status", "")).lower()
    if status in {"rejected", "blocked", "failed"}:
        return False, f"approved action plan status is {status}"
    return True, "approved action plan exists"


def approved_for_execution(
    runtime_state_dir: Path,
    *,
    run_started_at: datetime,
) -> tuple[bool, str]:
    gate_ok, gate_reason = gate_allows_execution(runtime_state_dir, run_started_at=run_started_at)
    if not gate_ok:
        return False, gate_reason
    review_ok, review_reason = human_review_approved(runtime_state_dir, run_started_at=run_started_at)
    if not review_ok:
        return False, review_reason
    plan_ok, plan_reason = approved_action_plan_exists(runtime_state_dir, run_started_at=run_started_at)
    if not plan_ok:
        return False, plan_reason
    return True, "approved for click-once execution"


def outputs_for_runtime(runtime_state_dir: Path) -> dict[str, dict[str, Path]]:
    outputs: dict[str, dict[str, Path]] = {}
    for step_name, paths in RUNTIME_OUTPUTS.items():
        outputs[step_name] = {
            label: runtime_state_dir / path.name if path.is_relative_to(RUNTIME_STATE_DIR) else path
            for label, path in paths.items()
        }
    return outputs


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one Autoworks pipeline pass.")
    parser.add_argument("--task", default="tts01", help="Task id to use for context-aware steps.")
    parser.add_argument(
        "--mode",
        choices=["dry-run", "preview", "click-once", "session"],
        default="preview",
        help="click-once executes one page; session loops pages until terminal state.",
    )
    parser.add_argument("--parser-mode", choices=["fake", "doubao", "ollama"], default="doubao")
    parser.add_argument("--output-level", choices=["light", "standard"], default="standard")
    parser.add_argument("--max-model-calls", type=int, default=3)
    parser.add_argument(
        "--allow-fake",
        action="store_true",
        help="Allow fake parser mode; parse quality gates still apply.",
    )
    parser.add_argument(
        "--allow-fixture",
        action="store_true",
        help="Allow tests/fixtures/latest_capture.png as a capture source for local testing.",
    )
    parser.add_argument(
        "--use-existing-capture",
        action="store_true",
        help="Use and validate runtime_state/latest_capture.png without overwriting it.",
    )
    parser.add_argument("--ocr", choices=["disabled", "tesseract", "rapidocr"], default="disabled")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--wait-after-navigation-seconds", type=float, default=1.0)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.mode == "session":
        report = run_session_until_terminal(
            task_id=args.task,
            parser_mode=args.parser_mode,
            output_level=args.output_level,
            max_model_calls=args.max_model_calls,
            ocr_backend=args.ocr,
            allow_fake=args.allow_fake,
            allow_fixture=args.allow_fixture,
            max_pages=args.max_pages,
            wait_after_navigation_seconds=args.wait_after_navigation_seconds,
        )
        print(f"session loop: {report['status']}")
        print(f"stop_reason: {report['stop_reason']}")
        print(f"run_count: {report['run_count']}")
        return
    state = run_once(
        task_id=args.task,
        mode=args.mode,
        parser_mode=args.parser_mode,
        output_level=args.output_level,
        max_model_calls=args.max_model_calls,
        ocr_backend=args.ocr,
        allow_fake=args.allow_fake,
        allow_fixture=args.allow_fixture,
        use_existing_capture=args.use_existing_capture,
    )
    print(f"pipeline run: {state['run_id']}")
    print(f"status: {state['overall_status']}")
    for step in state["steps"]:
        print(f"{step['name']}: {step['status']} - {step['summary']}")


if __name__ == "__main__":
    main()
