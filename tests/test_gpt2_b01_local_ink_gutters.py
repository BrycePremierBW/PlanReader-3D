"""B01: localized source ink gutters cannot manufacture view ownership."""
import fitz
from pb_viewport_segmentation import _raster_ink_gutter_evidence


def test_local_gutter_recovered_when_unrelated_title_band_blocks_global_gap():
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    # Wide header blocks a *page-wide* vertical gutter.
    page.draw_rect(fitz.Rect(10, 10, 390, 55), color=(0, 0, 0), fill=(0, 0, 0))
    # Separate drawings beneath an independently empty horizontal strip.
    page.draw_rect(fitz.Rect(15, 110, 155, 280), color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(245, 110, 385, 280), color=(0, 0, 0), fill=(0, 0, 0))
    result = _raster_ink_gutter_evidence(page)
    assert result["vertical_gutters_visual_pts"] == ()
    assert result["horizontal_gutters_visual_pts"]
    bands = result["local_vertical_gutters_by_band_visual_pts"]
    assert any(
        a < 200 < b
        for band in bands
        for a, b in band["vertical_gutters_visual_pts"]
    )
    assert all(not band["source_region_complete"] for band in bands)
    assert result["raster_gutters_are_authoritative"] is False
    doc.close()


def test_no_local_gutters_when_ink_is_uninterrupted():
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.draw_rect(fitz.Rect(10, 10, 390, 55), color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(10, 110, 390, 280), color=(0, 0, 0), fill=(0, 0, 0))
    result = _raster_ink_gutter_evidence(page)
    assert result["local_vertical_gutters_by_band_visual_pts"] == ()
    assert result["raster_gutters_are_authoritative"] is False
    doc.close()
