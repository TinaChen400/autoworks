from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from modules.perception_indexer.annotator import save_annotated_crop, save_annotated_overview
from modules.perception_indexer.card_detector import detect_card_regions, detect_viewport_regions
from modules.perception_indexer.crop_quality import compute_crop_quality, expand_and_clamp_crop
from modules.perception_indexer.element_detector import detect_elements
from modules.perception_indexer.detectors.runner import (
    detector_scores,
    implemented_detectors,
    pending_detectors,
    possible_page_types_from_scores,
    run_detectors,
)
from modules.perception_indexer.grouping import (
    attach_text_to_regions,
    build_element_region_relationships,
    build_region_relationships,
    infer_layout_hints,
    assign_elements_to_smallest_regions,
)
from modules.perception_indexer.image_loader import (
    RUNTIME_CONTEXT_PATH,
    get_model_input_region,
    load_runtime_context,
    load_screenshot,
)
from modules.perception_indexer.index_store import (
    ANNOTATED_OVERVIEW_PATH,
    CROPS_DIR,
    LAYOUT_INDEX_PATH,
    PERCEPTION_REPORT_PATH,
    load_config,
    save_layout_index,
    save_perception_report,
)
from modules.perception_indexer.ocr_layer import run_ocr
from modules.perception_indexer.region_detector import detect_regions
from modules.perception_indexer.schema import (
    BBox,
    IdGenerator,
    Relationship,
    bbox_from_dict,
    new_index_id,
    now_iso,
)
from modules.perception_indexer.text_association import associate_section_titles, associate_text
from modules.perception_indexer.text_classifier import (
    classify_text_blocks,
    removed_false_card_candidates_from_text,
)


