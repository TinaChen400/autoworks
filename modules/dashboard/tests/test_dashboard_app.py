from __future__ import annotations

import json
import os
from pathlib import Path

from modules.dashboard.app import build_runtime_summary, render_dashboard


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
            "requires_human_review": True,
            "question_decisions": [
                {
                    "answer_strategy": "profile_llm_strategy",
                    "answer_mode": "strict_private",
                    "recommended_option_ids": [],
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

    assert "Run Dry-Run Executor" in html
    assert "Real Click Once" in html
    assert "/run-real-click-once" in html
    assert "parsed_control_click_point" in html
    assert "{&#x27;x&#x27;: 747, &#x27;y&#x27;: 802}" in html
