from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modules.autoworks_runner.pipeline_state import PipelineState
from modules.autoworks_runner.pipeline_steps import run_python_module
from modules.autoworks_runner.run_once import (
    NO_LOCKED_TARGET_MESSAGE,
    NO_VALID_CAPTURE_MESSAGE,
    PIPELINE_STEPS,
    parse_quality_issues,
    run_once,
    run_session_until_terminal,
)


@pytest.fixture(autouse=True)
def default_locked_target_for_runner_tests(monkeypatch) -> None:
    def fake_lock_check(runtime_state_dir: Path, **kwargs) -> dict:
        return {
            "status": "success",
            "summary": "lock ok",
            "output_paths": {"lock": str(runtime_state_dir / "latest_locked_target.json")},
            "warnings": [],
            "errors": [],
            "metadata": {"target_locked": True, "target_window_title": "KVM"},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_target_lock_check", fake_lock_check)


def test_pipeline_state_writes_snapshot_and_events(tmp_path: Path) -> None:
    state = PipelineState(steps=["capture", "review"], runtime_state_dir=tmp_path, mode="dry-run")

    state.initialize()
    state.start_step("capture")
    state.finish_step(
        "capture",
        "success",
        summary="captured",
        output_paths={"screenshot": "runtime_state/latest_capture.png"},
        warnings=["low contrast"],
    )
    state.complete()

    snapshot = json.loads((tmp_path / "latest_pipeline_run.json").read_text(encoding="utf-8"))
    assert snapshot["status"] == "success"
    assert snapshot["mode"] == "dry-run"
    assert snapshot["steps"][0]["name"] == "capture"
    assert snapshot["steps"][0]["status"] == "success"
    assert snapshot["steps"][0]["warnings"] == ["low contrast"]

    events = (tmp_path / "latest_pipeline_events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in events] == [
        "pipeline_started",
        "step_started",
        "step_finished",
        "pipeline_finished",
    ]


def test_session_loop_stops_when_terminal_flow_detected(tmp_path: Path, monkeypatch) -> None:
    calls = 0

    def fake_run_once(**kwargs):
        nonlocal calls
        calls += 1
        runtime = kwargs["runtime_state_dir"]
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "latest_survey_session.json").write_text(
            json.dumps({"flow_status": "finished"}),
            encoding="utf-8",
        )
        (runtime / "latest_action_plan.json").write_text(
            json.dumps({"status": "no_action"}),
            encoding="utf-8",
        )
        (runtime / "latest_action_executor_report.json").write_text(
            json.dumps({"executed_action_count": 0}),
            encoding="utf-8",
        )
        return {"run_id": "run_1", "overall_status": "success"}

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_once", fake_run_once)

    report = run_session_until_terminal(
        runtime_state_dir=tmp_path,
        max_pages=5,
        wait_after_navigation_seconds=0,
    )

    assert calls == 1
    assert report["status"] == "completed"
    assert report["stop_reason"] == "terminal_flow_status:finished"
    assert (tmp_path / "latest_session_loop_report.json").exists()


