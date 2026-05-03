from __future__ import annotations

import re


SYNONYM_GROUPS = [
    {"amazon seller central", "seller central", "amazon seller"},
    {"vendor central", "amazon vendor central"},
    {"retail central", "retailcenter"},
    {"amazon central", "amazoncentral"},
    {"supplier central", "suppliercentral"},
]

VAGUE_TERMS = {"central", "seller", "amazon", "account", "accounts", "experience", "tool", "tools"}


def norm(text: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def evidence_values(profile: dict, session: dict | None) -> list[dict]:
    values = []
    for key, items in (profile or {}).items():
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item.strip():
                    values.append({"source": f"user_profile.{key}", "value": item})
                elif isinstance(item, dict) and item.get("value"):
                    values.append({"source": f"user_profile.{key}", "value": str(item["value"])})
    for fact in (session or {}).get("consistency_memory", []):
        if fact.get("value"):
            values.append({"source": "session_memory", "value": str(fact["value"]), "fact_key": fact.get("fact_key", "")})
    return values


def _synonym_group(value: str) -> set[str] | None:
    value_norm = norm(value)
    value_compact = compact(value)
    for group in SYNONYM_GROUPS:
        if value_norm in group or value_compact in {compact(item) for item in group}:
            return group
    return None


def _direct_match(option_text: str, evidence_text: str) -> bool:
    option_norm = norm(option_text)
    evidence_norm = norm(evidence_text)
    if not option_norm or option_norm in VAGUE_TERMS:
        return False
    if len(option_norm) < 4:
        return False
    option_compact = compact(option_norm)
    evidence_compact = compact(evidence_norm)
    return option_compact == evidence_compact or option_compact in evidence_compact or evidence_compact in option_compact


def option_is_supported(option: dict, profile: dict, session: dict | None) -> tuple[bool, list[dict]]:
    option_text = option.get("text", "")
    option_group = _synonym_group(option_text)
    matches = []
    for evidence in evidence_values(profile, session):
        value = evidence["value"]
        value_group = _synonym_group(value)
        if option_group and value_group and option_group == value_group:
            matches.append({**evidence, "matched_text": option_text, "match_type": "synonym"})
        elif _direct_match(option_text, value):
            matches.append({**evidence, "matched_text": option_text, "match_type": "direct"})
    return bool(matches), matches


def supported_options(options: list[dict], profile: dict, session: dict | None) -> dict[str, list[dict]]:
    supported: dict[str, list[dict]] = {}
    for option in options:
        ok, evidence = option_is_supported(option, profile, session)
        if ok:
            supported[option.get("option_id", "")] = evidence
    return supported


def is_all_of_the_above(option: dict) -> bool:
    return "all of the above" in norm(option.get("text", ""))
