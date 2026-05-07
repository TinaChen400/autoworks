from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mss
from PIL import Image

from modules.window_capture.capture import PROJECT_ROOT, ensure_anchor_profile
from modules.window_capture.target_profile import (
    describe_profile_match,
    find_matching_window,
    load_target_profile,
)
from modules.window_capture.window_controller import (
    WindowPlacement,
    get_window_placement,
    is_valid_window,
    restore_if_moved_or_resized,
    snap_to_anchor,
)
from modules.window_capture.window_locator import WindowInfo, list_visible_windows


RUNTIME_STATE_DIR = PROJECT_ROOT / "runtime_state"
TARGET_CANDIDATES_PATH = RUNTIME_STATE_DIR / "latest_target_candidates.json"
LOCKED_TARGET_PATH = RUNTIME_STATE_DIR / "latest_locked_target.json"
CAPTURE_PROVENANCE_PATH = RUNTIME_STATE_DIR / "latest_capture_provenance.json"
NO_LOCKED_TARGET_MESSAGE = (
    "No locked target window. Please snap and lock the KVM/remote window before running preview."
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def placement_to_dict(placement: WindowPlacement) -> dict[str, int]:
    return {
        "left": placement.left,
        "top": placement.top,
        "width": placement.width,
        "height": placement.height,
    }


def placement_from_dict(payload: dict[str, Any]) -> WindowPlacement:
    return WindowPlacement(
        left=int(payload["left"]),
        top=int(payload["top"]),
        width=int(payload["width"]),
        height=int(payload["height"]),
    )


def window_to_dict(window: WindowInfo) -> dict[str, Any]:
    return {
        "hwnd": window.hwnd,
        "title": window.title,
        "class_name": window.class_name,
        "process_id": window.process_id,
        "bbox": placement_to_dict(window.box),
    }


def snap_targets(runtime_state_dir: Path = RUNTIME_STATE_DIR) -> dict[str, Any]:
    try:
        windows = list_visible_windows(exclude_foreground=False)
        payload = {
            "ok": True,
            "created_at": utc_now_iso(),
            "candidate_count": len(windows),
            "candidates": [window_to_dict(window) for window in windows],
            "errors": [],
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "created_at": utc_now_iso(),
            "candidate_count": 0,
            "candidates": [],
            "errors": [str(exc)],
        }
    write_json(runtime_state_dir / TARGET_CANDIDATES_PATH.name, payload)
    return payload


def lock_saved_target(runtime_state_dir: Path = RUNTIME_STATE_DIR) -> dict[str, Any]:
    windows = list_visible_windows(exclude_foreground=False)
    profile = load_target_profile()
    matched = find_matching_window(windows, profile)
    if matched is None:
        payload = {
            "target_locked": False,
            "created_at": utc_now_iso(),
            "blocked_reason": describe_profile_match(windows, profile),
            "errors": [NO_LOCKED_TARGET_MESSAGE],
        }
        write_json(runtime_state_dir / LOCKED_TARGET_PATH.name, payload)
        return payload

    anchor = ensure_anchor_profile()
    locked_region = snap_to_anchor(matched.hwnd, anchor)
    payload = {
        "target_locked": True,
        "created_at": utc_now_iso(),
        "capture_source": "locked_target",
        "target_window_title": matched.title,
        "target_window_handle": matched.hwnd,
        "target_window_class": matched.class_name,
        "locked_region": placement_to_dict(locked_region),
        "bbox": placement_to_dict(locked_region),
        "dpi_scale": anchor.get("scale"),
        "errors": [],
    }
    write_json(runtime_state_dir / LOCKED_TARGET_PATH.name, payload)
    return payload


def lock_target_by_handle(
    hwnd: int,
    runtime_state_dir: Path = RUNTIME_STATE_DIR,
) -> dict[str, Any]:
    windows = list_visible_windows(exclude_foreground=False)
    matched = next((window for window in windows if window.hwnd == int(hwnd)), None)
    if matched is None:
        payload = {
            "target_locked": False,
            "created_at": utc_now_iso(),
            "blocked_reason": f"Selected target hwnd={hwnd} is not visible.",
            "errors": [NO_LOCKED_TARGET_MESSAGE],
        }
        write_json(runtime_state_dir / LOCKED_TARGET_PATH.name, payload)
        return payload

    anchor = ensure_anchor_profile()
    locked_region = snap_to_anchor(matched.hwnd, anchor)
    payload = {
        "target_locked": True,
        "created_at": utc_now_iso(),
        "capture_source": "locked_target",
        "target_window_title": matched.title,
        "target_window_handle": matched.hwnd,
        "target_window_class": matched.class_name,
        "locked_region": placement_to_dict(locked_region),
        "bbox": placement_to_dict(locked_region),
        "dpi_scale": anchor.get("scale"),
        "errors": [],
    }
    write_json(runtime_state_dir / LOCKED_TARGET_PATH.name, payload)
    return payload


def validate_locked_target(runtime_state_dir: Path = RUNTIME_STATE_DIR) -> tuple[bool, dict[str, Any], str]:
    payload = read_json(runtime_state_dir / LOCKED_TARGET_PATH.name)
    if payload.get("target_locked") is not True:
        return False, payload, NO_LOCKED_TARGET_MESSAGE

    hwnd = int(payload.get("target_window_handle") or 0)
    if not is_valid_window(hwnd):
        return False, payload, NO_LOCKED_TARGET_MESSAGE

    region_payload = payload.get("locked_region") or payload.get("bbox") or {}
    try:
        locked_region = placement_from_dict(region_payload)
    except (KeyError, TypeError, ValueError):
        return False, payload, NO_LOCKED_TARGET_MESSAGE

    restore_if_moved_or_resized(hwnd, locked_region)
    current = get_window_placement(hwnd)
    if current != locked_region:
        return False, payload, NO_LOCKED_TARGET_MESSAGE

    return True, payload, ""


def image_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_locked_target(
    *,
    runtime_state_dir: Path = RUNTIME_STATE_DIR,
    output_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    ok, target, reason = validate_locked_target(runtime_state_dir)
    if not ok:
        raise RuntimeError(reason)

    output = output_path or runtime_state_dir / "latest_capture.png"
    region = placement_from_dict(target.get("locked_region") or target.get("bbox") or {})
    monitor = {
        "left": region.left,
        "top": region.top,
        "width": region.width,
        "height": region.height,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        image.save(output)

    with Image.open(output) as image:
        image_width, image_height = image.size

    provenance = {
        "capture_source": "locked_target",
        "target_locked": True,
        "target_window_title": target.get("target_window_title", ""),
        "target_window_handle": target.get("target_window_handle"),
        "locked_region": placement_to_dict(region),
        "bbox": placement_to_dict(region),
        "dpi_scale": target.get("dpi_scale"),
        "screenshot_path": str(output),
        "screenshot_mtime": datetime.fromtimestamp(output.stat().st_mtime).isoformat(),
        "image_width": image_width,
        "image_height": image_height,
        "image_hash": image_hash(output),
        "created_at": utc_now_iso(),
    }
    write_json(runtime_state_dir / CAPTURE_PROVENANCE_PATH.name, provenance)
    return output, provenance
