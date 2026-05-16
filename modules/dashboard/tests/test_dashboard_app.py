from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock

from modules.dashboard.app import (
    DashboardHandler,
    build_runtime_summary,
    current_answer_approval_input,
    render_dashboard,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def touch_in_order(paths: list[Path]) -> None:
    base = 1_800_000_000
    for index, path in enumerate(paths):
        os.utime(path, (base + index, base + index))


def write_ready_chain(runtime: Path) -> None:
    (runtime / "latest_capture.png").write_bytes(b"png")
    write_json(runtime / "latest_runtime_context.json", {"task_id": "tts01"})
    write_json(runtime / "latest_layout_index.json", {"layout_hints": {}})
    write_json(
        runtime / "latest_parse_metrics.json",
        {
            "mode_used": "ollama",
            "strategy_used": "direct_region_parse",
            "model_calls_count": 1,
            "validation_passed": True,
            "fallback_used": False,
            "elapsed_time_ms": 12000,
        },
    )
    write_json(
        runtime / "latest_orchestrated_parse.json",
        {"requires_human_review": False},
    )
    write_json(
        runtime / "latest_parse_orchestrator_report.json",
        {"validation_passed": True, "requires_human_review": False},
    )
    write_json(
        runtime / "latest_answer_engine_report.json",
        {"validation_passed": True},
    )
    write_json(
        runtime / "latest_answer_decision.json",
        {
            "decision_id": "decision_1",
            "requires_human_review": False,
            "question_decisions": [
                {
                    "answer_strategy": "profile_llm_strategy",
                    "answer_mode": "representative_persona",
                    "recommended_option_ids": ["T29"],
                    "click_targets": [
                        {
                            "option_id": "T29",
                            "text": "This would be slightly better than what already exists",
                        }
                    ],
                }
            ],
        },
    )
    write_json(runtime / "latest_action_plan_report.json", {"validation_passed": True})
    write_json(
        runtime / "latest_action_plan.json",
        {
            "action_plan_id": "action_plan_1",
            "source_decision_id": "decision_1",
            "status": "ready",
            "actions": [
                {
                    "skill": "click_option",
                    "target": {
                        "option_id": "T29",
                        "option_text": "This would be slightly better than what already exists",
                    },
                }
            ],
        },
    )
    write_json(runtime / "latest_target_resolver_report.json", {"validation_passed": True})
    write_json(
        runtime / "latest_resolved_action_plan.json",
        {
            "resolved_action_plan_id": "resolved_action_plan_1",
            "source_action_plan_id": "action_plan_1",
            "actions": [
                {
                    "skill": "click_option",
                    "target": {
                        "option_id": "T29",
                        "option_text": "This would be slightly better than what already exists",
                        "resolver_source": "parsed_control_click_point",
                        "resolver_confidence": 0.9,
                        "click_point_screen": {"x": 747, "y": 802},
                    },
                }
            ]
        },
    )
    write_json(runtime / "latest_execution_gate_report.json", {"validation_passed": True})
    write_json(
        runtime / "latest_execution_gate.json",
        {
            "status": "allowed",
            "execution_allowed": True,
            "source_resolved_action_plan_id": "resolved_action_plan_1",
            "block_reasons": [],
            "executable_actions": [
                {
                    "skill": "click_option",
                    "target": {
                        "option_id": "T29",
                        "option_text": "This would be slightly better than what already exists",
                        "resolver_source": "parsed_control_click_point",
                        "resolver_confidence": 0.9,
                        "click_point_screen": {"x": 747, "y": 802},
                    },
                }
            ],
        },
    )
    touch_in_order(
        [
            runtime / "latest_capture.png",
            runtime / "latest_runtime_context.json",
            runtime / "latest_layout_index.json",
            runtime / "latest_parse_metrics.json",
            runtime / "latest_orchestrated_parse.json",
            runtime / "latest_parse_orchestrator_report.json",
            runtime / "latest_answer_engine_report.json",
            runtime / "latest_answer_decision.json",
            runtime / "latest_action_plan_report.json",
            runtime / "latest_action_plan.json",
            runtime / "latest_target_resolver_report.json",
            runtime / "latest_resolved_action_plan.json",
            runtime / "latest_execution_gate_report.json",
            runtime / "latest_execution_gate.json",
        ]
    )


def test_runtime_summary_enables_dry_run_when_gate_allowed(tmp_path: Path) -> None:
    write_ready_chain(tmp_path)

    summary = build_runtime_summary(tmp_path)

    assert summary["answer"]["recommended_option_ids"] == ["T29"]
    assert summary["answer"]["selected_option_text"] == (
        "This would be slightly better than what already exists"
    )
    assert summary["target_resolver"]["click_point_screen"] == {"x": 747, "y": 802}
    assert summary["can_run"]["executor_dry_run"] is True
    assert summary["can_run"]["real_click"] is True


def test_human_review_blocks_downstream_controls(tmp_path: Path) -> None:
    write_ready_chain(tmp_path)
    write_json(
        tmp_path / "latest_answer_decision.json",
        {
            "decision_id": "decision_review_required",
            "session_id": "session_1",
            "task_id": "tts01",
            "requires_human_review": True,
            "question_decisions": [
                {
                    "question_id": "q1",
                    "answer_strategy": "profile_llm_strategy",
                    "answer_mode": "strict_private",
                    "recommended_option_ids": ["T29"],
                }
            ],
        },
    )

    summary = build_runtime_summary(tmp_path)
    html = render_dashboard(tmp_path)

    assert summary["answer"]["status"] == "blocked"
    assert summary["can_run"]["action_plan"] is False
    assert "answer requires human review" in summary["answer"]["blocked_reason"]
    assert 'action="/run-action-plan"><button disabled>' in html
    assert 'action="/approve-current-answer"><button>Approve Current Answer</button>' in html


def test_current_answer_approval_input_uses_latest_decision() -> None:
    approval = current_answer_approval_input(
        {
            "decision_id": "decision_latest",
            "session_id": "session_latest",
            "task_id": "tts01",
            "question_decisions": [
                {
                    "question_id": "q1",
                    "recommended_option_ids": ["T29"],
                    "recommended_text_answer": "",
                }
            ],
        }
    )

    assert approval["source_decision_id"] == "decision_latest"
    assert approval["session_id"] == "session_latest"
    assert approval["approvals"] == [
        {
            "question_id": "q1",
            "approved_option_ids": ["T29"],
            "approved_text_answer": "",
            "review_note": "Human approved current dashboard recommendation.",
        }
    ]


def test_reviewed_answer_unblocks_real_click_controls(tmp_path: Path) -> None:
    write_ready_chain(tmp_path)
    raw_decision = json.loads(
        (tmp_path / "latest_answer_decision.json").read_text(encoding="utf-8")
    )
    raw_decision["requires_human_review"] = True
    raw_decision["question_decisions"][0]["requires_human_review"] = True
    write_json(tmp_path / "latest_answer_decision.json", raw_decision)
    reviewed_decision = dict(raw_decision)
    reviewed_decision["source_decision_id"] = raw_decision["decision_id"]
    reviewed_decision["requires_human_review"] = False
    reviewed_decision["question_decisions"][0] = dict(raw_decision["question_decisions"][0])
    reviewed_decision["question_decisions"][0]["requires_human_review"] = False
    reviewed_decision["question_decisions"][0]["confidence"] = 1.0
    reviewed_decision["question_decisions"][0]["approval_source"] = "manual_review"
    write_json(tmp_path / "latest_reviewed_answer_decision.json", reviewed_decision)
    write_json(
        tmp_path / "latest_human_review_report.json",
        {
            "validation_passed": True,
            "source_decision_id": raw_decision["decision_id"],
            "requires_human_review": False,
            "issues": [],
        },
    )
    write_json(
        tmp_path / "latest_answer_engine_report.json",
        {
            "validation_passed": False,
            "requires_human_review": True,
            "issues": [],
            "warnings": [],
        },
    )
    write_json(
        tmp_path / "latest_locked_target.json",
        {
            "target_locked": True,
            "target_window_title": "Tina",
            "target_window_handle": 123,
        },
    )
    touch_in_order(
        [
            tmp_path / "latest_orchestrated_parse.json",
            tmp_path / "latest_answer_decision.json",
            tmp_path / "latest_answer_engine_report.json",
            tmp_path / "latest_reviewed_answer_decision.json",
            tmp_path / "latest_human_review_report.json",
            tmp_path / "latest_action_plan.json",
            tmp_path / "latest_action_plan_report.json",
            tmp_path / "latest_resolved_action_plan.json",
            tmp_path / "latest_target_resolver_report.json",
            tmp_path / "latest_execution_gate.json",
            tmp_path / "latest_execution_gate_report.json",
        ]
    )

    summary = build_runtime_summary(tmp_path)
    html = render_dashboard(tmp_path)

    assert summary["answer"]["status"] == "ready"
    assert summary["answer"]["review_applied"] is True
    assert summary["can_run"]["real_click"] is True
    assert 'action="/run-real-click-once"><button class="danger">' in html


def test_new_blocked_parse_disables_stale_gate_and_executor(tmp_path: Path) -> None:
    write_ready_chain(tmp_path)
    write_json(
        tmp_path / "latest_parse_metrics.json",
        {
            "mode_used": "ollama",
            "validation_passed": False,
            "fallback_reason": "no grounded options",
        },
    )
    write_json(
        tmp_path / "latest_orchestrated_parse.json",
        {"parsed_page": {}, "requires_human_review": True},
    )
    write_json(
        tmp_path / "latest_parse_orchestrator_report.json",
        {"validation_passed": False, "requires_human_review": True},
    )
    touch_in_order(
        [
            tmp_path / "latest_answer_decision.json",
            tmp_path / "latest_action_plan.json",
            tmp_path / "latest_resolved_action_plan.json",
            tmp_path / "latest_execution_gate.json",
            tmp_path / "latest_parse_metrics.json",
            tmp_path / "latest_orchestrated_parse.json",
            tmp_path / "latest_parse_orchestrator_report.json",
        ]
    )

    summary = build_runtime_summary(tmp_path)
    html = render_dashboard(tmp_path)

    assert summary["parse"]["status"] == "blocked"
    assert summary["answer"]["status"] == "blocked"
    assert summary["execution_gate"]["status"] == "blocked"
    assert summary["can_run"]["executor_dry_run"] is False
    assert summary["can_run"]["real_click"] is False
    assert 'action="/run-executor-dry-run"><button disabled>' in html
    assert 'action="/run-real-click-once"><button class="danger" disabled>' in html


def test_stale_resolved_plan_disables_old_allowed_gate(tmp_path: Path) -> None:
    write_ready_chain(tmp_path)
    write_json(
        tmp_path / "latest_resolved_action_plan.json",
        {
            "resolved_action_plan_id": "resolved_action_plan_2",
            "source_action_plan_id": "action_plan_1",
            "actions": [
                {
                    "skill": "click_option",
                    "target": {
                        "option_id": "T30",
                        "resolver_source": "parsed_control_click_point",
                        "click_point_screen": {"x": 100, "y": 200},
                    },
                }
            ],
        },
    )
    os.utime(tmp_path / "latest_execution_gate.json", (1_800_000_000, 1_800_000_000))
    os.utime(
        tmp_path / "latest_execution_gate_report.json",
        (1_800_000_000, 1_800_000_000),
    )
    os.utime(
        tmp_path / "latest_resolved_action_plan.json",
        (1_800_000_100, 1_800_000_100),
    )

    summary = build_runtime_summary(tmp_path)

    assert summary["target_resolver"]["status"] == "ready"
    assert summary["execution_gate"]["status"] == "blocked"
    assert summary["can_run"]["executor_dry_run"] is False
    assert "execution gate is older than latest resolved action plan" in (
        summary["execution_gate"]["blocked_reason"]
    )


def test_render_dashboard_shows_click_point_and_real_click_is_separate(tmp_path: Path) -> None:
    write_ready_chain(tmp_path)

    html = render_dashboard(tmp_path)

    assert "Refresh Targets" in html
    assert "Snap Target" not in html
    assert "Run Dry-Run Executor" in html
    assert "Real Click 1 Action" in html
    assert "/run-real-click-once" in html
    assert "parsed_control_click_point" in html
    assert "{&#x27;x&#x27;: 747, &#x27;y&#x27;: 802}" in html


def test_render_dashboard_shows_anchor_mismatch_target_status(tmp_path: Path) -> None:
    write_ready_chain(tmp_path)
    write_json(
        tmp_path / "latest_locked_target.json",
        {
            "target_locked": False,
            "target_window_title": "Tina",
            "target_window_handle": 123,
            "anchor_frame": {"x": 100, "y": 80, "width": 1920, "height": 1080},
            "capture_region": {"left": 100, "top": 80, "width": 1920, "height": 1080},
            "locked_region": {"left": 100, "top": 80, "width": 1920, "height": 1080},
            "target_window_rect": {"left": 100, "top": 80, "width": 1440, "height": 1080},
            "blocked_reason": "Locked target window does not match the anchor frame after snap.",
        },
    )
    write_json(
        tmp_path / "latest_target_candidates.json",
        {
            "ok": True,
            "candidates": [
                {
                    "hwnd": 123,
                    "title": "Tina",
                    "class_name": "FlutterMultiWindow",
                    "bbox": {"left": 100, "top": 80, "width": 1440, "height": 1080},
                }
            ],
        },
    )

    html = render_dashboard(tmp_path)

    assert "Anchor frame" in html
    assert "Target window rect" in html
    assert "does not match the anchor frame" in html
    assert "Lock Target to Anchor" in html


def test_target_candidates_default_to_tina_before_editor_windows(tmp_path: Path) -> None:
    write_json(
        tmp_path / "latest_target_candidates.json",
        {
            "ok": True,
            "candidates": [
                {
                    "hwnd": 10,
                    "title": "autoworks - Visual Studio Code",
                    "class_name": "Chrome_WidgetWin_1",
                    "bbox": {"left": 2000, "top": 200, "width": 1600, "height": 1400},
                },
                {
                    "hwnd": 20,
                    "title": "Tina",
                    "class_name": "FlutterMultiWindow",
                    "bbox": {"left": 100, "top": 80, "width": 1920, "height": 1080},
                },
            ],
        },
    )

    html = render_dashboard(tmp_path)

    assert 'value="20" checked' in html
    assert html.index("Tina") < html.index("Visual Studio Code")


def test_dashboard_get_accepts_empty_query_string(tmp_path: Path) -> None:
    handler = object.__new__(DashboardHandler)
    handler.path = "/?"
    handler.runtime_state_dir = tmp_path
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = Mock()

    DashboardHandler.do_GET(handler)

    handler.send_response.assert_called_once_with(200)


def test_preview_block_preserves_existing_target_lock_diagnostics(tmp_path: Path) -> None:
    reason = "Locked target window does not match the anchor frame after snap."
    write_json(
        tmp_path / "latest_locked_target.json",
        {
            "target_locked": False,
            "target_window_rect": {"left": 100, "top": 80, "width": 1440, "height": 1080},
            "anchor_frame": {"x": 100, "y": 80, "width": 1920, "height": 1080},
            "blocked_reason": reason,
        },
    )
    handler = object.__new__(DashboardHandler)
    handler.runtime_state_dir = tmp_path

    DashboardHandler.write_blocked_lock(handler)

    payload = json.loads((tmp_path / "latest_locked_target.json").read_text(encoding="utf-8"))
    assert payload["blocked_reason"] == reason
    assert payload["target_window_rect"]["width"] == 1440
    assert payload["anchor_frame"]["width"] == 1920


def test_render_dashboard_shows_multi_action_real_click_results(tmp_path: Path) -> None:
    write_ready_chain(tmp_path)
    write_json(
        tmp_path / "latest_orchestrated_parse.json",
        {
            "requires_human_review": False,
            "parsed_page": {
                "questions": [{"question_id": "q1"}, {"question_id": "q2"}],
            },
        },
    )
    write_json(
        tmp_path / "latest_execution_gate.json",
        {
            "status": "allowed",
            "execution_allowed": True,
            "source_resolved_action_plan_id": "resolved_action_plan_1",
            "block_reasons": [],
            "executable_actions": [
                {
                    "action_id": "a1",
                    "skill": "click_option",
                    "target": {
                        "question_id": "q1",
                        "option_id": "T32",
                        "option_text": "No",
                        "resolver_source": "parsed_option_click_point",
                        "resolver_confidence": 0.82,
                        "click_point_screen": {"x": 889, "y": 683},
                    },
                },
                {
                    "action_id": "a2",
                    "skill": "click_option",
                    "target": {
                        "question_id": "q2",
                        "option_id": "T43",
                        "option_text": "No",
                        "resolver_source": "parsed_option_click_point",
                        "resolver_confidence": 0.82,
                        "click_point_screen": {"x": 890, "y": 1008},
                    },
                },
            ],
        },
    )
    write_json(
        tmp_path / "latest_action_executor_run.json",
        {
            "status": "completed",
            "validation_passed": True,
            "action_records": [
                {
                    "action_id": "a1",
                    "question_id": "q1",
                    "option_id": "T32",
                    "option_text": "No",
                    "click_point_screen": {"x": 889, "y": 683},
                    "status": "clicked_verified",
                    "verified_candidate_index": 0,
                    "verification": {"status": "selected"},
                    "click_attempts": [{"candidate_index": 0}],
                },
                {
                    "action_id": "a2",
                    "question_id": "q2",
                    "option_id": "T43",
                    "option_text": "No",
                    "click_point_screen": {"x": 890, "y": 1008},
                    "status": "clicked_verified",
                    "verified_candidate_index": 0,
                    "verification": {"status": "selected"},
                    "click_attempts": [{"candidate_index": 0}],
                },
            ],
        },
    )
    write_json(
        tmp_path / "latest_action_executor_report.json",
        {
            "validation_passed": True,
            "real_execution": True,
            "execution_attempted": True,
            "executed_action_count": 2,
        },
    )

    summary = build_runtime_summary(tmp_path)
    html = render_dashboard(tmp_path)

    assert summary["counts"]["questions"] == 2
    assert summary["counts"]["executable_actions"] == 2
    assert summary["counts"]["executor_records"] == 2
    assert "Real Click 2 Actions" in html
    assert "Action Review" in html
    assert "Executable Actions" in html
    assert "Real-click Results" in html
    assert "clicked_verified" in html
    assert "{&#x27;x&#x27;: 890, &#x27;y&#x27;: 1008}" in html