def build_layout_index(ocr_backend: str | None = None) -> dict[str, Any]:
    config = load_config()
    backend = ocr_backend or str(config.get("ocr_backend", "disabled"))
    warnings: list[str] = []
    runtime_context = load_runtime_context()
    image, screenshot_path = load_screenshot(runtime_context)
    model_region = get_model_input_region(runtime_context, image)
    ids = IdGenerator()

    regions = detect_regions(image, model_region, ids)
    viewport_regions = detect_viewport_regions(image, model_region, ids, warnings)
    regions.extend(viewport_regions)
    web_viewport = next(region for region in viewport_regions if region.region_type_hint == "web_viewport")
    elements = detect_elements(
        image=image,
        regions=regions,
        ids=ids,
        min_area=int(config.get("min_element_area_px", 80)),
        max_area_ratio=float(config.get("max_element_area_ratio", 0.40)),
    )
    text_blocks = run_ocr(image, backend, ids, warnings)
    text_classification_summary = classify_text_blocks(text_blocks)
    rejected_text_card_candidates = removed_false_card_candidates_from_text(text_blocks)
    card_regions, removed_false_card_candidates = detect_card_regions(
        image,
        web_viewport,
        elements,
        text_blocks,
        ids,
        warnings,
    )
    removed_false_card_candidates = removed_false_card_candidates + rejected_text_card_candidates
    regions.extend(card_regions)

    assign_elements_to_smallest_regions(regions, elements)
    attach_text_to_regions(regions, text_blocks)
    relationships: list[Relationship] = []
    relationships.extend(build_region_relationships(regions, relationship_id=ids.next_relationship))
    relationships.extend(
        build_element_region_relationships(regions, elements, relationship_id=ids.next_relationship)
    )
    for text_block in text_blocks:
        if text_block.associated_region_id:
            relationships.append(
                Relationship(
                    relationship_id=ids.next_relationship(),
                    relationship_type="text_in_region",
                    source_id=text_block.text_id,
                    target_id=text_block.associated_region_id,
                    confidence=text_block.confidence,
                )
            )
    relationships.extend(associate_text(elements, text_blocks, relationship_id=ids.next_relationship))
    relationships.extend(
        associate_section_titles(regions, text_blocks, relationship_id=ids.next_relationship)
    )

    _write_region_crops(
        image=image,
        regions=regions,
        elements=elements,
        text_blocks=text_blocks,
        margin_percent=float(config.get("crop_margin_percent", 0.08)),
        min_margin_px=int(config.get("crop_margin_min_px", 40)),
    )
    save_annotated_overview(
        image=image,
        regions=regions,
        elements=elements,
        text_blocks=text_blocks,
        output_path=ANNOTATED_OVERVIEW_PATH,
        annotate_regions=bool(config.get("annotate_regions", True)),
        annotate_elements=bool(config.get("annotate_elements", True)),
        annotate_text_blocks=bool(config.get("annotate_text_blocks", True)),
        show_browser_elements=bool(config.get("show_browser_elements", False)),
        show_low_confidence_elements=bool(config.get("show_low_confidence_elements", False)),
        min_element_confidence_for_annotation=float(
            config.get("min_element_confidence_for_annotation", 0.35)
        ),
    )

    detector_results = run_detectors(regions, elements, text_blocks)
    layout_hints = infer_layout_hints(regions, elements)
    layout_hints.false_card_candidates_removed = removed_false_card_candidates
    layout_hints.detector_scores = detector_scores(detector_results)
    layout_hints.possible_page_types = possible_page_types_from_scores(detector_results)
    layout_index = {
        "index_id": new_index_id(),
        "source_image": str(screenshot_path),
        "runtime_context_path": str(RUNTIME_CONTEXT_PATH),
        "image_size": {"width": image.width, "height": image.height},
        "model_input_region": model_region.to_dict(),
        "full_screenshot": {"path": str(screenshot_path), "preserved": True},
        "annotated_overview": str(ANNOTATED_OVERVIEW_PATH),
        "regions": [region.to_dict() for region in regions],
        "elements": [element.to_dict() for element in elements],
        "text_blocks": [text_block.to_dict() for text_block in text_blocks],
        "relationships": [relationship.to_dict() for relationship in relationships],
        "layout_hints": layout_hints.to_dict(),
        "warnings": warnings,
        "created_at": now_iso(),
    }
    save_layout_index(layout_index)
    save_perception_report(
        {
            "layout_index": str(LAYOUT_INDEX_PATH),
            "annotated_overview": str(ANNOTATED_OVERVIEW_PATH),
            "regions": len(regions),
            "elements": len(elements),
            "text_blocks": len(text_blocks),
            "warnings": warnings,
            "ocr_backend": backend,
            "true_card_regions": [
                {
                    "region_id": region.region_id,
                    "region_type_hint": region.region_type_hint,
                    "semantic_region_hint": region.metadata.get("semantic_region_hint", ""),
                    "title_text": region.metadata.get("title_text", ""),
                    "crop_path": region.crop_path,
                    "annotated_crop_path": region.annotated_crop_path,
                }
                for region in regions
                if region.metadata.get("is_true_business_card")
                or region.metadata.get("source") == "element_vertical_clustering"
            ],
            "removed_false_card_candidates": removed_false_card_candidates,
            "region_tree": _build_region_tree(regions),
            "section_title_classification_summary": text_classification_summary,
            "element_assignment_summary": _build_element_assignment_summary(regions, elements),
            "implemented_detectors": implemented_detectors(detector_results),
            "pending_detectors": pending_detectors(detector_results),
            "detector_results": [result.to_dict() for result in detector_results],
            "created_at": layout_index["created_at"],
        }
    )
    return layout_index


