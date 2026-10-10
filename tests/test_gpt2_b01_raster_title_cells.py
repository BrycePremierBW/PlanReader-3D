"""B01 candidate titles never grant source or measurement authority."""
import fitz
from pb_viewport_segmentation import _TitleAnchor, _raster_ink_title_cell_evidence


def _page():
    pdf = fitz.open()
    return pdf, pdf.new_page(width=400, height=300)


def _source_gutters():
    return {
        "horizontal_gutters_visual_pts": ((80.0, 100.0),),
        "vertical_gutters_visual_pts": (),
        "local_vertical_gutters_by_band_visual_pts": (
            {"visual_band_y_pts": (100.0, 300.0),
             "vertical_gutters_visual_pts": ((190.0, 210.0),)},
        ),
    }


def test_separated_native_titles_remain_untrusted_candidates():
    pdf, page = _page()
    anchors = (
        _TitleAnchor("REFLECTED CEILING PLAN", (20, 135, 140, 150),
                     "reflected_ceiling_plan"),
        _TitleAnchor("FLOOR FINISH PLAN", (235, 135, 360, 150),
                     "floor_finish_plan"),
    )
    rows = _raster_ink_title_cell_evidence(page, anchors, _source_gutters())
    assert len(rows) == 2
    assert all(row["unique_title_candidate"] for row in rows)
    assert all(not row["authenticated_viewport"] for row in rows)
    assert all(not row["source_region_complete"] for row in rows)
    pdf.close()


def test_competing_titles_in_one_source_cell_stay_ambiguous():
    pdf, page = _page()
    anchors = (
        _TitleAnchor("REFLECTED CEILING PLAN", (20, 135, 140, 150),
                     "reflected_ceiling_plan"),
        _TitleAnchor("FLOOR FINISH PLAN", (20, 170, 140, 185),
                     "floor_finish_plan"),
    )
    rows = _raster_ink_title_cell_evidence(page, anchors, _source_gutters())
    assert len(rows) == 1
    assert len(rows[0]["contained_titles"]) == 2
    assert not rows[0]["unique_title_candidate"]
    assert not rows[0]["authenticated_viewport"]
    pdf.close()


def test_title_crossing_gutter_does_not_receive_owner():
    pdf, page = _page()
    anchor = _TitleAnchor("FLOOR FINISH PLAN", (180, 135, 220, 150),
                          "floor_finish_plan")
    assert _raster_ink_title_cell_evidence(page, (anchor,), _source_gutters()) == ()
    pdf.close()