def test_session_loop_ignores_stale_artifacts_when_run_blocks(tmp_path: Path, monkeypatch) -> None:
    old_time = 1_700_000_000
    for name, payload in {
        "latest_survey_session.json": {"flow_status": "finished"},
        "latest_action_plan.json": {"status": "ready"},
        "latest_action_executor_report.json": {"executed_action_count": 4},
    }.items():
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        os.utime(path, (old_time, old_time))

    def fake_run_once(**kwargs):
        return {
            "run_id": "run_1",
            "started_at": "2026-05-17T12:00:00+00:00",
            "overall_status": "waiting_review",
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_once", fake_run_once)

    report = run_session_until_terminal(
        runtime_state_dir=tmp_path,
        max_pages=5,
        wait_after_navigation_seconds=0,
    )

    assert report["stop_reason"] == "pipeline_waiting_review"
    assert report["runs"] == [
        {
            "page_number": 1,
            "run_id": "run_1",
            "overall_status": "waiting_review",
            "flow_status": "",
            "action_plan_status": "",
            "executed_action_count": 0,
        }
    ]


def test_parse_quality_blocks_developer_window_content() -> None:
    issues = parse_quality_issues(
        {
            "parsed_page": {
                "page": {"page_type": "questionnaire", "confidence": 0.9},
                "questions": [
                    {
                        "question_type": "single_choice",
                        "question_stem": {"text": "Reviewing Interview Automation Progress"},
                        "answer_options": [
                            {"option_id": "T1", "text": "File"},
                            {"option_id": "T2", "text": "Edit"},
                            {"option_id": "T3", "text": "browser_ctrl.py"},
                        ],
                        "confidence": 0.9,
                    }
                ],
            }
        },
        allow_fake=False,
    )

    assert any("developer/local window" in issue for issue in issues)


def test_parse_quality_allows_terminal_page_without_questions() -> None:
    issues = parse_quality_issues(
        {
            "parsed_page": {
                "page": {
                    "page_type": "questionnaire",
                    "confidence": 0.9,
                    "summary": "Thank you, your response has been recorded.",
                },
                "questions": [],
                "navigation_buttons": [],
            }
        },
        allow_fake=False,
    )

    assert issues == []


def test_parse_quality_waits_when_parse_requires_review() -> None:
    issues = parse_quality_issues(
        {
            "parsed_page": {
                "requires_human_review": True,
                "page": {"page_type": "questionnaire", "confidence": 0.9},
                "questions": [
                    {
                        "question_type": "single_choice",
                        "question_stem": {"text": "Question?"},
                        "answer_options": [{"option_id": "T1", "text": "Yes"}],
                        "requires_human_review": True,
                        "confidence": 0.9,
                    }
                ],
            }
        },
        allow_fake=False,
    )

    assert "needs_human_review: parse output requires human review" in issues


def test_parse_quality_allows_actionable_page_with_top_level_review_flag() -> None:
    issues = parse_quality_issues(
        {
            "requires_human_review": True,
            "parsed_page": {
                "page": {"page_type": "questionnaire", "confidence": 1.0},
                "questions": [
                    {
                        "question_type": "text_input",
                        "question_stem": {"text": "What do you like about this idea?"},
                        "answer_options": [],
                        "input_fields": [
                            {
                                "field_id": "f1",
                                "field_type": "text",
                                "click_point_norm": {"x": 0.5, "y": 0.5},
                            }
                        ],
                        "confidence": 1.0,
                        "requires_human_review": False,
                    }
                ],
            },
        },
        allow_fake=False,
    )

    assert "needs_human_review: parse output requires human review" not in issues


def test_required_skipped_step_causes_overall_status_blocked(monkeypatch, tmp_path: Path) -> None:
    def fake_run_pipeline_step(step, **kwargs):
        if step.name == "window_capture":
            return fake_capture(tmp_path)
        if step.name == "existing_capture_check":
            return write_existing_capture_check_result(tmp_path)
        if step.name == "context_mapper":
            write_context(tmp_path)
        if step.name == "perception_indexer":
            write_perception(tmp_path)
        if step.name == "parse_orchestrator":
            write_parse(tmp_path, selected_mode="doubao", question_text="What now?", options=["Yes"])
        if step.name == "page_state_manager":
            return {
                "status": "skipped",
                "summary": "module is not implemented",
                "output_paths": {},
                "warnings": ["module is not implemented"],
                "errors": [],
                "metadata": {},
            }
        return {
            "status": "success",
            "summary": f"{step.name} ok",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_pipeline_step", fake_run_pipeline_step)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert result["overall_status"] == "blocked"
    assert statuses["page_state_manager"] == "blocked"


def test_fake_parse_causes_overall_status_blocked(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("modules.autoworks_runner.run_once.run_window_capture", fake_capture)

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        if "perception_indexer" in module_name:
            write_perception(tmp_path)
        if "parse_orchestrator" in module_name:
            write_parse(tmp_path, selected_mode="fake", question_text="What now?", options=["Yes"])
        for path in expected_outputs.values():
            if not path.exists():
                path.write_text("{}", encoding="utf-8")
        return {
            "status": "success",
            "summary": "parse ok",
            "output_paths": {label: str(path) for label, path in expected_outputs.items()},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert result["overall_status"] == "blocked"
    assert statuses["parse_orchestrator"] == "blocked"


def test_empty_question_parse_causes_overall_status_blocked(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("modules.autoworks_runner.run_once.run_window_capture", fake_capture)

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        if "perception_indexer" in module_name:
            write_perception(tmp_path)
        if "parse_orchestrator" in module_name:
            write_parse(tmp_path, selected_mode="doubao", question_text="", options=[])
        for path in expected_outputs.values():
            if not path.exists():
                path.write_text("{}", encoding="utf-8")
        return {
            "status": "success",
            "summary": "parse ok",
            "output_paths": {label: str(path) for label, path in expected_outputs.items()},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    result = run_once(mode="preview", runtime_state_dir=tmp_path, allow_fake=True)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert result["overall_status"] == "blocked"
    assert statuses["parse_quality_gate"] == "blocked"


def test_stale_output_files_are_ignored(monkeypatch, tmp_path: Path) -> None:
    output_path = tmp_path / "latest_result.json"
    output_path.write_text("{}", encoding="utf-8")
    old_time = time.time() - 3600
    os.utime(output_path, (old_time, old_time))

    monkeypatch.setattr("modules.autoworks_runner.pipeline_steps.module_is_available", lambda name: True)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("modules.autoworks_runner.pipeline_steps.subprocess.run", fake_run)

    result = run_python_module(
        "modules.fake.step",
        [],
        {"result": output_path},
        min_mtime=datetime.now(timezone.utc),
    )

    assert result["status"] == "failed"
    assert "missing or stale expected outputs" in result["summary"]


def test_run_once_preview_passes_doubao_args_to_parse_orchestrator(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("modules.autoworks_runner.run_once.run_window_capture", fake_capture)
    parse_args = []

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        if "context_mapper" in module_name:
            write_context(tmp_path)
        if "perception_indexer" in module_name:
            write_perception(tmp_path)
        if "parse_orchestrator" in module_name:
            parse_args.extend(args)
            write_parse(tmp_path, selected_mode="doubao", question_text="What now?", options=["Yes"])
        for path in expected_outputs.values():
            if not path.exists():
                path.write_text("{}", encoding="utf-8")
        return {
            "status": "success",
            "summary": f"{module_name} ok",
            "output_paths": {label: str(path) for label, path in expected_outputs.items()},
            "warnings": [],
            "errors": [],
            "metadata": {"args": args},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    run_once(mode="preview", runtime_state_dir=tmp_path)

    assert parse_args == ["--mode", "doubao", "--output-level", "standard", "--max-model-calls", "3"]


def test_stale_annotated_overview_blocks_parse_orchestrator(monkeypatch, tmp_path: Path) -> None:
    assert_stale_parse_input_blocks(monkeypatch, tmp_path, "latest_annotated_overview.png")


def test_stale_runtime_context_blocks_parse_orchestrator(monkeypatch, tmp_path: Path) -> None:
    assert_stale_parse_input_blocks(monkeypatch, tmp_path, "latest_runtime_context.json")


def test_stale_layout_index_blocks_parse_orchestrator(monkeypatch, tmp_path: Path) -> None:
    assert_stale_parse_input_blocks(monkeypatch, tmp_path, "latest_layout_index.json")


def test_latest_pipeline_run_records_model_image_provenance(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("modules.autoworks_runner.run_once.run_window_capture", fake_capture)

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        if "context_mapper" in module_name:
            write_context(tmp_path)
        if "perception_indexer" in module_name:
            write_perception(tmp_path)
        if "parse_orchestrator" in module_name:
            write_parse(
                tmp_path,
                selected_mode="doubao",
                question_text="What now?",
                options=["Yes"],
                selected_input_images=["runtime_state/latest_annotated_overview.png"],
                input_image_used="runtime_state/latest_annotated_overview.png",
            )
        for path in expected_outputs.values():
            if not path.exists():
                path.write_text("{}", encoding="utf-8")
        return {
            "status": "success",
            "summary": f"{module_name} ok",
            "output_paths": {label: str(path) for label, path in expected_outputs.items()},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    provenance = result["image_provenance"]
    assert provenance["selected_input_images"] == ["runtime_state/latest_annotated_overview.png"]
    assert provenance["input_image_used"] == "runtime_state/latest_annotated_overview.png"


def test_image_task_visual_elements_without_questions_waits_for_review(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("modules.autoworks_runner.run_once.run_window_capture", fake_capture)

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        if "context_mapper" in module_name:
            write_context(tmp_path)
        if "perception_indexer" in module_name:
            write_perception(tmp_path)
        if "parse_orchestrator" in module_name:
            write_image_task_parse(tmp_path)
        for path in expected_outputs.values():
            if not path.exists():
                path.write_text("{}", encoding="utf-8")
        return {
            "status": "success",
            "summary": f"{module_name} ok",
            "output_paths": {label: str(path) for label, path in expected_outputs.items()},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert result["overall_status"] == "waiting_review"
    assert statuses["parse_quality_gate"] == "waiting_review"
    assert statuses["answer_engine"] == "blocked"


def test_run_once_preview_blocks_when_no_target_is_locked(monkeypatch, tmp_path: Path) -> None:
    def fake_lock_check(runtime_state_dir: Path, **kwargs) -> dict:
        return {
            "status": "blocked",
            "summary": NO_LOCKED_TARGET_MESSAGE,
            "output_paths": {},
            "warnings": [],
            "errors": [NO_LOCKED_TARGET_MESSAGE],
            "metadata": {"target_locked": False},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_target_lock_check", fake_lock_check)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert result["overall_status"] == "blocked"
    assert statuses["target_lock_check"] == "blocked"
    assert statuses["window_capture"] == "blocked"
    assert statuses["existing_capture_check"] == "blocked"
    assert statuses["context_mapper"] == "blocked"
    assert NO_LOCKED_TARGET_MESSAGE in result["errors"]


def test_run_once_preview_captures_only_after_lock_validation(monkeypatch, tmp_path: Path) -> None:
    calls = []
    install_locked_capture_flow(monkeypatch, tmp_path, calls=calls)

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        if "context_mapper" in module_name:
            write_context(tmp_path)
        if "perception_indexer" in module_name:
            write_perception(tmp_path)
        if "parse_orchestrator" in module_name:
            return {
                "status": "blocked",
                "summary": "stop after capture proof",
                "output_paths": {},
                "warnings": [],
                "errors": [],
                "metadata": {},
            }
        return successful_module_result(module_name, expected_outputs)

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    result = run_once(mode="preview", runtime_state_dir=tmp_path, allow_fake=True)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert calls[:2] == ["lock_check", "capture"]
    assert statuses["window_capture"] == "success"
    assert statuses["parse_orchestrator"] == "blocked"


def test_stale_latest_capture_is_rejected(monkeypatch, tmp_path: Path) -> None:
    install_locked_capture_flow(monkeypatch, tmp_path, stale_capture=True)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert result["overall_status"] == "blocked"
    assert statuses["context_mapper"] == "blocked"
    assert "latest_capture.png is missing or stale" in statuses_summary(result)


def test_missing_latest_capture_blocks_context_mapper(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "modules.autoworks_runner.run_once.run_window_capture",
        lambda runtime_state_dir, **kwargs: {
            "status": "success",
            "summary": "capture step claimed success",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {"capture_source": "locked_target", "target_locked": True},
        },
    )

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert statuses["existing_capture_check"] == "blocked"
    assert statuses["context_mapper"] == "blocked"
    assert NO_VALID_CAPTURE_MESSAGE in result["errors"]


def test_missing_latest_capture_prevents_perception_and_parse(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "modules.autoworks_runner.run_once.run_window_capture",
        lambda runtime_state_dir, **kwargs: {
            "status": "success",
            "summary": "capture step claimed success",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {"capture_source": "locked_target", "target_locked": True},
        },
    )

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert statuses["perception_indexer"] == "blocked"
    assert statuses["parse_orchestrator"] == "blocked"


def test_runtime_context_referencing_missing_screenshot_blocks_downstream(
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_valid_capture(tmp_path / "latest_capture.png")

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        if "context_mapper" in module_name:
            (tmp_path / "latest_runtime_context.json").write_text(
                json.dumps({"screenshot_path": str(tmp_path / "missing_capture.png")}),
                encoding="utf-8",
            )
        return successful_module_result(module_name, expected_outputs)

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    result = run_once(mode="preview", runtime_state_dir=tmp_path, use_existing_capture=True)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert "window_capture" not in statuses
    assert statuses["perception_indexer"] == "blocked"
    assert statuses["parse_orchestrator"] == "blocked"


def test_valid_latest_capture_allows_context_mapper_to_run(monkeypatch, tmp_path: Path) -> None:
    write_valid_capture(tmp_path / "latest_capture.png")
    executed = []

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        executed.append(module_name)
        if "context_mapper" in module_name:
            write_context(tmp_path)
        if "perception_indexer" in module_name:
            return {
                "status": "blocked",
                "summary": "stop after context proof",
                "output_paths": {},
                "warnings": [],
                "errors": [],
                "metadata": {},
            }
        return successful_module_result(module_name, expected_outputs)

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    result = run_once(mode="preview", runtime_state_dir=tmp_path, use_existing_capture=True)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert "target_lock_check" not in statuses
    assert "window_capture" not in statuses
    assert statuses["existing_capture_check"] == "success"
    assert "modules.context_mapper.capture_context" in executed
    assert result["metadata"]["capture_source"] == "existing_capture"
    assert result["metadata"]["capture_path"] == str(tmp_path / "latest_capture.png")
    assert result["metadata"]["image_width"] == 3
    assert result["metadata"]["image_height"] == 4
    assert result["metadata"]["image_hash"]


def test_use_existing_capture_does_not_run_window_capture(monkeypatch, tmp_path: Path) -> None:
    write_valid_capture(tmp_path / "latest_capture.png")
    original_bytes = (tmp_path / "latest_capture.png").read_bytes()

    def fail_window_capture(*args, **kwargs):
        raise AssertionError("window_capture should not run in --use-existing-capture mode")

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_window_capture", fail_window_capture)
    monkeypatch.setattr(
        "modules.autoworks_runner.run_once.run_python_module",
        lambda module_name, args, expected_outputs, **kwargs: {
            "status": "blocked",
            "summary": "stop after context attempt",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {},
        },
    )

    result = run_once(mode="preview", runtime_state_dir=tmp_path, use_existing_capture=True)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert "window_capture" not in statuses
    assert statuses["existing_capture_check"] == "success"
    assert (tmp_path / "latest_capture.png").read_bytes() == original_bytes


def test_use_existing_capture_parse_inputs_are_checked_against_capture_mtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_valid_capture(tmp_path / "latest_capture.png")
    old_time = time.time() - 30
    os.utime(tmp_path / "latest_capture.png", (old_time, old_time))
    parse_ran = []

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        if "context_mapper" in module_name:
            write_context(tmp_path)
        if "perception_indexer" in module_name:
            write_perception(tmp_path)
        if "parse_orchestrator" in module_name:
            parse_ran.append(module_name)
            return {
                "status": "blocked",
                "summary": "stop after freshness proof",
                "output_paths": {},
                "warnings": [],
                "errors": [],
                "metadata": {},
            }
        return successful_module_result(module_name, expected_outputs)

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    result = run_once(mode="preview", runtime_state_dir=tmp_path, use_existing_capture=True)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert statuses["existing_capture_check"] == "success"
    assert statuses["context_mapper"] == "success"
    assert statuses["perception_indexer"] == "success"
    assert statuses["parse_orchestrator"] == "blocked"
    assert parse_ran == ["modules.parse_orchestrator.orchestrator"]


def test_fixture_capture_rejected_unless_allow_fixture(monkeypatch, tmp_path: Path) -> None:
    def fake_lock_check(runtime_state_dir: Path, **kwargs) -> dict:
        if kwargs.get("allow_fixture"):
            return {
                "status": "success",
                "summary": "fixture allowed",
                "output_paths": {},
                "warnings": [],
                "errors": [],
                "metadata": {"target_locked": False, "capture_source": "fixture"},
            }
        return {
            "status": "blocked",
            "summary": NO_LOCKED_TARGET_MESSAGE,
            "output_paths": {},
            "warnings": [],
            "errors": [NO_LOCKED_TARGET_MESSAGE],
            "metadata": {"target_locked": False},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_target_lock_check", fake_lock_check)

    rejected = run_once(mode="preview", runtime_state_dir=tmp_path)
    assert {step["name"]: step["status"] for step in rejected["steps"]}["target_lock_check"] == "blocked"

    monkeypatch.setattr(
        "modules.autoworks_runner.run_once.run_window_capture",
        lambda runtime_state_dir, **kwargs: write_capture_result(runtime_state_dir, capture_source="fixture"),
    )
    monkeypatch.setattr(
        "modules.autoworks_runner.run_once.run_python_module",
        lambda module_name, args, expected_outputs, **kwargs: successful_module_result(
            module_name,
            expected_outputs,
        ),
    )
    allowed = run_once(mode="preview", runtime_state_dir=tmp_path, allow_fixture=True)
    statuses = {step["name"]: step["status"] for step in allowed["steps"]}
    assert statuses["window_capture"] == "success"


def test_capture_provenance_is_written_to_pipeline_run(monkeypatch, tmp_path: Path) -> None:
    install_locked_capture_flow(monkeypatch, tmp_path)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    provenance = result["metadata"]["capture_provenance"]
    assert provenance["capture_source"] == "locked_target"
    assert provenance["target_locked"] is True
    assert provenance["target_window_title"] == "KVM"
    assert provenance["screenshot_path"] == str(tmp_path / "latest_capture.png")
    assert provenance["image_hash"]


def test_downstream_parsing_blocks_when_capture_provenance_missing_or_unlocked(
    monkeypatch,
    tmp_path: Path,
) -> None:
    install_locked_capture_flow(monkeypatch, tmp_path, unlocked_provenance=True)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert statuses["context_mapper"] == "blocked"
    assert statuses["perception_indexer"] == "blocked"
    assert statuses["parse_orchestrator"] == "blocked"


def test_run_once_does_not_auto_lock_a_target_window(monkeypatch, tmp_path: Path) -> None:
    auto_lock_calls = []

    def fake_lock_check(runtime_state_dir: Path, **kwargs) -> dict:
        return {
            "status": "blocked",
            "summary": NO_LOCKED_TARGET_MESSAGE,
            "output_paths": {},
            "warnings": [],
            "errors": [NO_LOCKED_TARGET_MESSAGE],
            "metadata": {"target_locked": False},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_target_lock_check", fake_lock_check)
    monkeypatch.setattr(
        "modules.window_capture.target_lock.lock_saved_target",
        lambda *args, **kwargs: auto_lock_calls.append("lock_saved_target"),
    )

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert "target_snap" not in statuses
    assert statuses["target_lock_check"] == "blocked"
    assert auto_lock_calls == []


def test_run_once_requires_fresh_page_state_manager_report_ok(monkeypatch, tmp_path: Path) -> None:
    assert_answer_engine_requires_page_state_report(monkeypatch, tmp_path, report_ok=True)
    assert_answer_engine_requires_page_state_report(monkeypatch, tmp_path, report_ok=False)


def test_perception_indexer_failure_blocks_parse_orchestrator(monkeypatch, tmp_path: Path) -> None:
    executed = []

    def fake_run_pipeline_step(step, **kwargs):
        executed.append(step.name)
        if step.name == "window_capture":
            return fake_capture(tmp_path)
        if step.name == "existing_capture_check":
            return write_existing_capture_check_result(tmp_path)
        if step.name == "context_mapper":
            write_context(tmp_path)
        if step.name == "perception_indexer":
            return {
                "status": "failed",
                "summary": "perception failed",
                "output_paths": {},
                "warnings": [],
                "errors": ["perception failed"],
                "metadata": {},
            }
        return {
            "status": "success",
            "summary": f"{step.name} ok",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_pipeline_step", fake_run_pipeline_step)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert result["overall_status"] == "failed"
    assert statuses["perception_indexer"] == "failed"
    assert statuses["parse_orchestrator"] == "blocked"
    assert "parse_orchestrator" not in executed


def test_perception_indexer_success_allows_parse_orchestrator_to_run(monkeypatch, tmp_path: Path) -> None:
    executed = []

    def fake_run_pipeline_step(step, **kwargs):
        executed.append(step.name)
        if step.name == "window_capture":
            return fake_capture(tmp_path)
        if step.name == "existing_capture_check":
            return write_existing_capture_check_result(tmp_path)
        if step.name == "context_mapper":
            write_context(tmp_path)
        if step.name == "perception_indexer":
            write_perception(tmp_path)
        if step.name == "parse_orchestrator":
            return {
                "status": "blocked",
                "summary": "stop after proving parse ran",
                "output_paths": {},
                "warnings": [],
                "errors": [],
                "metadata": {},
            }
        return {
            "status": "success",
            "summary": f"{step.name} ok",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_pipeline_step", fake_run_pipeline_step)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    assert "perception_indexer" in executed
    assert "parse_orchestrator" in executed
    assert result["overall_status"] == "blocked"


def test_stale_perception_outputs_are_ignored(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("modules.autoworks_runner.run_once.run_window_capture", fake_capture)
    write_perception(tmp_path)
    old_time = time.time() - 3600
    for path in [
        tmp_path / "latest_layout_index.json",
        tmp_path / "latest_annotated_overview.png",
        tmp_path / "latest_perception_report.json",
    ]:
        os.utime(path, (old_time, old_time))
    for path in (tmp_path / "crops").glob("R*.png"):
        os.utime(path, (old_time, old_time))

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        if "context_mapper" in module_name:
            write_context(tmp_path)
            return successful_module_result(module_name, expected_outputs)
        for path in expected_outputs.values():
            if not path.exists():
                path.write_text("{}", encoding="utf-8")
        return {
            "status": "success",
            "summary": f"{module_name} ok",
            "output_paths": {label: str(path) for label, path in expected_outputs.items()},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert result["overall_status"] == "failed"
    assert statuses["perception_indexer"] == "failed"


def test_successful_required_steps_produce_waiting_review(monkeypatch, tmp_path: Path) -> None:
    def fake_run_pipeline_step(step, **kwargs):
        if step.name == "window_capture":
            return fake_capture(tmp_path)
        if step.name == "existing_capture_check":
            return write_existing_capture_check_result(tmp_path)
        if step.name == "context_mapper":
            write_context(tmp_path)
        if step.name == "perception_indexer":
            write_perception(tmp_path)
        if step.name == "parse_orchestrator":
            write_parse(tmp_path, selected_mode="doubao", question_text="What now?", options=["Yes"])
        if step.name == "execution_gate":
            (tmp_path / "latest_execution_gate.json").write_text(
                json.dumps({"execution_allowed": True, "status": "allowed"}),
                encoding="utf-8",
            )
            (tmp_path / "latest_execution_gate_report.json").write_text(
                json.dumps({"validation_passed": True, "issues": []}),
                encoding="utf-8",
            )
            (tmp_path / "latest_execution_gate_report.json").write_text(
                json.dumps({"validation_passed": True, "issues": []}),
                encoding="utf-8",
            )
        if step.name == "human_review":
            (tmp_path / "latest_human_review_report.json").write_text(
                json.dumps(
                    {
                        "validation_passed": True,
                        "requires_human_review": True,
                        "unresolved_question_ids": ["q1"],
                    }
                ),
                encoding="utf-8",
            )
        return {
            "status": "success",
            "summary": f"{step.name} ok",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_pipeline_step", fake_run_pipeline_step)

    result = run_once(mode="click-once", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert result["overall_status"] == "waiting_review"
    assert statuses["human_review"] == "waiting_review"
    assert statuses["action_executor"] == "blocked"
    assert set(statuses) == set(PIPELINE_STEPS)


def test_preview_does_not_require_explicit_human_approval_when_review_clear(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_run_pipeline_step(step, **kwargs):
        if step.name == "window_capture":
            return fake_capture(tmp_path)
        if step.name == "existing_capture_check":
            return write_existing_capture_check_result(tmp_path)
        if step.name == "context_mapper":
            write_context(tmp_path)
        if step.name == "perception_indexer":
            write_perception(tmp_path)
        if step.name == "parse_orchestrator":
            write_parse(tmp_path, selected_mode="doubao", question_text="What now?", options=["Yes"])
        if step.name == "execution_gate":
            (tmp_path / "latest_execution_gate.json").write_text(
                json.dumps({"execution_allowed": True, "status": "allowed"}),
                encoding="utf-8",
            )
            (tmp_path / "latest_execution_gate_report.json").write_text(
                json.dumps({"validation_passed": True, "issues": []}),
                encoding="utf-8",
            )
        if step.name == "human_review":
            (tmp_path / "latest_human_review_report.json").write_text(
                json.dumps(
                    {
                        "validation_passed": True,
                        "requires_human_review": False,
                        "unresolved_question_ids": [],
                    }
                ),
                encoding="utf-8",
            )
            (tmp_path / "latest_reviewed_answer_decision.json").write_text(
                json.dumps({"requires_human_review": False}),
                encoding="utf-8",
            )
        return {
            "status": "success",
            "summary": f"{step.name} ok",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_pipeline_step", fake_run_pipeline_step)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert statuses["human_review"] == "success"
    assert statuses["click_preview"] == "success"


def test_click_once_does_not_execute_without_approval(monkeypatch, tmp_path: Path) -> None:
    executed = []
    stale_review = tmp_path / "latest_human_review_report.json"
    stale_review.write_text(
        json.dumps({"validation_passed": True, "requires_human_review": False, "approved": True}),
        encoding="utf-8",
    )
    old_time = time.time() - 3600
    os.utime(stale_review, (old_time, old_time))

    def fake_run_pipeline_step(step, **kwargs):
        executed.append(step.name)
        if step.name == "window_capture":
            return fake_capture(tmp_path)
        if step.name == "existing_capture_check":
            return write_existing_capture_check_result(tmp_path)
        if step.name == "context_mapper":
            write_context(tmp_path)
        if step.name == "perception_indexer":
            write_perception(tmp_path)
        if step.name == "parse_orchestrator":
            write_parse(tmp_path, selected_mode="doubao", question_text="What now?", options=["Yes"])
        if step.name == "execution_gate":
            (tmp_path / "latest_execution_gate.json").write_text(
                json.dumps({"execution_allowed": True, "status": "allowed"}),
                encoding="utf-8",
            )
            (tmp_path / "latest_execution_gate_report.json").write_text(
                json.dumps({"validation_passed": True, "issues": []}),
                encoding="utf-8",
            )
        return {
            "status": "success",
            "summary": f"{step.name} ok",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_pipeline_step", fake_run_pipeline_step)

    result = run_once(mode="click-once", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert "action_executor" not in executed
    assert statuses["human_review"] == "waiting_review"
    assert statuses["action_executor"] == "blocked"
    assert result["overall_status"] == "waiting_review"


def test_click_once_executes_when_human_review_not_required(monkeypatch, tmp_path: Path) -> None:
    executed = []

    def fake_run_pipeline_step(step, **kwargs):
        executed.append(step.name)
        if step.name == "window_capture":
            return fake_capture(tmp_path)
        if step.name == "existing_capture_check":
            return write_existing_capture_check_result(tmp_path)
        if step.name == "context_mapper":
            write_context(tmp_path)
        if step.name == "perception_indexer":
            write_perception(tmp_path)
        if step.name == "parse_orchestrator":
            write_parse(tmp_path, selected_mode="doubao", question_text="What now?", options=["Yes"])
        if step.name == "execution_gate":
            (tmp_path / "latest_execution_gate.json").write_text(
                json.dumps({"execution_allowed": True, "status": "allowed"}),
                encoding="utf-8",
            )
            (tmp_path / "latest_execution_gate_report.json").write_text(
                json.dumps({"validation_passed": True, "issues": []}),
                encoding="utf-8",
            )
        if step.name == "human_review":
            (tmp_path / "latest_human_review_report.json").write_text(
                json.dumps(
                    {
                        "validation_passed": True,
                        "requires_human_review": False,
                        "unresolved_question_ids": [],
                    }
                ),
                encoding="utf-8",
            )
            (tmp_path / "latest_reviewed_answer_decision.json").write_text(
                json.dumps({"requires_human_review": False}),
                encoding="utf-8",
            )
        if step.name == "target_resolver":
            (tmp_path / "latest_resolved_action_plan.json").write_text(
                json.dumps({"status": "ready", "actions": [{"action_id": "a1"}]}),
                encoding="utf-8",
            )
            (tmp_path / "latest_target_resolver_report.json").write_text(
                json.dumps({"validation_passed": True, "issues": []}),
                encoding="utf-8",
            )
        if step.name == "action_executor":
            (tmp_path / "latest_action_executor_report.json").write_text(
                json.dumps({"executed_action_count": 1}),
                encoding="utf-8",
            )
        return {
            "status": "success",
            "summary": f"{step.name} ok",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_pipeline_step", fake_run_pipeline_step)

    result = run_once(mode="click-once", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert "action_executor" in executed
    assert statuses["human_review"] == "success"
    assert statuses["action_executor"] == "success"


def write_parse(
    runtime_state_dir: Path,
    *,
    selected_mode: str,
    question_text: str,
    options: list[str],
    confidence: float = 0.9,
    selected_input_images: list[str] | None = None,
    input_image_used: str = "",
) -> None:
    runtime_state_dir.mkdir(parents=True, exist_ok=True)
    answer_options = [
        {"option_id": f"a{index}", "text": option}
        for index, option in enumerate(options, start=1)
    ]
    parse = {
        "parsed_page": {
            "page": {"page_type": "survey", "confidence": confidence},
            "questions": [
                {
                    "question_id": "q1",
                    "question_stem": {"text": question_text},
                    "answer_options": answer_options,
                    "input_fields": [],
                    "confidence": confidence,
                }
            ],
            "metadata": {"input_image_used": input_image_used},
        },
        "parse_plan": {
            "selected_mode": selected_mode,
            "selected_input_images": selected_input_images or [],
        },
        "parse_metrics": {"mode_used": selected_mode},
    }
    (runtime_state_dir / "latest_orchestrated_parse.json").write_text(
        json.dumps(parse),
        encoding="utf-8",
    )
    (runtime_state_dir / "latest_parse_orchestrator_report.json").write_text(
        json.dumps({"selected_mode": selected_mode}),
        encoding="utf-8",
    )


def write_image_task_parse(runtime_state_dir: Path) -> None:
    parse = {
        "parsed_page": {
            "page": {"page_type": "image_task", "confidence": 0.9},
            "questions": [],
            "visual_elements": [{"element_id": "E1", "label": "image"}],
            "navigation_buttons": [],
            "metadata": {"input_image_used": "runtime_state/latest_annotated_overview.png"},
        },
        "parse_plan": {
            "selected_mode": "doubao",
            "selected_input_images": ["runtime_state/latest_annotated_overview.png"],
        },
        "parse_metrics": {"mode_used": "doubao"},
    }
    (runtime_state_dir / "latest_orchestrated_parse.json").write_text(
        json.dumps(parse),
        encoding="utf-8",
    )
    (runtime_state_dir / "latest_parse_orchestrator_report.json").write_text(
        json.dumps({"selected_mode": "doubao"}),
        encoding="utf-8",
    )


def write_context(runtime_state_dir: Path) -> None:
    runtime_state_dir.mkdir(parents=True, exist_ok=True)
    (runtime_state_dir / "latest_runtime_context.json").write_text(
        json.dumps({"screenshot_path": str(runtime_state_dir / "latest_capture.png")}),
        encoding="utf-8",
    )


def write_perception(runtime_state_dir: Path) -> None:
    crops_dir = runtime_state_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    crop_path = crops_dir / "R1_web_viewport.png"
    annotated_crop_path = crops_dir / "R1_web_viewport_annotated.png"
    crop_path.write_bytes(b"crop")
    annotated_crop_path.write_bytes(b"annotated-crop")
    layout_index = {
        "index_id": "index_test",
        "annotated_overview": str(runtime_state_dir / "latest_annotated_overview.png"),
        "regions": [
            {
                "region_id": "R1",
                "crop_path": str(crop_path),
                "annotated_crop_path": str(annotated_crop_path),
            }
        ],
    }
    (runtime_state_dir / "latest_layout_index.json").write_text(
        json.dumps(layout_index),
        encoding="utf-8",
    )
    (runtime_state_dir / "latest_annotated_overview.png").write_bytes(b"overview")
    (runtime_state_dir / "latest_perception_report.json").write_text(
        json.dumps(
            {
                "layout_index": str(runtime_state_dir / "latest_layout_index.json"),
                "annotated_overview": str(runtime_state_dir / "latest_annotated_overview.png"),
            }
        ),
        encoding="utf-8",
    )


def fake_capture(runtime_state_dir: Path, **kwargs) -> dict:
    return write_capture_result(runtime_state_dir)


def install_locked_capture_flow(
    monkeypatch,
    tmp_path: Path,
    *,
    calls: list[str] | None = None,
    stale_capture: bool = False,
    unlocked_provenance: bool = False,
) -> None:
    calls = calls if calls is not None else []

    def fake_lock_check(runtime_state_dir: Path, **kwargs) -> dict:
        calls.append("lock_check")
        (runtime_state_dir / "latest_locked_target.json").write_text(
            json.dumps(
                {
                    "target_locked": True,
                    "target_window_title": "KVM",
                    "target_window_handle": 123,
                    "locked_region": {"left": 1, "top": 2, "width": 3, "height": 4},
                    "dpi_scale": 1.25,
                }
            ),
            encoding="utf-8",
        )
        return {
            "status": "success",
            "summary": "lock ok",
            "output_paths": {"lock": str(runtime_state_dir / "latest_locked_target.json")},
            "warnings": [],
            "errors": [],
            "metadata": {"target_locked": True, "target_window_title": "KVM"},
        }

    def fake_window_capture(runtime_state_dir: Path, **kwargs) -> dict:
        calls.append("capture")
        return write_capture_result(
            runtime_state_dir,
            stale_capture=stale_capture,
            target_locked=not unlocked_provenance,
        )

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        if "context_mapper" in module_name:
            write_context(tmp_path)
        if "perception_indexer" in module_name:
            write_perception(tmp_path)
        if "parse_orchestrator" in module_name:
            write_parse(tmp_path, selected_mode="doubao", question_text="What now?", options=["Yes"])
        for path in expected_outputs.values():
            if not path.exists():
                path.write_text("{}", encoding="utf-8")
        return successful_module_result(module_name, expected_outputs)

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_target_lock_check", fake_lock_check)
    monkeypatch.setattr("modules.autoworks_runner.run_once.run_window_capture", fake_window_capture)
    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)


def write_capture_result(
    runtime_state_dir: Path,
    *,
    capture_source: str = "locked_target",
    target_locked: bool = True,
    stale_capture: bool = False,
) -> dict:
    capture_path = runtime_state_dir / "latest_capture.png"
    provenance_path = runtime_state_dir / "latest_capture_provenance.json"
    write_valid_capture(capture_path)
    provenance = {
        "capture_source": capture_source,
        "target_locked": target_locked,
        "target_window_title": "KVM" if target_locked else "",
        "target_window_handle": 123 if target_locked else None,
        "locked_region": {"left": 1, "top": 2, "width": 3, "height": 4} if target_locked else {},
        "dpi_scale": 1.25 if target_locked else None,
        "screenshot_path": str(capture_path),
        "screenshot_mtime": datetime.fromtimestamp(capture_path.stat().st_mtime).isoformat(),
        "image_width": 3,
        "image_height": 4,
        "image_hash": "hash123",
    }
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    if stale_capture:
        old_time = time.time() - 3600
        os.utime(capture_path, (old_time, old_time))
        os.utime(provenance_path, (old_time, old_time))
    return {
        "status": "success",
        "summary": "capture ok",
        "output_paths": {"screenshot": str(capture_path), "provenance": str(provenance_path)},
        "warnings": [],
        "errors": [],
        "metadata": provenance,
    }


def successful_module_result(module_name: str, expected_outputs: dict[str, Path]) -> dict:
    return {
        "status": "success",
        "summary": f"{module_name} ok",
        "output_paths": {label: str(path) for label, path in expected_outputs.items()},
        "warnings": [],
        "errors": [],
        "metadata": {},
    }


def write_valid_capture(path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (3, 4), color=(10, 20, 30)).save(path)


def write_existing_capture_check_result(runtime_state_dir: Path) -> dict:
    from modules.autoworks_runner.run_once import validate_existing_capture

    provenance = validate_existing_capture(runtime_state_dir / "latest_capture.png")
    (runtime_state_dir / "latest_capture_provenance.json").write_text(
        json.dumps(provenance),
        encoding="utf-8",
    )
    return {
        "status": "success",
        "summary": "validated runtime_state/latest_capture.png",
        "output_paths": {
            "screenshot": str(runtime_state_dir / "latest_capture.png"),
            "provenance": str(runtime_state_dir / "latest_capture_provenance.json"),
        },
        "warnings": [],
        "errors": [],
        "metadata": provenance,
    }


def statuses_summary(result: dict) -> str:
    return " ".join(str(step.get("summary", "")) for step in result["steps"])


def assert_answer_engine_requires_page_state_report(
    monkeypatch,
    tmp_path: Path,
    *,
    report_ok: bool,
) -> None:
    monkeypatch.setattr("modules.autoworks_runner.run_once.run_window_capture", fake_capture)
    executed = []

    def fake_run_python_module(module_name, args, expected_outputs, **kwargs):
        executed.append(module_name)
        if "context_mapper" in module_name:
            write_context(tmp_path)
        if "perception_indexer" in module_name:
            write_perception(tmp_path)
        if "parse_orchestrator" in module_name:
            write_parse(tmp_path, selected_mode="doubao", question_text="What now?", options=["Yes"])
        if "page_state_manager" in module_name:
            (tmp_path / "latest_survey_session.json").write_text(
                json.dumps({"session_id": "session_1", "pages": [{}]}),
                encoding="utf-8",
            )
            (tmp_path / "latest_session_update_report.json").write_text(
                json.dumps({"ok": report_ok, "errors": [] if report_ok else ["bad report"]}),
                encoding="utf-8",
            )
        for path in expected_outputs.values():
            if not path.exists():
                path.write_text("{}", encoding="utf-8")
        return {
            "status": "success",
            "summary": f"{module_name} ok",
            "output_paths": {label: str(path) for label, path in expected_outputs.items()},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_python_module", fake_run_python_module)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)
    statuses = {step["name"]: step["status"] for step in result["steps"]}

    if report_ok:
        assert "modules.answer_engine.answer_engine" in executed
    else:
        assert statuses["page_state_manager"] == "failed"
        assert statuses["answer_engine"] == "blocked"
        assert "modules.answer_engine.answer_engine" not in executed


def assert_stale_parse_input_blocks(monkeypatch, tmp_path: Path, stale_name: str) -> None:
    executed = []

    def fake_run_pipeline_step(step, **kwargs):
        executed.append(step.name)
        if step.name == "window_capture":
            return fake_capture(tmp_path)
        if step.name == "existing_capture_check":
            return write_existing_capture_check_result(tmp_path)
        if step.name == "context_mapper":
            write_context(tmp_path)
        if step.name == "perception_indexer":
            write_perception(tmp_path)
            stale_path = tmp_path / stale_name
            old_time = time.time() - 3600
            os.utime(stale_path, (old_time, old_time))
        return {
            "status": "success",
            "summary": f"{step.name} ok",
            "output_paths": {},
            "warnings": [],
            "errors": [],
            "metadata": {},
        }

    monkeypatch.setattr("modules.autoworks_runner.run_once.run_pipeline_step", fake_run_pipeline_step)

    result = run_once(mode="preview", runtime_state_dir=tmp_path)

    statuses = {step["name"]: step["status"] for step in result["steps"]}
    assert result["overall_status"] == "blocked"
    assert statuses["parse_orchestrator"] == "blocked"
    assert "parse_orchestrator" not in executed
