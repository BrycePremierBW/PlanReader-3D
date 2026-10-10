"""B01 white gutters are source separation candidates, not plan identities."""
import fitz
from pb_viewport_segmentation import _raster_ink_gutter_evidence


def test_separated_source_ink_yields_untrusted_vertical_gutter():
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.draw_rect(fitz.Rect(15, 20, 140, 180), color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(260, 20, 385, 180), color=(0, 0, 0), fill=(0, 0, 0))
    evidence = _raster_ink_gutter_evidence(page)
    assert evidence["raster_gutters_are_authoritative"] is False
    assert any(a < 200 < b for a, b in evidence["vertical_gutters_visual_pts"])
    assert evidence["render_dimensions"][0] <= 800
    assert evidence["render_dimensions"][1] <= 800
    doc.close()


def test_continuous_ink_cannot_invent_full_width_gutter():
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.draw_rect(fitz.Rect(10, 10, 390, 190), color=(0, 0, 0), fill=(0, 0, 0))
    evidence = _raster_ink_gutter_evidence(page)
    assert evidence["vertical_gutters_visual_pts"] == ()
    assert evidence["raster_gutters_are_authoritative"] is False
    doc.close()


def test_blank_page_has_no_authenticated_gutter():
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    evidence = _raster_ink_gutter_evidence(page)
    assert evidence["vertical_gutters_visual_pts"] == ()
    assert evidence["horizontal_gutters_visual_pts"] == ()
    assert evidence["raster_gutters_are_authoritative"] is False
    doc.close()
