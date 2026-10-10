"""B01 source raster coverage may span several drawings."""
from pb_viewport_segmentation import (
    ViewportLayoutCalibration, _raster_component_is_sheetwide,
)


def _calibration():
    return ViewportLayoutCalibration(
        median_word_height_pt=10, title_frame_gap_pt=20,
        minimum_frame_span_pt=100, title_separation_pt=60,
        page_width_pt=1000, page_height_pt=800,
    )


def test_full_page_image_coverage_not_drawing():
    assert _raster_component_is_sheetwide(
        {"native_bbox": (0, 0, 1000, 800)}, _calibration()
    )


def test_localized_image_component_is_not_sheetwide():
    assert not _raster_component_is_sheetwide(
        {"native_bbox": (100, 100, 450, 700)}, _calibration()
    )


def test_invalid_page_dimensions_do_not_claim_sheetwide():
    c = _calibration()
    c = ViewportLayoutCalibration(
        median_word_height_pt=c.median_word_height_pt,
        title_frame_gap_pt=c.title_frame_gap_pt,
        minimum_frame_span_pt=c.minimum_frame_span_pt,
        title_separation_pt=c.title_separation_pt,
        page_width_pt=0, page_height_pt=0,
    )
    assert not _raster_component_is_sheetwide(
        {"native_bbox": (0, 0, 1000, 800)}, c
    )
