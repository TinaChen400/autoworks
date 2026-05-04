from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from modules.window_capture.capture import PROJECT_ROOT
from modules.window_capture.window_locator import WindowInfo


DEFAULT_TARGET_PATH = PROJECT_ROOT / "config" / "target_profile.json"


class TargetProfile(TypedDict):
    title: str
    class_name: str


def load_target_profile(path: Path = DEFAULT_TARGET_PATH) -> TargetProfile | None:
    if not path.exists():
        return None

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    title = str(data.get("title", "")).strip()
    class_name = str(data.get("class_name", "")).strip()
    if not title or not class_name:
        return None

    return {"title": title, "class_name": class_name}


def save_target_profile(window: WindowInfo, path: Path = DEFAULT_TARGET_PATH) -> TargetProfile:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {"title": window.title, "class_name": window.class_name}
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return profile


def find_matching_window(
    windows: list[WindowInfo],
    profile: TargetProfile | None,
) -> WindowInfo | None:
    if profile is None:
        return None

    exact = [
        window
        for window in windows
        if window.title == profile["title"] and window.class_name == profile["class_name"]
    ]
    if len(exact) == 1:
        return exact[0]

    same_class = [window for window in windows if window.class_name == profile["class_name"]]
    if len(same_class) == 1:
        return same_class[0]

    return None


def describe_profile_match(
    windows: list[WindowInfo],
    profile: TargetProfile | None,
) -> str:
    if profile is None:
        return "No saved target profile. Select a window, then save it with Anchor Origin first."

    exact = [
        window
        for window in windows
        if window.title == profile["title"] and window.class_name == profile["class_name"]
    ]
    if len(exact) == 1:
        return "Saved target matched exactly."
    if len(exact) > 1:
        return (
            "Saved target is ambiguous: "
            f"{len(exact)} windows match title={profile['title']} and class={profile['class_name']}."
        )

    same_class = [window for window in windows if window.class_name == profile["class_name"]]
    if len(same_class) == 1:
        return "Saved target matched by class_name."
    if len(same_class) > 1:
        return (
            "Saved target is ambiguous: "
            f"{len(same_class)} windows match class={profile['class_name']}."
        )

    return (
        "Saved target not found: "
        f"title={profile['title']}, class={profile['class_name']} is not visible."
    )
