from __future__ import annotations

import re
from collections import Counter
from typing import Any

from modules.perception_indexer.schema import TextBlock

SECTION_TITLES = {
    "licenses & credentials": ("license_section", "license"),
    "licenses&credentials": ("license_section", "license"),
    "licences & credentials": ("license_section", "license"),
    "licences&credentials": ("license_section", "license"),
    "account": ("account_section", "account"),
    "contact": ("contact_section", "contact"),
    "notification preferences": ("notification_section", "notification"),
    "security": ("security_section", "security"),
}

INSTRUCTION_PATTERNS = (
    "professional licenses",
    "educational verification",
    "personal and contact information",
    "choose how we let you know",
    "protect your account",
    "protecti your account",
    "two-factor authentication",
)

FIELD_LABELS = {
    "first name",
    "last",
    "username",
    "worker id",
    "referral code",
    "email",
    "phone number",
    "paypal email",
    "email notifications",
}

ACTION_TEXTS = {
    "+ add a professional license",
    "add a professional license",
    "change email",
    "add and verify phone number",
    "add paypal email",
    "save changes",
    "savechanges",
}

BROWSER_HINTS = (
    "chrome",
    "http",
    "https",
    "www.",
    "extensions",
    "bookmarks",
    "search",
)


def classify_text_blocks(text_blocks: list[TextBlock]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for block in text_blocks:
        role, semantic = classify_text(block.text)
        block.metadata["text_role"] = role
        if semantic:
            block.metadata["semantic_region_hint"] = semantic
        counts[role] += 1
    return {
        "counts": dict(counts),
        "section_titles": [
            {"text_id": block.text_id, "text": block.text, "semantic": block.metadata.get("semantic_region_hint", "")}
            for block in text_blocks
            if block.metadata.get("text_role") == "section_title"
        ],
    }


def removed_false_card_candidates_from_text(text_blocks: list[TextBlock]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for block in text_blocks:
        role = str(block.metadata.get("text_role", "unknown"))
        normalized = normalize_text(block.text)
        if role == "section_title":
            continue
        reason = ""
        if role in {"instruction_text", "field_label", "action_link", "button_text"} and any(
            needle in normalized
            for needle in (
                "account",
                "contact",
                "notification",
                "security",
                "license",
                "email",
                "save",
            )
        ):
            reason = f"text_classified_as_{role}"
        if reason:
            records.append(
                {
                    "text_id": block.text_id,
                    "text": block.text,
                    "text_role": role,
                    "reason": reason,
                    "bbox_raw": block.bbox_raw,
                }
            )
    return records


def classify_text(text: str) -> tuple[str, str]:
    normalized = normalize_text(text)
    if not normalized:
        return "unknown", ""
    if normalized in SECTION_TITLES:
        _region_type, semantic = SECTION_TITLES[normalized]
        return "section_title", semantic
    compact = normalized.replace(" ", "")
    if normalized in ACTION_TEXTS or compact in ACTION_TEXTS:
        return "button_text" if "save" in normalized or "change" in normalized else "action_link", ""
    if normalized in FIELD_LABELS:
        return "field_label", ""
    if any(pattern in normalized for pattern in INSTRUCTION_PATTERNS):
        return "instruction_text", ""
    if any(pattern in normalized for pattern in BROWSER_HINTS):
        return "browser_text", ""
    if _looks_like_field_value(normalized):
        return "field_value", ""
    return "unknown", ""


def section_region_type_for_text(text: str) -> tuple[str, str]:
    return SECTION_TITLES.get(normalize_text(text), ("", ""))


def normalize_text(text: str) -> str:
    lowered = text.lower().replace("|", " ").replace("：", ":")
    lowered = lowered.replace("＆", "&")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip(" .:-")


def _looks_like_field_value(text: str) -> bool:
    if "@" in text:
        return True
    if re.fullmatch(r"[a-z0-9_.-]{3,}", text) and text not in FIELD_LABELS:
        return True
    return False
