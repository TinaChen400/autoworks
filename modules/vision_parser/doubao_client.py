from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from modules.vision_parser.image_payload import image_to_data_url
from modules.vision_parser.schema import sample_parsed_page

DEFAULT_CONFIG_PATH = Path("config/vision_model.json")
DEFAULT_SECRETS_PATH = Path("config/secrets.json")
ARK_CHAT_COMPLETIONS_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


class VisionModelError(RuntimeError):
    pass


def load_model_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        return {
            "provider": "doubao",
            "model_name": "doubao-seed-1.8-vision",
            "mode": "fake",
            "timeout_seconds": 60,
            "temperature": 0.1,
            "response_format": "json",
            "secrets_file": str(DEFAULT_SECRETS_PATH),
        }
    with config_path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def mask_api_key(value: str) -> str:
    if not value:
        return ""
    suffix = value[-4:] if len(value) >= 4 else value
    prefix = value[:3] if value.startswith("sk-") else ""
    return f"{prefix}****{suffix}"


def load_secrets(path: str | Path = DEFAULT_SECRETS_PATH) -> dict[str, str]:
    secrets_path = Path(path)
    if not secrets_path.exists():
        raise VisionModelError(
            f"Missing Doubao secrets file: {secrets_path}. Create config/secrets.json first."
        )
    with secrets_path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    endpoint_id = str(data.get("doubao_endpoint_id", "")).strip()
    api_key = str(data.get("ark_api_key", "")).strip()
    if not endpoint_id:
        raise VisionModelError("Missing doubao_endpoint_id in config/secrets.json.")
    if not api_key:
        raise VisionModelError("Missing ark_api_key in config/secrets.json.")
    return {"doubao_endpoint_id": endpoint_id, "ark_api_key": api_key}


def build_doubao_payload(
    endpoint_id: str,
    prompt: str,
    image_path: str | Path,
    temperature: float,
) -> dict[str, Any]:
    return {
        "model": endpoint_id,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You parse screenshots into structured JSON only. "
                    "You never answer questions, click, call OCR, or take actions."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                ],
            },
        ],
    }


def call_doubao(
    prompt: str,
    image_path: str | Path,
    config: dict[str, Any] | None = None,
) -> str:
    model_config = config or load_model_config()
    secrets = load_secrets(model_config.get("secrets_file", DEFAULT_SECRETS_PATH))
    payload = build_doubao_payload(
        endpoint_id=secrets["doubao_endpoint_id"],
        prompt=prompt,
        image_path=image_path,
        temperature=float(model_config.get("temperature", 0.1)),
    )
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        ARK_CHAT_COMPLETIONS_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {secrets['ark_api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=int(model_config.get("timeout_seconds", 60)),
        ) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise VisionModelError(f"Doubao API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise VisionModelError(f"Doubao API request failed: {exc.reason}") from exc

    try:
        return str(response_data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise VisionModelError("Doubao API response did not contain message content.") from exc


def call_vision_model(
    mode: str,
    prompt: str,
    image_path: str | Path,
    task_id: str,
    config: dict[str, Any] | None = None,
    parser_type: str = "general",
) -> str:
    if mode == "fake":
        if parser_type == "scene_scan":
            return json.dumps(
                {
                    "detected_page_type": "unknown",
                    "layout_type": "unknown",
                    "detected_interaction_types": [],
                    "recommended_parser": "general",
                    "confidence": 0.1,
                    "reason": "Fake mode returns a schema-valid placeholder scene scan only.",
                },
                ensure_ascii=False,
            )
        return json.dumps(sample_parsed_page(task_id), ensure_ascii=False)
    if mode == "doubao":
        return call_doubao(prompt, image_path, config)
    raise VisionModelError(f"Unsupported vision parser mode: {mode}")
