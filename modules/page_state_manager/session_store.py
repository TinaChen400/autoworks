from __future__ import annotations

import json
from pathlib import Path

from .schema import new_session


ROOT = Path.cwd()
SESSION_PATH = ROOT / "runtime_state" / "latest_survey_session.json"


def load_session(task_id: str = "") -> dict:
    if SESSION_PATH.exists():
        with SESSION_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return new_session(task_id)


def save_session(session: dict) -> Path:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SESSION_PATH.open("w", encoding="utf-8") as handle:
        json.dump(session, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return SESSION_PATH
