from __future__ import annotations

import hashlib
import json
import ctypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mss
from PIL import Image

from modules.window_capture.window_controller import (
    WindowPlacement,
    get_window_placement,
    is_valid_window,
)


RUNTIME_DIR = Path("runtime_state")
CAPTURE_PROVENANCE_PATH = RUNTIME_DIR / "latest_capture_provenance.json"
AFTER_CLICK_CAPTURE_PATH = RUNTIME_DIR / "latest_capture_after_click.png"
AFTER_CLICK_PROVENANCE_PATH = RUNTIME_DIR / "latest_capture_after_click_provenance.json"


def _set_process_dpi_aware() -> None:
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        return


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing.")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _image_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _placement_from_bbox(bbox: dict[str, Any]) -> WindowPlacement:
    return WindowPlacement(
        left=int(bbox["left"]),
        top=int(bbox["top"]),
        width=int(bbox["width"]),
        height=int(bbox["height"]),
    )


def _capture_region_from_provenance(provenance: dict[str, Any]) -> WindowPlacement:
    bbox = provenance.get("locked_region") or provenance.get("bbox")
    if not isinstance(bbox, dict):
        raise ValueError("latest_capture_provenance.json is missing locked_region/bbox.")
    region = _placement_from_bbox(bbox)
    if region.width <= 0 or region.height <= 0:
        raise ValueError("latest_capture_provenance.json has an invalid capture region.")
    return region


def _validate_target_has_not_moved(provenance: dict[str, Any], region: WindowPlacement) -> None:
    hwnd = provenance.get("target_window_handle")
    if hwnd in {None, ""}:
        return
    try:
        hwnd_int = int(hwnd)
    except (TypeError, ValueError):
        raise RuntimeError("latest_capture_provenance.json has an invalid target_window_handle.")
    if not is_valid_window(hwnd_int):
        raise RuntimeError("locked target window is no longer valid.")
    current = get_window_placement(hwnd_int)
    if current != region:
        raise RuntimeError(
            "locked target moved or resized; refresh panel capture before closed-loop verify. "
            f"expected={region}, current={current}."
        )


def capture_after_click(
    *,
    runtime_state_dir: str | Path = RUNTIME_DIR,
    output_path: str | Path | None = None,
    provenance_path: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    _set_process_dpi_aware()
    runtime = Path(runtime_state_dir)
    source_provenance_path = runtime / CAPTURE_PROVENANCE_PATH.name
    source_provenance = _read_json(source_provenance_path)
    region = _capture_region_from_provenance(source_provenance)
    _validate_target_has_not_moved(source_provenance, region)

    output = (
        Path(output_path)
        if output_path is not None
        else runtime / AFTER_CLICK_CAPTURE_PATH.name
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    monitor = {
        "left": region.left,
        "top": region.top,
        "width": region.width,
        "height": region.height,
    }
    with mss.mss() as sct:
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        image.save(output)

    with Image.open(output) as image:
        image_width, image_height = image.size

    created_at = datetime.now(timezone.utc).isoformat()
    provenance = {
        "capture_source": "action_executor_after_click",
        "source_capture_provenance_path": str(source_provenance_path),
        "target_locked": bool(source_provenance.get("target_locked")),
        "target_window_title": source_provenance.get("target_window_title", ""),
        "target_window_handle": source_provenance.get("target_window_handle"),
        "locked_region": {
            "left": region.left,
            "top": region.top,
            "width": region.width,
            "height": region.height,
        },
        "bbox": {
            "left": region.left,
            "top": region.top,
            "width": region.width,
            "height": region.height,
        },
        "dpi_scale": source_provenance.get("dpi_scale"),
        "screenshot_path": str(output),
        "screenshot_mtime": datetime.fromtimestamp(output.stat().st_mtime).isoformat(),
        "image_width": image_width,
        "image_height": image_height,
        "image_hash": _image_hash(output),
        "created_at": created_at,
    }
    destination = (
        Path(provenance_path)
        if provenance_path is not None
        else runtime / AFTER_CLICK_PROVENANCE_PATH.name
    )
    _write_json(destination, provenance)
    return output, provenance
