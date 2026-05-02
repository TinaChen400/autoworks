from __future__ import annotations

from PIL import Image

from modules.perception_indexer.schema import BBox, IdGenerator, Region, normalize_bbox


def _is_nonblank_strip(image: Image.Image, box: BBox, threshold: int = 245) -> bool:
    crop = image.crop((box.x, box.y, box.right, box.bottom)).convert("L")
    pixels = crop.resize((max(1, min(80, crop.width)), max(1, min(40, crop.height)))).getdata()
    dark = sum(1 for value in pixels if value < threshold)
    return dark > max(5, len(pixels) * 0.015)


def detect_regions(image: Image.Image, model_region: BBox, ids: IdGenerator) -> list[Region]:
    regions: list[Region] = []
    full = Region(
        region_id=ids.next_region(),
        region_type_hint="model_input_region",
        bbox_raw=model_region.to_dict(),
        bbox_norm=normalize_bbox(model_region, image.width, image.height),
        confidence=1.0,
        metadata={"source": "runtime_context.model_input_region"},
    )
    regions.append(full)

    header_height = max(60, int(model_region.height * 0.12))
    footer_height = max(50, int(model_region.height * 0.10))
    sidebar_width = max(120, int(model_region.width * 0.18))

    candidates = [
        ("header", BBox(model_region.x, model_region.y, model_region.width, header_height), 0.45),
        (
            "footer",
            BBox(
                model_region.x,
                model_region.bottom - footer_height,
                model_region.width,
                footer_height,
            ),
            0.40,
        ),
        (
            "left_sidebar",
            BBox(
                model_region.x,
                model_region.y + header_height,
                sidebar_width,
                max(1, model_region.height - header_height - footer_height),
            ),
            0.35,
        ),
    ]
    for hint, bbox, base_confidence in candidates:
        if bbox.width > 0 and bbox.height > 0 and _is_nonblank_strip(image, bbox):
            regions.append(
                Region(
                    region_id=ids.next_region(),
                    region_type_hint=hint,
                    bbox_raw=bbox.to_dict(),
                    bbox_norm=normalize_bbox(bbox, image.width, image.height),
                    confidence=base_confidence,
                    metadata={"source": "geometric_strip_detection"},
                )
            )

    main = BBox(
        x=model_region.x,
        y=model_region.y + int(header_height * 0.5),
        width=model_region.width,
        height=max(1, model_region.height - int(header_height * 0.5) - int(footer_height * 0.4)),
    )
    regions.append(
        Region(
            region_id=ids.next_region(),
            region_type_hint="main_content",
            bbox_raw=main.to_dict(),
            bbox_norm=normalize_bbox(main, image.width, image.height),
            confidence=0.75,
            metadata={"source": "fallback_main_content"},
        )
    )
    return regions
