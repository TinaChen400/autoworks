from __future__ import annotations

from typing import Any

from PIL import Image

from modules.perception_indexer.schema import BBox, IdGenerator, TextBlock, normalize_bbox


def run_ocr(
    image: Image.Image,
    backend: str,
    ids: IdGenerator,
    warnings: list[str],
) -> list[TextBlock]:
    if backend == "disabled":
        return []
    if backend == "tesseract":
        return _run_tesseract(image, ids, warnings)
    if backend == "rapidocr":
        return _run_rapidocr(image, ids, warnings)
    warnings.append(f"Unsupported OCR backend '{backend}', continuing without OCR.")
    return []


def _run_tesseract(image: Image.Image, ids: IdGenerator, warnings: list[str]) -> list[TextBlock]:
    try:
        import pytesseract
    except ImportError:
        warnings.append("OCR backend tesseract unavailable: pytesseract is not installed.")
        return []
    try:
        data: dict[str, Any] = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:
        warnings.append(f"OCR backend tesseract failed: {exc}")
        return []

    blocks: list[TextBlock] = []
    for index, text in enumerate(data.get("text", [])):
        cleaned = str(text).strip()
        if not cleaned:
            continue
        confidence = _to_confidence(data.get("conf", ["0"])[index])
        x = int(data.get("left", [0])[index])
        y = int(data.get("top", [0])[index])
        width = int(data.get("width", [0])[index])
        height = int(data.get("height", [0])[index])
        bbox = {"x": x, "y": y, "width": width, "height": height}
        blocks.append(
            TextBlock(
                text_id=ids.next_text(),
                text=cleaned,
                bbox_raw=bbox,
                bbox_norm=normalize_bbox(BBox(x=x, y=y, width=width, height=height), image.width, image.height),
                confidence=confidence,
                source="tesseract",
            )
        )
    return blocks


def _run_rapidocr(image: Image.Image, ids: IdGenerator, warnings: list[str]) -> list[TextBlock]:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        warnings.append("OCR backend rapidocr unavailable: rapidocr_onnxruntime is not installed.")
        return []
    try:
        import numpy as np
    except ImportError:
        warnings.append("OCR backend rapidocr unavailable: numpy is not installed.")
        return []
    try:
        engine = RapidOCR()
        result, _elapsed = engine(np.array(image))
    except Exception as exc:
        warnings.append(f"OCR backend rapidocr failed: {exc}")
        return []
    blocks: list[TextBlock] = []
    for item in result or []:
        points, text, confidence = item
        xs = [int(point[0]) for point in points]
        ys = [int(point[1]) for point in points]
        x = min(xs)
        y = min(ys)
        width = max(xs) - x
        height = max(ys) - y
        bbox = {"x": x, "y": y, "width": width, "height": height}
        blocks.append(
            TextBlock(
                text_id=ids.next_text(),
                text=str(text),
                bbox_raw=bbox,
                bbox_norm={
                    "x": round(x / max(1, image.width), 6),
                    "y": round(y / max(1, image.height), 6),
                    "width": round(width / max(1, image.width), 6),
                    "height": round(height / max(1, image.height), 6),
                },
                confidence=float(confidence),
                source="rapidocr",
            )
        )
    return blocks


def _to_confidence(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric < 0:
        return 0.0
    return round(min(1.0, numeric / 100), 4)
