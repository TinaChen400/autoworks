from __future__ import annotations

import json
from pathlib import Path


ROOT = Path.cwd()
CONFIG_DIR = ROOT / "config"


EMPTY_PROFILE = {
    "known_accounts_or_experience": [],
    "known_tools": [],
    "known_languages": [],
    "known_devices": [],
    "known_locations": [],
    "known_demographics": [],
    "notes": [],
}


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_user_profile() -> tuple[dict, bool, dict | None]:
    example = _read_json(CONFIG_DIR / "user_profile.example.json")
    profile = _read_json(CONFIG_DIR / "user_profile.json")
    if profile is None:
        return dict(EMPTY_PROFILE), False, example
    merged = dict(EMPTY_PROFILE)
    merged.update(profile)
    return merged, True, example
