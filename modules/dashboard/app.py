from __future__ import annotations

import argparse
import base64
import html
import json
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_STATE_DIR = PROJECT_ROOT / "runtime_state"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"error": f"could not parse {path.name}: {exc}"}


def read_events(path: Path, limit: int = 80) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"event": "invalid_jsonl", "raw": line})
    return rows


def image_data_uri(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def latest_action_record(runtime_state_dir: Path) -> dict[str, Any]:
    return read_json(runtime_state_dir / "latest_dashboard_action.json")


def first_question_decision(decision: dict[str, Any]) -> dict[str, Any]:
    questions = decision.get("question_decisions")
    if isinstance(questions, list) and questions and isinstance(questions[0], dict):
        return questions[0]
    return {}


def current_answer_approval_input(decision: dict[str, Any]) -> dict[str, Any]:
    approvals = []
    for qd in decision.get("question_decisions", []):
        if not isinstance(qd, dict):
            continue
        question_id = str(qd.get("question_id", ""))
        option_ids = [str(option_id) for option_id in qd.get("recommended_option_ids", []) if str(option_id)]
        text_answer = str(qd.get("recommended_text_answer", ""))
        if not question_id or (not option_ids and not text_answer):
            continue
        approvals.append(
            {
                "question_id": question_id,
                "approved_option_ids": option_ids,
                "approved_text_answer": text_answer,
                "review_note": "Human approved current dashboard recommendation.",
            }
        )
    return {
        "source_decision_id": decision.get("decision_id", ""),
        "session_id": decision.get("session_id", ""),
        "task_id": decision.get("task_id", ""),
        "approvals": approvals,
    }


def first_action(plan: dict[str, Any]) -> dict[str, Any]:
    actions = plan.get("executable_actions") or plan.get("actions")
    if isinstance(actions, list) and actions and isinstance(actions[0], dict):
        return actions[0]
    return {}


def action_target(action: dict[str, Any]) -> dict[str, Any]:
    target = action.get("target")
    return target if isinstance(target, dict) else {}


def action_rows(actions: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            continue
        target = action_target(action)
        rows.append(
            {
                "index": index,
                "action_id": action.get("action_id", ""),
                "skill": action.get("skill", ""),
                "question_id": target.get("question_id", action.get("question_id", "")),
                "option_id": target.get("option_id", action.get("option_id", "")),
                "option_text": target.get("option_text", action.get("option_text", "")),
                "button_id": target.get("button_id", action.get("button_id", "")),
                "navigation_action": target.get("action", action.get("navigation_action", "")),
                "navigation_text": target.get("text", action.get("navigation_text", "")),
                "resolver_source": target.get("resolver_source", ""),
                "resolver_confidence": target.get("resolver_confidence", ""),
                "click_point_screen": target.get("click_point_screen", action.get("click_point_screen", "")),
                "candidate_count": len(target.get("click_candidates", []) or []),
                "requires_review": action.get("requires_review", ""),
            }
        )
    return rows


def executor_rows(executor_run: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for index, record in enumerate(executor_run.get("action_records", []) or [], start=1):
        if not isinstance(record, dict):
            continue
        rows.append(
            {
                "index": index,
                "action_id": record.get("action_id", ""),
                "question_id": record.get("question_id", ""),
                "option_id": record.get("option_id", ""),
                "option_text": record.get("option_text", ""),
                "button_id": record.get("button_id", ""),
                "navigation_action": record.get("navigation_action", ""),
                "navigation_text": record.get("navigation_text", ""),
                "click_point_screen": record.get("click_point_screen", ""),
                "status": record.get("status", ""),
                "verified_candidate_index": record.get("verified_candidate_index", ""),
                "verification": (record.get("verification") or {}).get("status", ""),
                "attempt_count": len(record.get("click_attempts", []) or []),
            }
        )
    return rows


def bool_ok(value: Any) -> bool:
    return value is True


def validation_passed(report: dict[str, Any]) -> bool:
    return bool_ok(report.get("validation_passed")) or bool_ok(report.get("ok"))


def blocked_reason(messages: list[str], fallback: str) -> str:
    return "; ".join(message for message in messages if message) or fallback


def file_mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    return path.stat().st_mtime


def files_are_after(paths: list[Path], source: Path) -> bool:
    source_mtime = file_mtime(source)
    if source_mtime is None:
        return False
    for path in paths:
        mtime = file_mtime(path)
        if mtime is None or mtime < source_mtime:
            return False
    return True


def ids_match(left: Any, right: Any) -> bool:
    if not left or not right:
        return True
    return str(left) == str(right)


def build_runtime_summary(runtime_state_dir: Path) -> dict[str, Any]:
    parse_metrics_path = runtime_state_dir / "latest_parse_metrics.json"
    orchestrated_parse_path = runtime_state_dir / "latest_orchestrated_parse.json"
    parse_report_path = runtime_state_dir / "latest_parse_orchestrator_report.json"
    answer_report_path = runtime_state_dir / "latest_answer_engine_report.json"
    decision_path = runtime_state_dir / "latest_answer_decision.json"
    reviewed_decision_path = runtime_state_dir / "latest_reviewed_answer_decision.json"
    human_review_report_path = runtime_state_dir / "latest_human_review_report.json"
    action_plan_report_path = runtime_state_dir / "latest_action_plan_report.json"
    action_plan_path = runtime_state_dir / "latest_action_plan.json"
    target_report_path = runtime_state_dir / "latest_target_resolver_report.json"
    resolved_plan_path = runtime_state_dir / "latest_resolved_action_plan.json"
    gate_report_path = runtime_state_dir / "latest_execution_gate_report.json"
    gate_path = runtime_state_dir / "latest_execution_gate.json"
    capture_path = runtime_state_dir / "latest_capture.png"

    survey_session = read_json(runtime_state_dir / "latest_survey_session.json")
    session_report = read_json(runtime_state_dir / "latest_session_update_report.json")
    parse_report = read_json(runtime_state_dir / "latest_parse_orchestrator_report.json")
    parse_metrics = read_json(runtime_state_dir / "latest_parse_metrics.json")
    orchestrated_parse = read_json(runtime_state_dir / "latest_orchestrated_parse.json")
    answer_report = read_json(runtime_state_dir / "latest_answer_engine_report.json")
    decision = read_json(runtime_state_dir / "latest_answer_decision.json")
    reviewed_decision = read_json(runtime_state_dir / "latest_reviewed_answer_decision.json")
    human_review_report = read_json(runtime_state_dir / "latest_human_review_report.json")
    action_plan_report = read_json(runtime_state_dir / "latest_action_plan_report.json")
    action_plan = read_json(runtime_state_dir / "latest_action_plan.json")
    target_report = read_json(runtime_state_dir / "latest_target_resolver_report.json")
    resolved_plan = read_json(runtime_state_dir / "latest_resolved_action_plan.json")
    gate_report = read_json(runtime_state_dir / "latest_execution_gate_report.json")
    gate = read_json(runtime_state_dir / "latest_execution_gate.json")
    executor_report = read_json(runtime_state_dir / "latest_action_executor_report.json")
    executor_run = read_json(runtime_state_dir / "latest_action_executor_run.json")
    questions = (orchestrated_parse.get("parsed_page") or {}).get("questions", [])
    question_count = len(questions) if isinstance(questions, list) else 0
    review_applies = (
        reviewed_decision.get("requires_human_review") is False
        and human_review_report.get("requires_human_review") is False
        and ids_match(
            reviewed_decision.get("source_decision_id"),
            decision.get("decision_id"),
        )
    )
    effective_decision = reviewed_decision if review_applies else decision
    effective_decision_path = reviewed_decision_path if review_applies else decision_path
    decision_count = len(effective_decision.get("question_decisions", []) or [])
    planned_actions = action_rows(action_plan.get("actions", []) or [])
    resolved_actions = action_rows(resolved_plan.get("actions", []) or [])
    executable_actions = action_rows(gate.get("executable_actions", []) or [])
    executor_records = executor_rows(executor_run)
    recent_answers = survey_session.get("recent_answers", [])
    if not isinstance(recent_answers, list):
        recent_answers = []

    qd = first_question_decision(effective_decision)
    resolved_action = first_action(resolved_plan)
    gated_action = first_action(gate)
    target = action_target(gated_action or resolved_action)
    parse_ok = validation_passed(parse_metrics) or validation_passed(parse_report)
    parse_human_review = bool_ok(orchestrated_parse.get("requires_human_review")) or bool_ok(
        parse_report.get("requires_human_review")
    )
    answer_validation_ok = validation_passed(answer_report) or (
        review_applies and validation_passed(human_review_report)
    )
    answer_ok = answer_validation_ok and not bool_ok(
        effective_decision.get("requires_human_review")
    )
    action_plan_no_action = action_plan.get("status") == "no_action"
    action_plan_ok = (
        validation_passed(action_plan_report)
        and action_plan.get("status") not in {"human_review_required", "blocked", "invalid"}
    )
    target_ok = validation_passed(target_report)
    gate_allowed = bool_ok(gate.get("execution_allowed")) and gate.get("status") == "allowed"
    executor_dry_run_ok = executor_report.get("real_execution") is False
    parse_ready = parse_ok and not parse_human_review
    parse_fresh = files_are_after(
        [parse_metrics_path, orchestrated_parse_path, parse_report_path],
        capture_path,
    )
    answer_fresh_paths = [effective_decision_path, answer_report_path]
    if review_applies:
        answer_fresh_paths.append(human_review_report_path)
    answer_fresh = files_are_after(answer_fresh_paths, orchestrated_parse_path)
    action_plan_fresh = files_are_after(
        [action_plan_path, action_plan_report_path],
        effective_decision_path,
    )
    target_fresh = files_are_after([resolved_plan_path, target_report_path], action_plan_path)
    gate_fresh = files_are_after([gate_path, gate_report_path], resolved_plan_path)
    action_plan_lineage_ok = ids_match(
        action_plan.get("source_decision_id"),
        decision.get("decision_id"),
    )
    target_lineage_ok = ids_match(
        resolved_plan.get("source_action_plan_id"),
        action_plan.get("action_plan_id"),
    )
    gate_lineage_ok = ids_match(
        gate.get("source_resolved_action_plan_id"),
        resolved_plan.get("resolved_action_plan_id"),
    )
    answer_ready = parse_ready and parse_fresh and answer_ok and answer_fresh
    action_plan_ready = (
        answer_ready and action_plan_ok and action_plan_fresh and action_plan_lineage_ok
    )
    target_ready = (
        action_plan_ready
        and not action_plan_no_action
        and target_ok
        and target_fresh
        and target_lineage_ok
    )
    gate_ready = target_ready and gate_allowed and gate_fresh and gate_lineage_ok

    blockers = {
        "parse": "" if parse_ready and parse_fresh else blocked_reason(
            [
                "parse validation did not pass"
                if parse_report or parse_metrics
                else "parse has not run",
                "parse requires human review" if parse_human_review else "",
                "parse is older than latest capture" if parse_ready and not parse_fresh else "",
            ],
            "parse is not ready",
        ),
        "answer": "" if answer_ready else blocked_reason(
            [
                "parse is not ready" if not parse_ready else "",
                "parse is older than latest capture" if parse_ready and not parse_fresh else "",
                "answer validation did not pass"
                if answer_report and not answer_validation_ok
                else "answer has not run"
                if not answer_report
                else "",
                "answer requires human review"
                if effective_decision.get("requires_human_review") is True
                else "",
                "answer is older than latest parse" if answer_ok and not answer_fresh else "",
            ],
            "answer is not ready",
        ),
        "action_plan": "" if action_plan_ready else blocked_reason(
            [
                "answer is not ready" if not answer_ready else "",
                "action plan validation did not pass"
                if action_plan_report and not validation_passed(action_plan_report)
                else "action plan has not run"
                if not action_plan_report
                else "",
                f"action plan status={action_plan.get('status')}"
                if action_plan.get("status")
                else "",
                "action plan is older than latest answer"
                if action_plan_ok and not action_plan_fresh
                else "",
                "action plan source decision does not match latest answer"
                if action_plan_ok and not action_plan_lineage_ok
                else "",
            ],
            "action plan is not ready",
        ),
        "target_resolver": "" if target_ready else blocked_reason(
            [
                "action plan is not ready" if not action_plan_ready else "",
                "target resolver validation did not pass"
                if target_report and not target_ok
                else "target resolver has not run"
                if not target_ok
                else "",
                "resolved action plan is older than latest action plan"
                if target_ok and not target_fresh
                else "",
                "resolved action plan source does not match latest action plan"
                if target_ok and not target_lineage_ok
                else "",
            ],
            "target resolver is not ready",
        ),
        "execution_gate": "" if gate_ready else blocked_reason(
            [
                "target resolver is not ready" if not target_ready else "",
                f"execution gate status={gate.get('status')}" if gate.get("status") else "",
                "execution_allowed is not true"
                if gate and gate.get("execution_allowed") is not True
                else "",
                json.dumps(gate.get("block_reasons"), ensure_ascii=False)
                if gate.get("block_reasons")
                else "",
                "execution gate is older than latest resolved action plan"
                if gate_allowed and not gate_fresh
                else "",
                "execution gate source does not match latest resolved action plan"
                if gate_allowed and not gate_lineage_ok
                else "",
            ],
            "execution gate is not allowed",
        ),
    }

    return {
        "parse": {
            "status": "ready" if parse_ready and parse_fresh else "blocked",
            "mode_used": parse_metrics.get("mode_used", ""),
            "strategy_used": parse_metrics.get("strategy_used")
            or parse_report.get("selected_strategy", ""),
            "model_calls_count": parse_metrics.get("model_calls_count")
            or parse_report.get("model_calls_count", ""),
            "validation_passed": parse_ok,
            "requires_human_review": parse_human_review,
            "fresh": parse_fresh,
            "fallback_used": parse_metrics.get("fallback_used", ""),
            "elapsed_time_ms": parse_metrics.get("elapsed_time_ms", ""),
            "blocked_reason": blockers["parse"],
        },
        "answer": {
            "status": "ready" if answer_ready else "blocked",
            "answer_strategy": qd.get("answer_strategy", ""),
            "answer_mode": qd.get("answer_mode", ""),
            "recommended_option_ids": qd.get("recommended_option_ids", []),
            "selected_option_text": first_text(
                [target.get("option_text"), target.get("text"), *option_texts(qd)]
            ),
            "requires_human_review": decision.get("requires_human_review", ""),
            "review_applied": review_applies,
            "validation_passed": answer_validation_ok,
            "fresh": answer_fresh,
            "blocked_reason": blockers["answer"],
        },
        "session": {
            "status": session_status(survey_session, session_report),
            "flow_status": survey_session.get("flow_status")
            or session_report.get("flow_status", ""),
            "session_continuity": survey_session.get("session_continuity")
            or session_report.get("session_continuity", ""),
            "session_continuity_reason": survey_session.get("session_continuity_reason")
            or session_report.get("session_continuity_reason", ""),
            "current_page_index": survey_session.get("current_page_index", ""),
            "page_count": len(survey_session.get("pages", []) or []),
            "recent_answer_count": len(recent_answers),
            "recent_answers": recent_answers[-5:],
            "validation_passed": validation_passed(session_report),
            "blocked_reason": session_report.get("errors", []),
        },
        "action_plan": {
            "status": "no_action" if action_plan_no_action else "ready" if action_plan_ready else "blocked",
            "skill": (first_action(action_plan).get("skill") or resolved_action.get("skill") or ""),
            "option_id": action_target(first_action(action_plan)).get("option_id")
            or target.get("option_id", ""),
            "option_text": action_target(first_action(action_plan)).get("option_text")
            or target.get("option_text", ""),
            "validation_passed": validation_passed(action_plan_report),
            "fresh": action_plan_fresh,
            "lineage_ok": action_plan_lineage_ok,
            "blocked_reason": blockers["action_plan"],
        },
        "target_resolver": {
            "status": "ready" if target_ready else "blocked",
            "resolver_source": target.get("resolver_source", ""),
            "resolver_confidence": target.get("resolver_confidence", ""),
            "click_point_screen": target.get("click_point_screen", ""),
            "validation_passed": target_ok,
            "fresh": target_fresh,
            "lineage_ok": target_lineage_ok,
            "blocked_reason": blockers["target_resolver"],
        },
        "execution_gate": {
            "status": "allowed" if gate_ready else "blocked",
            "execution_allowed": gate.get("execution_allowed", ""),
            "block_reasons": gate.get("block_reasons", []),
            "validation_passed": validation_passed(gate_report),
            "fresh": gate_fresh,
            "lineage_ok": gate_lineage_ok,
            "blocked_reason": blockers["execution_gate"],
        },
        "executor": {
            "status": executor_run.get("status", ""),
            "validation_passed": validation_passed(executor_report),
            "real_execution": executor_report.get("real_execution", ""),
            "execution_attempted": executor_report.get("execution_attempted", ""),
            "executed_action_count": executor_report.get("executed_action_count", ""),
            "dry_run_ok": executor_dry_run_ok,
        },
        "counts": {
            "questions": question_count,
            "decisions": decision_count,
            "planned_actions": len(planned_actions),
            "resolved_actions": len(resolved_actions),
            "executable_actions": len(executable_actions),
            "executor_records": len(executor_records),
        },
        "actions": {
            "planned": planned_actions,
            "resolved": resolved_actions,
            "executable": executable_actions,
            "executor_records": executor_records,
        },
        "can_run": {
            "parse": (runtime_state_dir / "latest_runtime_context.json").exists()
            and (runtime_state_dir / "latest_layout_index.json").exists(),
            "answer": parse_ready and parse_fresh,
            "action_plan": answer_ready,
            "target_resolver": action_plan_ready and not action_plan_no_action,
            "execution_gate": target_ready,
            "executor_dry_run": gate_ready,
            "real_click": gate_ready,
        },
    }


def session_status(session: dict[str, Any], report: dict[str, Any]) -> str:
    flow_status = str(session.get("flow_status") or report.get("flow_status") or "")
    continuity = str(session.get("session_continuity") or report.get("session_continuity") or "")
    if flow_status == "finished":
        return "completed"
    if flow_status == "kicked_out":
        return "blocked"
    if continuity == "possible_new_session":
        return "waiting_review"
    if validation_passed(report):
        return "ready"
    return "unknown"


def option_texts(question_decision: dict[str, Any]) -> list[str]:
    targets = question_decision.get("click_targets")
    if not isinstance(targets, list):
        return []
    return [str(item.get("text") or "") for item in targets if isinstance(item, dict)]


def first_text(values: list[Any]) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def render_dashboard(runtime_state_dir: Path = RUNTIME_STATE_DIR) -> str:
    pipeline = read_json(runtime_state_dir / "latest_pipeline_run.json")
    locked_target = read_json(runtime_state_dir / "latest_locked_target.json")
    target_candidates = read_json(runtime_state_dir / "latest_target_candidates.json")
    capture_provenance = read_json(runtime_state_dir / "latest_capture_provenance.json")
    decision = read_json(runtime_state_dir / "latest_answer_decision.json")
    reviewed_decision = read_json(runtime_state_dir / "latest_reviewed_answer_decision.json")
    action_plan = read_json(runtime_state_dir / "latest_action_plan.json")
    resolved_plan = read_json(runtime_state_dir / "latest_resolved_action_plan.json")
    events = read_events(runtime_state_dir / "latest_pipeline_events.jsonl")
    summary = build_runtime_summary(runtime_state_dir)
    dashboard_action = latest_action_record(runtime_state_dir)

    screenshot = first_existing([runtime_state_dir / "latest_capture.png"])
    annotated = first_existing(
        [
            runtime_state_dir / "latest_annotated_overview.png",
        ]
    )
    model_input = first_existing([runtime_state_dir / "latest_model_input.png"])
    click_preview = first_existing(
        [
            runtime_state_dir / "latest_click_preview.png",
            runtime_state_dir / "latest_action_executor_preview.png",
            runtime_state_dir / "latest_action_executor_preview.jpg",
        ]
    )

    warnings = collect_messages(pipeline, "warnings")
    errors = collect_messages(pipeline, "errors")
    status = pipeline.get("status", "no pipeline run")
    run_id = pipeline.get("run_id", "")
    target_locked = locked_target.get("target_locked") is True
    blocked_reason = (
        ""
        if target_locked
        else (
            locked_target.get("blocked_reason")
            or "No locked target window. Please snap and lock the KVM/remote window before "
            "running preview."
        )
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="5">
  <title>Autoworks Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #697586;
      --border: #d8dde6;
      --accent: #16697a;
      --ok: #207a45;
      --bad: #b42318;
      --wait: #9a6700;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Segoe UI, Arial, sans-serif;
      color: var(--text);
      background: var(--bg);
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
    }}
    h1, h2 {{ margin: 0; }}
    h1 {{ font-size: 22px; }}
    h2 {{ font-size: 16px; margin-bottom: 10px; }}
    main {{
      display: grid;
      grid-template-columns: minmax(360px, 1.1fr) minmax(360px, .9fr);
      gap: 16px;
      padding: 16px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .status {{ font-weight: 700; color: {status_color(status)}; }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .imagebox {{
      border: 1px solid var(--border);
      border-radius: 8px;
      min-height: 180px;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #eef1f5;
    }}
    img {{ max-width: 100%; max-height: 420px; display: block; }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #f9fafb;
      max-height: 360px;
      overflow: auto;
      font-size: 13px;
    }}
    .wide {{ grid-column: 1 / -1; }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    button {{
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #fff;
      padding: 8px 10px;
      cursor: pointer;
    }}
    button.primary {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
    button.danger {{ border-color: var(--bad); color: var(--bad); }}
    button:disabled {{ color: var(--muted); cursor: not-allowed; }}
    .badge {{
      display: inline-block;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      color: var(--muted);
    }}
    ul {{ margin: 0; padding-left: 18px; }}
    @media (max-width: 900px) {{
      main, .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Autoworks Dashboard</h1>
      <div class="muted">{escape(run_id)}</div>
    </div>
    <div class="status">{escape(status)}</div>
  </header>
  <main>
    <section class="wide">
      <h2>Target Controls</h2>
      {render_controls(target_locked, summary)}
      {render_dashboard_action(dashboard_action)}
    </section>
    <section class="wide">
      <h2>Locked Target</h2>
      {render_target_status(locked_target, capture_provenance, blocked_reason)}
    </section>
    <section class="wide">
      <h2>Target Candidates</h2>
      {render_target_candidates(target_candidates)}
    </section>
    <section>
      <h2>Step Status</h2>
      {render_step_table(pipeline.get("steps", []))}
    </section>
    <section>
      <h2>Run Summary</h2>
      {render_run_summary(summary)}
    </section>
    <section class="wide">
      <h2>Action Review</h2>
      {render_action_review(summary)}
    </section>
    <section>
      <h2>Errors and Warnings</h2>
      {render_messages("Errors", errors)}
      {render_messages("Warnings", warnings)}
    </section>
    <section class="wide">
      <h2>Images</h2>
      <div class="grid">
        {render_image("Latest Screenshot", screenshot)}
        {render_image("Latest Annotated Overview", annotated)}
        {render_image("Latest Model Input", model_input)}
      </div>
    </section>
    <section>
      <h2>Latest Answer Decision</h2>
      {render_session_memory(summary)}
      {render_answer_brief(summary)}
      <pre>{escape(json.dumps(reviewed_decision or decision, indent=2, ensure_ascii=False))}</pre>
    </section>
    <section>
      <h2>Latest Action Plan</h2>
      {render_click_brief(summary)}
      <pre>{escape(json.dumps(resolved_plan or action_plan, indent=2, ensure_ascii=False))}</pre>
    </section>
    <section class="wide">
      <h2>Latest Events</h2>
      <pre>{escape(json.dumps(events, indent=2, ensure_ascii=False))}</pre>
    </section>
  </main>
</body>
</html>"""


def render_controls(target_locked: bool, summary: dict[str, Any]) -> str:
    run_disabled = "" if target_locked else " disabled"
    can_run = summary.get("can_run", {})
    executable_count = int((summary.get("counts") or {}).get("executable_actions") or 0)
    real_click_label = (
        f"Real Click {executable_count} Action"
        if executable_count == 1
        else f"Real Click {executable_count} Actions"
    )
    controls = [
        '<form method="post" action="/snap-target"><button>Refresh Targets</button></form>',
        '<form method="post" action="/capture-locked"><button>Capture Locked Window</button></form>',
        '<form method="get" action="/"><button>Check Status</button></form>',
        control_form("/run-parse", "Run Parse", can_run.get("parse")),
        control_form("/run-answer", "Run Answer", can_run.get("answer")),
        control_form("/run-action-plan", "Run Action Plan", can_run.get("action_plan")),
        control_form(
            "/run-target-resolver",
            "Run Target Resolver",
            can_run.get("target_resolver"),
        ),
        control_form("/run-execution-gate", "Run Execution Gate", can_run.get("execution_gate")),
        control_form(
            "/run-executor-dry-run",
            "Run Dry-Run Executor",
            can_run.get("executor_dry_run"),
        ),
        control_form(
            "/approve-current-answer",
            "Approve Current Answer",
            summary.get("answer", {}).get("status") == "blocked"
            and bool(summary.get("answer", {}).get("recommended_option_ids")),
        ),
        (
            '<form method="post" action="/run-preview">'
            f'<button class="primary"{run_disabled}>Run Full Dry Preview</button></form>'
        ),
        (
            '<form method="post" action="/run-session-loop">'
            f'<button class="danger"{run_disabled}>Run Session Loop</button></form>'
        ),
        control_form(
            "/run-real-click-once",
            real_click_label,
            can_run.get("real_click") and target_locked,
            "danger",
        ),
    ]
    return '<div class="controls">' + "".join(controls) + "</div>"


def control_form(action: str, label: str, enabled: Any, button_class: str = "") -> str:
    disabled = "" if enabled else " disabled"
    css_class = f' class="{button_class}"' if button_class else ""
    return (
        f'<form method="post" action="{action}">'
        f"<button{css_class}{disabled}>{label}</button></form>"
    )


def render_dashboard_action(action: dict[str, Any]) -> str:
    if not action:
        return ""
    status = action.get("status", "")
    command = action.get("command_text", "")
    return (
        '<p class="muted">'
        f"Last action: <span class=\"badge\">{escape(status)}</span> {escape(command)}"
        "</p>"
    )


def render_run_summary(summary: dict[str, Any]) -> str:
    rows = [
        ("Parse", summary.get("parse", {})),
        ("Session", summary.get("session", {})),
        ("Answer", summary.get("answer", {})),
        ("Action Plan", summary.get("action_plan", {})),
        ("Target Resolver", summary.get("target_resolver", {})),
        ("Execution Gate", summary.get("execution_gate", {})),
        ("Dry-Run Executor", summary.get("executor", {})),
    ]
    body = []
    for label, data in rows:
        status = str(
            data.get("status") or ("ready" if data.get("validation_passed") else "unknown")
        )
        reason = data.get("blocked_reason", "")
        details = compact_details(data)
        body.append(
            "<tr>"
            f"<th>{escape(label)}</th>"
            f"<td style=\"color:{status_color(status)}\">{escape(status)}</td>"
            f"<td>{escape(details)}</td>"
            f"<td>{escape(reason)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Step</th><th>Status</th><th>Details</th><th>Stop Reason</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def render_action_review(summary: dict[str, Any]) -> str:
    counts = summary.get("counts", {})
    actions = summary.get("actions", {})
    header = (
        '<p class="muted">'
        f"Questions: {escape(counts.get('questions', 0))} | "
        f"Decisions: {escape(counts.get('decisions', 0))} | "
        f"Resolved actions: {escape(counts.get('resolved_actions', 0))} | "
        f"Executable actions: {escape(counts.get('executable_actions', 0))} | "
        f"Executor records: {escape(counts.get('executor_records', 0))}"
        "</p>"
    )
    return (
        header
        + render_action_table("Executable Actions", actions.get("executable", []))
        + render_executor_table(actions.get("executor_records", []))
    )


def render_session_memory(summary: dict[str, Any]) -> str:
    session = summary.get("session", {})
    recent_answers = session.get("recent_answers", [])
    if not isinstance(recent_answers, list):
        recent_answers = []
    continuity = str(session.get("session_continuity") or "")
    reason = str(session.get("session_continuity_reason") or "")
    prompt = ""
    if continuity and continuity != "same_session":
        prompt = (
            '<p class="muted">'
            f"Session prompt: <span class=\"badge\">{escape(continuity)}</span> "
            f"{escape(reason)}"
            "</p>"
        )
    summary_line = (
        '<p class="muted">'
        f"Session: flow={escape(session.get('flow_status', ''))}; "
        f"page={escape(session.get('current_page_index', ''))}/"
        f"{escape(session.get('page_count', ''))}; "
        f"recent answers={escape(session.get('recent_answer_count', 0))}"
        "</p>"
    )
    if not recent_answers:
        return prompt + summary_line
    rows = []
    for item in reversed(recent_answers[-5:]):
        question = str(item.get("question_text") or item.get("question_id") or "")
        answer = str(item.get("answer_text") or "")
        confirmed = "confirmed" if item.get("confirmed") else "candidate"
        rows.append(
            "<li>"
            f"{escape(short_text(question, 90))} -> {escape(short_text(answer, 60))} "
            f"<span class=\"badge\">{escape(confirmed)}</span>"
            "</li>"
        )
    return prompt + summary_line + "<ul>" + "".join(rows) + "</ul>"


def short_text(value: str, limit: int) -> str:
    value = " ".join(str(value or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def render_action_table(label: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f'<p class="muted">{escape(label)}: none</p>'
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{escape(row.get('index', ''))}</td>"
            f"<td>{escape(row.get('action_id', ''))}</td>"
            f"<td>{escape(row.get('question_id', ''))}</td>"
            f"<td>{escape(row.get('option_id', ''))}</td>"
            f"<td>{escape(row.get('option_text', '') or row.get('navigation_text', ''))}</td>"
            f"<td>{escape(row.get('click_point_screen', ''))}</td>"
            f"<td>{escape(row.get('resolver_source', ''))}</td>"
            f"<td>{escape(row.get('resolver_confidence', ''))}</td>"
            "</tr>"
        )
    return (
        f"<p>{escape(label)}</p>"
        "<table><thead><tr><th>#</th><th>Action</th><th>Question</th><th>Option</th>"
        "<th>Text</th><th>Click point</th><th>Resolver</th><th>Confidence</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def render_executor_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="muted">Real-click results: none</p>'
    body = []
    for row in rows:
        status = str(row.get("status", ""))
        body.append(
            "<tr>"
            f"<td>{escape(row.get('index', ''))}</td>"
            f"<td>{escape(row.get('action_id', ''))}</td>"
            f"<td>{escape(row.get('question_id', ''))}</td>"
            f"<td>{escape(row.get('option_text', '') or row.get('navigation_text', ''))}</td>"
            f"<td>{escape(row.get('click_point_screen', ''))}</td>"
            f"<td style=\"color:{status_color(status)}\">{escape(status)}</td>"
            f"<td>{escape(row.get('verified_candidate_index', ''))}</td>"
            f"<td>{escape(row.get('verification', ''))}</td>"
            f"<td>{escape(row.get('attempt_count', ''))}</td>"
            "</tr>"
        )
    return (
        "<p>Real-click Results</p>"
        "<table><thead><tr><th>#</th><th>Action</th><th>Question</th><th>Text</th>"
        "<th>Click point</th><th>Status</th><th>Verified candidate</th>"
        "<th>Verification</th><th>Attempts</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def compact_details(data: dict[str, Any]) -> str:
    skip = {"status", "blocked_reason", "block_reasons", "recent_answers"}
    parts = []
    for key, value in data.items():
        if key in skip or value == "" or value == [] or value == {} or value is None:
            continue
        parts.append(f"{key}={value}")
    return "; ".join(parts[:5])


def render_answer_brief(summary: dict[str, Any]) -> str:
    answer = summary.get("answer", {})
    return (
        '<p class="muted">'
        f"Strategy: {escape(answer.get('answer_strategy', ''))} | "
        f"Mode: {escape(answer.get('answer_mode', ''))} | "
        f"Selected: {escape(answer.get('recommended_option_ids', []))} "
        f"{escape(answer.get('selected_option_text', ''))}"
        "</p>"
    )


def render_click_brief(summary: dict[str, Any]) -> str:
    resolver = summary.get("target_resolver", {})
    gate = summary.get("execution_gate", {})
    return (
        '<p class="muted">'
        f"Click point: {escape(resolver.get('click_point_screen', ''))} | "
        f"Resolver: {escape(resolver.get('resolver_source', ''))} | "
        f"Gate: {escape(gate.get('status', ''))} "
        f"allowed={escape(gate.get('execution_allowed', ''))}"
        "</p>"
    )


def render_target_status(
    locked_target: dict[str, Any],
    capture_provenance: dict[str, Any],
    blocked_reason: str,
) -> str:
    status = "locked" if locked_target.get("target_locked") is True else "unlocked"
    rows = {
        "Status": status,
        "Target window title": locked_target.get("target_window_title", ""),
        "Target window handle": locked_target.get("target_window_handle", ""),
        "Anchor frame": locked_target.get("anchor_frame", ""),
        "Target window rect": locked_target.get("target_window_rect", ""),
        "Locked target region": (
            locked_target.get("locked_region") or locked_target.get("bbox") or ""
        ),
        "DPI scale": locked_target.get("dpi_scale", ""),
        "Capture timestamp": capture_provenance.get("screenshot_mtime", ""),
        "Capture image hash": capture_provenance.get("image_hash", ""),
        "Blocked reason": "" if status == "locked" else blocked_reason,
    }
    body = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>"
        for label, value in rows.items()
    )
    return f"<table><tbody>{body}</tbody></table>"


def render_target_candidates(target_candidates: dict[str, Any]) -> str:
    candidates = target_candidates.get("candidates") or []
    if not candidates:
        return '<div class="muted">No candidate snapshot found.</div>'
    rows = []
    sorted_candidates = sorted(candidates, key=target_candidate_sort_key)
    for index, candidate in enumerate(sorted_candidates):
        hwnd = candidate.get("hwnd", "")
        checked = " checked" if index == 0 else ""
        rows.append(
            "<tr>"
            f"<td><input type=\"radio\" name=\"hwnd\" value=\"{escape(hwnd)}\"{checked}></td>"
            f"<td>{escape(candidate.get('title', ''))}</td>"
            f"<td>{escape(candidate.get('class_name', ''))}</td>"
            f"<td>{escape(hwnd)}</td>"
            f"<td>{escape(candidate.get('bbox', ''))}</td>"
            "</tr>"
        )
    return (
        '<form method="post" action="/lock-target">'
        "<table><thead><tr><th></th><th>Title</th><th>Class</th><th>Handle</th>"
        "<th>Region</th></tr></thead><tbody>"
        + "".join(rows)
        + '</tbody></table><p><button>Lock Target to Anchor</button></p></form>'
    )


def target_candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, str]:
    title = str(candidate.get("title", "")).lower()
    class_name = str(candidate.get("class_name", "")).lower()
    bbox = candidate.get("bbox") or {}
    area = int(bbox.get("width") or 0) * int(bbox.get("height") or 0)
    if title == "tina":
        priority = 0
    elif "flutter" in class_name or "oray" in class_name:
        priority = 1
    elif "dashboard" in title or "visual studio code" in title:
        priority = 3
    else:
        priority = 2
    return (priority, -area, title)


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def render_step_table(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return '<div class="muted">No pipeline state found.</div>'
    rows = []
    for step in steps:
        rows.append(
            "<tr>"
            f"<td>{escape(step.get('name', ''))}</td>"
            f"<td style=\"color:{status_color(str(step.get('status', '')))}\">"
            f"{escape(step.get('status', ''))}</td>"
            f"<td>{escape(step.get('summary', ''))}</td>"
            f"<td>{escape(str(step.get('duration_ms') or ''))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Step</th><th>Status</th><th>Summary</th>"
        "<th>ms</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_image(label: str, path: Path | None) -> str:
    if path is None:
        body = '<span class="muted">Missing</span>'
    else:
        uri = image_data_uri(path)
        body = (
            f'<img src="{uri}" alt="{escape(label)}">'
            if uri
            else '<span class="muted">Missing</span>'
        )
    return (
        f'<div><div class="muted">{escape(label)}</div>'
        f'<div class="imagebox">{body}</div></div>'
    )


def render_messages(label: str, messages: list[str]) -> str:
    if not messages:
        return f'<p class="muted">{escape(label)}: none</p>'
    rows = "".join(f"<li>{escape(message)}</li>" for message in messages[-20:])
    return f"<p>{escape(label)}</p><ul>{rows}</ul>"


def collect_messages(pipeline: dict[str, Any], key: str) -> list[str]:
    values = [str(item) for item in pipeline.get(key, [])]
    for step in pipeline.get("steps", []):
        values.extend(str(item) for item in step.get(key, []))
    return values


def status_color(status: str) -> str:
    if status in {"success", "completed", "allowed", "ready", "no_action"}:
        return "var(--ok)"
    if status in {"failed", "blocked", "not_allowed", "invalid"}:
        return "var(--bad)"
    if status in {"waiting_review", "running", "pending"}:
        return "var(--wait)"
    return "var(--accent)"


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


class DashboardHandler(BaseHTTPRequestHandler):
    runtime_state_dir = RUNTIME_STATE_DIR

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path not in {"/", "/index.html"}:
            self.send_error(404)
            return
        body = render_dashboard(self.runtime_state_dir).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            if self.path == "/snap-target":
                from modules.window_capture.target_lock import snap_targets

                snap_targets(self.runtime_state_dir)
                self.redirect_home()
                return
            if self.path == "/lock-target":
                from modules.window_capture.target_lock import (
                    lock_saved_target,
                    lock_target_by_handle,
                )

                form = self.read_form()
                hwnd = (form.get("hwnd") or [""])[0]
                if hwnd:
                    lock_target_by_handle(int(hwnd), self.runtime_state_dir)
                else:
                    lock_saved_target(self.runtime_state_dir)
                self.redirect_home()
                return
            if self.path == "/capture-locked":
                from modules.window_capture.target_lock import capture_locked_target

                capture_locked_target(runtime_state_dir=self.runtime_state_dir)
                self.redirect_home()
                return
            if self.path == "/approve-current-answer":
                decision = read_json(self.runtime_state_dir / "latest_answer_decision.json")
                manual_input = current_answer_approval_input(decision)
                if not manual_input.get("source_decision_id") or not manual_input.get("approvals"):
                    self.write_action_error("No current answer recommendation is available to approve.")
                    self.redirect_home()
                    return
                write_json(self.runtime_state_dir / "manual_review_input.json", manual_input)
                command = [
                    sys.executable,
                    "-m",
                    "modules.human_review.human_review_processor",
                    "--source",
                    "auto",
                ]
                self.run_dashboard_command(command)
                self.redirect_home()
                return
            if self.path == "/run-preview":
                locked_target = read_json(self.runtime_state_dir / "latest_locked_target.json")
                if locked_target.get("target_locked") is not True:
                    self.write_blocked_lock()
                    self.redirect_home()
                    return
                command = [
                    sys.executable,
                    "-m",
                    "modules.autoworks_runner.run_once",
                    "--mode",
                    "preview",
                    "--parser-mode",
                    "ollama",
                    "--ocr",
                    "rapidocr",
                ]
                self.run_dashboard_command(command)
                self.redirect_home()
                return
            if self.path == "/run-session-loop":
                locked_target = read_json(self.runtime_state_dir / "latest_locked_target.json")
                if locked_target.get("target_locked") is not True:
                    self.write_blocked_lock()
                    self.redirect_home()
                    return
                command = [
                    sys.executable,
                    "-m",
                    "modules.autoworks_runner.run_once",
                    "--mode",
                    "session",
                    "--parser-mode",
                    "ollama",
                    "--ocr",
                    "rapidocr",
                ]
                self.run_dashboard_command(command)
                self.redirect_home()
                return
            step_commands = {
                "/run-parse": [
                    sys.executable,
                    "-m",
                    "modules.parse_orchestrator.orchestrator",
                    "--mode",
                    "ollama",
                ],
                "/run-answer": [sys.executable, "-m", "modules.answer_engine.answer_engine"],
                "/run-action-plan": [
                    sys.executable,
                    "-m",
                    "modules.action_plan.action_plan_builder",
                    "--source",
                    "auto",
                ],
                "/run-target-resolver": [
                    sys.executable,
                    "-m",
                    "modules.target_resolver.target_resolver",
                ],
                "/run-execution-gate": [
                    sys.executable,
                    "-m",
                    "modules.execution_gate.execution_gate",
                ],
                "/run-executor-dry-run": [
                    sys.executable,
                    "-m",
                    "modules.action_executor.action_executor",
                    "--dry-run",
                ],
                "/run-real-click-once": [
                    sys.executable,
                    "-m",
                    "modules.action_executor.action_executor",
                ],
            }
            if self.path in step_commands:
                if not self.step_allowed(self.path):
                    self.write_action_error(f"{self.path} is blocked by current runtime state.")
                    self.redirect_home()
                    return
                self.run_dashboard_command(step_commands[self.path])
                self.redirect_home()
                return
        except Exception as exc:
            self.write_action_error(str(exc))
            self.redirect_home()
            return
        self.send_error(404)

    def read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        return parse_qs(self.rfile.read(length).decode("utf-8"))

    def redirect_home(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def write_blocked_lock(self) -> None:
        path = self.runtime_state_dir / "latest_locked_target.json"
        existing = read_json(path)
        reason = (
            existing.get("blocked_reason")
            or "No locked target window. Please snap and lock the KVM/remote window before "
            "running preview."
        )
        payload = dict(existing) if isinstance(existing, dict) else {}
        payload["target_locked"] = False
        payload["blocked_reason"] = reason
        payload["errors"] = payload.get("errors") or [reason]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write_action_error(self, message: str) -> None:
        path = self.runtime_state_dir / "latest_dashboard_action_error.json"
        payload = {"status": "blocked", "error": message, "created_at": utc_now()}
        write_json(path, payload)
        write_json(self.runtime_state_dir / "latest_dashboard_action.json", payload)

    def step_allowed(self, path: str) -> bool:
        summary = build_runtime_summary(self.runtime_state_dir)
        can_run = summary.get("can_run", {})
        locked_target = read_json(self.runtime_state_dir / "latest_locked_target.json")
        target_locked = locked_target.get("target_locked") is True
        return {
            "/run-parse": bool(can_run.get("parse")),
            "/run-answer": bool(can_run.get("answer")),
            "/run-action-plan": bool(can_run.get("action_plan")),
            "/run-target-resolver": bool(can_run.get("target_resolver")),
            "/run-execution-gate": bool(can_run.get("execution_gate")),
            "/run-executor-dry-run": bool(can_run.get("executor_dry_run")),
            "/run-real-click-once": bool(can_run.get("real_click")) and target_locked,
        }.get(path, False)

    def run_dashboard_command(self, command: list[str]) -> None:
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            check=False,
            capture_output=True,
            text=True,
        )
        status = "success" if completed.returncode == 0 else "failed"
        write_json(
            self.runtime_state_dir / "latest_dashboard_action.json",
            {
                "status": status,
                "command": command,
                "command_text": " ".join(command),
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
                "created_at": utc_now(),
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        return


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve a local Autoworks runtime dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--runtime-state", default=str(RUNTIME_STATE_DIR))
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    handler = type("ConfiguredDashboardHandler", (DashboardHandler,), {})
    handler.runtime_state_dir = Path(args.runtime_state)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Autoworks dashboard: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
