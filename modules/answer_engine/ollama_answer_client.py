from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def call_ollama_answerer(
    *,
    endpoint: str,
    model: str,
    prompt: str,
    timeout_seconds: int = 90,
    num_predict: int = 512,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_predict": num_predict,
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(getattr(exc, "reason", str(exc))) from exc
    text = str(data.get("response") or "").strip()
    if not text:
        raise RuntimeError("Ollama returned an empty answer response.")
    return text


def extract_json_object(raw_response: str) -> dict[str, Any]:
    text = raw_response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Ollama answer response must be a JSON object.")
    return parsed
