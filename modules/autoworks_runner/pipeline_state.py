from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_STATE_DIR = PROJECT_ROOT / "runtime_state"
PIPELINE_STATE_PATH = RUNTIME_STATE_DIR / "latest_pipeline_run.json"
PIPELINE_EVENTS_PATH = RUNTIME_STATE_DIR / "latest_pipeline_events.jsonl"

StepStatus = Literal[
    "pending",
    "running",
    "success",
    "failed",
    "blocked",
    "skipped",
    "waiting_review",
    "not_allowed",
]
RunStatus = Literal[
    "pending",
    "running",
    "success",
    "partial_success",
    "failed",
    "blocked",
    "waiting_review",
]

STEP_STATUSES: set[str] = {
    "pending",
    "running",
    "success",
    "failed",
    "blocked",
    "skipped",
    "waiting_review",
    "not_allowed",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StepRecord:
    name: str
    status: StepStatus = "pending"
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    summary: str = ""
    output_paths: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "summary": self.summary,
            "output_paths": self.output_paths,
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": self.metadata,
        }


class PipelineState:
    def __init__(
        self,
        *,
        steps: list[str],
        runtime_state_dir: Path = RUNTIME_STATE_DIR,
        run_id: str | None = None,
        mode: str = "dry-run",
        task_id: str = "tts01",
    ) -> None:
        self.runtime_state_dir = Path(runtime_state_dir)
        self.state_path = self.runtime_state_dir / "latest_pipeline_run.json"
        self.events_path = self.runtime_state_dir / "latest_pipeline_events.jsonl"
        self.run_id = run_id or f"pipeline_run_{uuid.uuid4().hex}"
        self.mode = mode
        self.task_id = task_id
        self.status: RunStatus = "pending"
        self.created_at = now_iso()
        self.updated_at = self.created_at
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.steps: dict[str, StepRecord] = {name: StepRecord(name=name) for name in steps}
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.metadata: dict[str, Any] = {}

    def initialize(self) -> None:
        self.runtime_state_dir.mkdir(parents=True, exist_ok=True)
        self.events_path.write_text("", encoding="utf-8")
        self.status = "running"
        self.started_at = now_iso()
        self.updated_at = self.started_at
        self.write_event("pipeline_started", status=self.status, mode=self.mode, task_id=self.task_id)
        self.write()

    def start_step(self, name: str) -> None:
        step = self._step(name)
        step.status = "running"
        step.started_at = now_iso()
        step.finished_at = None
        step.duration_ms = None
        self.updated_at = step.started_at
        self.write_event("step_started", step=name, status=step.status)
        self.write()

    def finish_step(
        self,
        name: str,
        status: StepStatus,
        *,
        summary: str = "",
        output_paths: dict[str, str] | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if status not in STEP_STATUSES:
            raise ValueError(f"unknown step status: {status}")
        step = self._step(name)
        step.status = status
        step.finished_at = now_iso()
        step.summary = summary
        if output_paths is not None:
            step.output_paths = {key: str(value) for key, value in output_paths.items()}
        if warnings is not None:
            step.warnings = list(warnings)
        if errors is not None:
            step.errors = list(errors)
        if metadata is not None:
            step.metadata = metadata
        if step.started_at:
            start = datetime.fromisoformat(step.started_at)
            finish = datetime.fromisoformat(step.finished_at)
            step.duration_ms = int((finish - start).total_seconds() * 1000)
        self.updated_at = step.finished_at
        self.warnings.extend(step.warnings)
        self.errors.extend(step.errors)
        self.write_event(
            "step_finished",
            step=name,
            status=status,
            summary=summary,
            warnings=step.warnings,
            errors=step.errors,
            metadata=step.metadata,
        )
        self.write()

    def block_remaining(self, after_step: str, reason: str) -> None:
        mark = False
        for name, step in self.steps.items():
            if mark and step.status == "pending":
                step.status = "blocked"
                step.summary = reason
            if name == after_step:
                mark = True
        self.write_event("pipeline_blocked", step=after_step, reason=reason)
        self.write()

    def complete(self, status: RunStatus | None = None) -> None:
        if status is None:
            statuses = [step.status for step in self.steps.values()]
            if "failed" in statuses:
                status = "failed"
            elif "waiting_review" in statuses:
                status = "waiting_review"
            elif "blocked" in statuses:
                status = "blocked"
            elif "skipped" in statuses:
                status = "partial_success"
            else:
                status = "success"
        self.status = status
        self.finished_at = now_iso()
        self.updated_at = self.finished_at
        self.write_event("pipeline_finished", status=self.status)
        self.write()

    def write(self) -> None:
        self.runtime_state_dir.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        tmp_path = self.state_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.state_path)

    def write_event(self, event: str, **fields: Any) -> None:
        self.runtime_state_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "time": now_iso(),
            "run_id": self.run_id,
            "event": event,
            **fields,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "overall_status": self.status,
            "mode": self.mode,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "steps": [step.to_dict() for step in self.steps.values()],
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": self.metadata,
            "image_provenance": self.metadata.get("image_provenance", {}),
            "runtime_state_dir": str(self.runtime_state_dir),
            "events_path": str(self.events_path),
        }

    def _step(self, name: str) -> StepRecord:
        try:
            return self.steps[name]
        except KeyError as exc:
            raise KeyError(f"unknown pipeline step: {name}") from exc


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
