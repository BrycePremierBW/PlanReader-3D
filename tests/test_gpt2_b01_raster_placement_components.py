"""Source raster coverage components do not imply plan boundaries."""
from pb_viewport_segmentation import _raster_placement_components


def test_touching_image_tiles_form_untrusted_component():
    groups = [
        {"xref": 7, "native_bboxes": ((0, 0, 10, 10), (10, 0, 20, 10))},
        {"xref": 8, "native_bboxes": ((40, 0, 50, 10),)},
    ]
    result = _raster_placement_components(groups)
    assert len(result) == 2
    assert result[0]["native_bbox"] == (0, 0, 20, 10)
    assert result[0]["placement_count"] == 2
    assert result[0]["authenticated_viewport"] is False


def test_corner_touch_and_disjoint_tiles_remain_separate():
    groups = [{"xref": 4, "native_bboxes": (
        (0, 0, 10, 10), (10, 10, 20, 20), (50, 50, 60, 60),
    )}]
    result = _raster_placement_components(groups)
    assert len(result) == 3
    assert all(not row["authenticated_viewport"] for row in result)


def test_empty_raster_placements_fail_closed():
    assert _raster_placement_components(()) == ()