def _write_region_crops(
    image,
    regions,
    elements,
    text_blocks,
    margin_percent: float,
    min_margin_px: int,
) -> None:
    CROPS_DIR.mkdir(parents=True, exist_ok=True)
    _clear_existing_crops()
    for region in regions:
        region_bbox = bbox_from_dict(region.bbox_raw)
        crop_bbox = expand_and_clamp_crop(
            region_bbox,
            image.width,
            image.height,
            margin_percent=margin_percent,
            min_margin_px=min_margin_px,
        )
        safe_hint = _region_filename_hint(region)
        crop_path = CROPS_DIR / f"{region.region_id}_{safe_hint}.png"
        annotated_crop_path = CROPS_DIR / f"{region.region_id}_{safe_hint}_annotated.png"
        crop = image.crop((crop_bbox.x, crop_bbox.y, crop_bbox.right, crop_bbox.bottom))
        crop.save(crop_path)
        save_annotated_crop(
            image=image,
            crop_bbox=crop_bbox,
            region=region,
            elements=elements,
            text_blocks=text_blocks,
            output_path=annotated_crop_path,
        )
        relevant_elements = [
            element for element in elements if element.region_id == region.region_id
        ]
        relevant_text = [
            text_block for text_block in text_blocks if text_block.associated_region_id == region.region_id
        ]
        quality = compute_crop_quality(
            crop_bbox=crop_bbox,
            region_bbox=region_bbox,
            image_width=image.width,
            image_height=image.height,
            elements=relevant_elements,
            text_blocks=relevant_text,
            is_card_region=bool(region.metadata.get("is_card_region")),
        )
        region.crop_path = str(crop_path)
        region.annotated_crop_path = str(annotated_crop_path)
        region.crop_quality = quality.to_dict()
        region.metadata["crop_bbox_raw"] = crop_bbox.to_dict()


def _safe_filename_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value)


def _clear_existing_crops() -> None:
    for path in CROPS_DIR.glob("R*.png"):
        if path.is_file():
            path.unlink()


def _region_filename_hint(region) -> str:
    semantic = region.metadata.get("semantic_region_hint", "")
    if semantic:
        return _safe_filename_part(f"card_{semantic}")
    return _safe_filename_part(region.region_type_hint)


def _build_region_tree(regions) -> list[dict[str, Any]]:
    by_parent: dict[str, list] = {}
    roots = []
    for region in regions:
        parent = region.metadata.get("parent_region_id", "")
        if parent:
            by_parent.setdefault(parent, []).append(region)
        else:
            roots.append(region)

    def node(region) -> dict[str, Any]:
        return {
            "region_id": region.region_id,
            "region_type_hint": region.region_type_hint,
            "semantic_region_hint": region.metadata.get("semantic_region_hint", ""),
            "element_ids": region.element_ids,
            "text_ids": region.text_ids,
            "children": [node(child) for child in by_parent.get(region.region_id, [])],
        }

    return [node(region) for region in roots]


def _build_element_assignment_summary(regions, elements) -> dict[str, Any]:
    region_type_by_id = {region.region_id: region.region_type_hint for region in regions}
    by_region: dict[str, int] = {}
    by_region_type: dict[str, int] = {}
    for element in elements:
        by_region[element.region_id] = by_region.get(element.region_id, 0) + 1
        region_type = region_type_by_id.get(element.region_id, "unknown")
        by_region_type[region_type] = by_region_type.get(region_type, 0) + 1
    return {"by_region": by_region, "by_region_type": by_region_type}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local perception layout index.")
    parser.add_argument("--ocr", choices=["disabled", "tesseract", "rapidocr"], default=None)
    args = parser.parse_args()
    try:
        layout_index = build_layout_index(ocr_backend=args.ocr)
    except FileNotFoundError as exc:
        print(str(exc))
        raise SystemExit(1) from exc
    print(f"Saved layout index to {LAYOUT_INDEX_PATH}")
    print(f"Saved annotated overview to {ANNOTATED_OVERVIEW_PATH}")
    print(f"Saved perception report to {PERCEPTION_REPORT_PATH}")
    print(
        "Counts: "
        f"regions={len(layout_index['regions'])}, "
        f"elements={len(layout_index['elements'])}, "
        f"text_blocks={len(layout_index['text_blocks'])}, "
        f"warnings={len(layout_index['warnings'])}"
    )


if __name__ == "__main__":
    main()
