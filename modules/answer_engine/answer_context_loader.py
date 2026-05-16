from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path.cwd()
ANSWER_NOTES_PATH = ROOT / "knowledge_base" / "answer_notes.json"
MAX_NOTES = 3


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").casefold())
        if len(token) >= 3
    }


def _load_notes(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or ANSWER_NOTES_PATH
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []

    notes = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        note_id = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        tags = item.get("tags") or []
        if not note_id or not text or not isinstance(tags, list):
            continue
        notes.append(
            {
                "id": note_id,
                "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
                "text": text,
            }
        )
    return notes


def load_relevant_answer_notes(question: dict[str, Any], limit: int = MAX_NOTES) -> list[dict[str, Any]]:
    query_parts = [str((question.get("question_stem") or {}).get("text") or "")]
    query_parts.extend(str(item.get("text") or "") for item in question.get("instructions", []) or [])
    query_parts.extend(str(option.get("text") or "") for option in question.get("answer_options", []) or [])
    query_text = " ".join(query_parts)
    query_tokens = _tokens(query_text)
    if not query_tokens:
        return []

    scored = []
    for note in _load_notes():
        tag_text = " ".join(note["tags"])
        note_tokens = _tokens(f"{tag_text} {note['text']}")
        overlap = query_tokens & note_tokens
        tag_overlap = query_tokens & _tokens(tag_text)
        score = len(overlap) + len(tag_overlap)
        if score > 0:
            scored.append((score, note["id"], note))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [note for _score, _note_id, note in scored[:limit]]
