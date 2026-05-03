from __future__ import annotations

import re


NEGATIVE_VALUES = {"no", "none", "false", "0", "not applicable", "n/a"}
POSITIVE_VALUES = {"yes", "true", "1"}


def normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def normalize_value(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def values_conflict(left: str, right: str) -> bool:
    left_norm = normalize_value(left)
    right_norm = normalize_value(right)
    if not left_norm or not right_norm or left_norm == right_norm:
        return False
    if left_norm in NEGATIVE_VALUES and right_norm not in NEGATIVE_VALUES:
        return True
    if right_norm in NEGATIVE_VALUES and left_norm not in NEGATIVE_VALUES:
        return True
    if left_norm in POSITIVE_VALUES and right_norm in NEGATIVE_VALUES:
        return True
    if right_norm in POSITIVE_VALUES and left_norm in NEGATIVE_VALUES:
        return True
    return False


def detect_conflicting_answer(consistency_memory: list[dict], fact_key: str, proposed_value: str) -> list[dict]:
    key = normalize_key(fact_key)
    conflicts = []
    for fact in consistency_memory:
        if normalize_key(fact.get("fact_key", "")) == key and values_conflict(fact.get("value", ""), proposed_value):
            conflicts.append(
                {
                    "fact_key": fact.get("fact_key", ""),
                    "previous_value": fact.get("value", ""),
                    "proposed_value": proposed_value,
                    "source": fact.get("source", ""),
                }
            )
    return conflicts


def detect_decision_contradictions(session: dict, decision: dict | None) -> list[dict]:
    if not decision:
        return []
    conflicts = []
    memory = session.get("consistency_memory", [])
    for qd in decision.get("question_decisions", []):
        value = qd.get("recommended_text_answer") or ", ".join(qd.get("recommended_option_ids", []))
        conflicts.extend(detect_conflicting_answer(memory, qd.get("question_text", ""), value))
    return conflicts
