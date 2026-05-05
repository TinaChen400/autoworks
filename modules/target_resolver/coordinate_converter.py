from __future__ import annotations

from typing import Any


def _number(data: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = data.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def norm_to_raw(point_norm: dict[str, Any], runtime_context: dict[str, Any]) -> dict[str, int]:
    model_region = runtime_context.get("model_input_region") or {}
    raw_x = _number(model_region, "x") + _number(point_norm, "x") * _number(model_region, "width", 1)
    raw_y = _number(model_region, "y") + _number(point_norm, "y") * _number(model_region, "height", 1)
    return {"x": int(round(raw_x)), "y": int(round(raw_y))}


def raw_to_screen(point_raw: dict[str, Any], runtime_context: dict[str, Any]) -> dict[str, int]:
    anchor = runtime_context.get("anchor_frame") or {}
    screen_x = _number(anchor, "x") + _number(point_raw, "x")
    screen_y = _number(anchor, "y") + _number(point_raw, "y")
    return {"x": int(round(screen_x)), "y": int(round(screen_y))}


def norm_to_screen(point_norm: dict[str, Any], runtime_context: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    raw = norm_to_raw(point_norm, runtime_context)
    return raw, raw_to_screen(raw, runtime_context)

