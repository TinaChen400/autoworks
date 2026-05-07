from __future__ import annotations

import argparse
import base64
import html
import json
import subprocess
import sys
from urllib.parse import parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


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
    blocked_reason = "" if target_locked else (
        locked_target.get("blocked_reason")
        or "No locked target window. Please snap and lock the KVM/remote window before running preview."
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
    th, td {{ border-bottom: 1px solid var(--border); padding: 8px; text-align: left; vertical-align: top; }}
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
    button:disabled {{ color: var(--muted); cursor: not-allowed; }}
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
      {render_controls(target_locked)}
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
      <pre>{escape(json.dumps(reviewed_decision or decision, indent=2, ensure_ascii=False))}</pre>
    </section>
    <section>
      <h2>Latest Action Plan</h2>
      <pre>{escape(json.dumps(resolved_plan or action_plan, indent=2, ensure_ascii=False))}</pre>
    </section>
    <section class="wide">
      <h2>Latest Events</h2>
      <pre>{escape(json.dumps(events, indent=2, ensure_ascii=False))}</pre>
    </section>
  </main>
</body>
</html>"""


def render_controls(target_locked: bool) -> str:
    run_disabled = "" if target_locked else " disabled"
    return (
        '<div class="controls">'
        '<form method="post" action="/snap-target"><button>Snap Target</button></form>'
        '<form method="post" action="/capture-locked"><button>Capture Locked Window</button></form>'
        f'<form method="post" action="/run-preview"><button class="primary"{run_disabled}>Run Preview</button></form>'
        '<form method="get" action="/"><button>Refresh Status</button></form>'
        "</div>"
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
        "Locked target region": locked_target.get("locked_region") or locked_target.get("bbox") or "",
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
    for index, candidate in enumerate(candidates):
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
        + '</tbody></table><p><button>Lock Target</button></p></form>'
    )


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
        body = f'<img src="{uri}" alt="{escape(label)}">' if uri else '<span class="muted">Missing</span>'
    return f"<div><div class=\"muted\">{escape(label)}</div><div class=\"imagebox\">{body}</div></div>"


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
    if status in {"success", "completed", "allowed"}:
        return "var(--ok)"
    if status in {"failed", "blocked", "not_allowed"}:
        return "var(--bad)"
    if status in {"waiting_review", "running", "pending"}:
        return "var(--wait)"
    return "var(--accent)"


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


class DashboardHandler(BaseHTTPRequestHandler):
    runtime_state_dir = RUNTIME_STATE_DIR

    def do_GET(self) -> None:
        if self.path not in {"/", "/index.html"}:
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
                from modules.window_capture.target_lock import lock_saved_target, lock_target_by_handle

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
            if self.path == "/run-preview":
                locked_target = read_json(self.runtime_state_dir / "latest_locked_target.json")
                if locked_target.get("target_locked") is not True:
                    self.write_blocked_lock()
                    self.redirect_home()
                    return
                command = [sys.executable, "-m", "modules.autoworks_runner.run_once", "--mode", "preview"]
                subprocess.run(
                    command,
                    cwd=str(PROJECT_ROOT),
                    check=False,
                    capture_output=True,
                    text=True,
                )
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
        payload = {
            "target_locked": False,
            "blocked_reason": (
                "No locked target window. Please snap and lock the KVM/remote window before running preview."
            ),
            "errors": [
                "No locked target window. Please snap and lock the KVM/remote window before running preview."
            ],
        }
        path = self.runtime_state_dir / "latest_locked_target.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write_action_error(self, message: str) -> None:
        path = self.runtime_state_dir / "latest_dashboard_action_error.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"error": message}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def log_message(self, format: str, *args: Any) -> None:
        return


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
