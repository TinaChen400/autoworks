from __future__ import annotations

import pytest

from modules.context_mapper.coordinate_mapper import (
    image_pixel_to_norm,
    image_pixel_to_screen,
    map_model_norm,
    model_norm_to_raw_screenshot_pixel,
    norm_to_image_pixel,
    norm_to_screen,
)


def fake_runtime_context() -> dict:
    return {
        "task_id": "fake",
        "anchor_frame": {"x": 100, "y": 80, "width": 1280, "height": 720},
        "image_size": {"width": 1280, "height": 720},
        "model_input_region": {"x": 10, "y": 20, "width": 1000, "height": 600},
    }


def test_norm_to_image_pixel_and_back() -> None:
    assert norm_to_image_pixel(0.5, 0.25, 200, 100) == (100, 25)
    assert image_pixel_to_norm(100, 25, 200, 100) == (0.5, 0.25)


def test_image_pixel_to_screen() -> None:
    assert image_pixel_to_screen(20, 30, {"x": 100, "y": 80, "width": 200, "height": 100}) == (
        120,
        110,
    )


def test_model_norm_maps_through_model_region_to_screen() -> None:
    runtime_context = fake_runtime_context()

    assert model_norm_to_raw_screenshot_pixel(0.5, 0.5, runtime_context["model_input_region"]) == (
        510,
        320,
    )
    assert norm_to_screen(0.5, 0.5, runtime_context) == (610, 400)
    mapped = map_model_norm(0.5, 0.5, runtime_context)
    assert mapped["model_region_pixel"] == {"x": 500, "y": 300}
    assert mapped["image_pixel_coordinate"] == {"x": 510, "y": 320}
    assert mapped["screen_pixel_coordinate"] == {"x": 610, "y": 400}


def test_norm_validation() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        norm_to_image_pixel(1.1, 0.5, 200, 100)
