from __future__ import annotations

from copy import deepcopy
from typing import Any


def merge_contexts(*contexts: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for context in contexts:
        merged = _merge_two(merged, context)
    return merged


def _merge_two(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_two(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = _merge_lists(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _merge_lists(left: list[Any], right: list[Any]) -> list[Any]:
    merged = deepcopy(left)
    for item in right:
        if item not in merged:
            merged.append(deepcopy(item))
    return merged
