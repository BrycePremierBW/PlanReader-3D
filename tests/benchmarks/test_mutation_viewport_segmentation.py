"""Mutation/metamorphic/red-team tests for F.07 viewport segmentation.

All drawings are synthetic. No development-benchmark quantities, project names,
file names, or expected takeoff outputs are used.
"""
from __future__ import annotations

import uuid

import fitz
import pytest

from pb_drawing_evidence_binding import DrawingViewType
from pb_hosted_opening_instance_adapter import authoritative_floor_plan_viewports
from pb_viewport_segmentation import (
    ViewportBoundarySource,
    ViewportSegmentationStatus,
    assign_bbox_to_viewport,
    is_authoritative_derived_viewport,
    segment_page_viewports,
    validate_non_overlapping_viewports,
)


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


def _two_framed_views(*, dx: float = 0.0, dy: float = 0.0, page_width: float = 640, page_height: float = 420) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=page_width, height=page_height)
    left = fitz.Rect(30 + dx, 30 + dy, 295 + dx, 350 + dy)
    right = fitz.Rect(330 + dx, 30 + dy, 595 + dx, 350 + dy)
    page.draw_rect(left)
    page.draw_rect(right)

    # View content exists independently of the title text.
    page.draw_line((65 + dx, 100 + dy), (255 + dx, 100 + dy))
    page.draw_line((65 + dx, 100 + dy), (65 + dx, 240 + dy))
    page.draw_line((365 + dx, 90 + dy), (555 + dx, 90 + dy))
    page.draw_line((460 + dx, 70 + dy), (460 + dx, 250 + dy))

    page.insert_text((80 + dx, 320 + dy), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((92 + dx, 338 + dy), "SCALE 1:100", fontsize=9)
    page.insert_text((390 + dx, 320 + dy), "NORTH ELEVATION", fontsize=11)
    page.insert_text((405 + dx, 338 + dy), "SCALE 1:50", fontsize=9)
    return _reopen(doc)


def _semantic_signature(viewports):
    return sorted(
        (
            v.view_type,
            v.status,
            v.boundary_source,
            v.scale_denominator,
            round(v.bounding_box[2] - v.bounding_box[0], 3) if v.bounding_box else None,
            round(v.bounding_box[3] - v.bounding_box[1], 3) if v.bounding_box else None,
        )
        for v in viewports
    )


def test_two_vector_frames_resolve_actual_viewport_regions_and_scales():
    doc = _two_framed_views()
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert len(viewports) == 2
    assert validate_non_overlapping_viewports(viewports)

    by_type = {v.view_type: v for v in viewports}
    plan = by_type[DrawingViewType.FLOOR_PLAN.value]
    elevation = by_type[DrawingViewType.ELEVATION.value]

    assert plan.status == ViewportSegmentationStatus.RESOLVED.value
    assert elevation.status == ViewportSegmentationStatus.RESOLVED.value
    assert plan.boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
    assert elevation.boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
    # The spatial bbox is the drawing frame, not the tiny title-text bbox.
    assert plan.bounding_box == pytest.approx((30, 30, 295, 350))
    assert elevation.bounding_box == pytest.approx((330, 30, 595, 350))
    assert plan.scale_denominator == pytest.approx(100.0)
    assert elevation.scale_denominator == pytest.approx(50.0)
    assert not plan.scale_conflict
    assert not elevation.scale_conflict
    doc.close()


def test_mutating_view_specific_scale_changes_only_that_viewport_scale():
    base = _two_framed_views()
    changed = fitz.open()
    page = changed.new_page(width=640, height=420)
    page.draw_rect(fitz.Rect(30, 30, 295, 350))
    page.draw_rect(fitz.Rect(330, 30, 595, 350))
    page.insert_text((80, 320), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((92, 338), "SCALE 1:200", fontsize=9)
    page.insert_text((390, 320), "NORTH ELEVATION", fontsize=11)
    page.insert_text((405, 338), "SCALE 1:50", fontsize=9)
    changed = _reopen(changed)

    before = {v.view_type: v for v in segment_page_viewports(base[0], page_number=1)}
    after = {v.view_type: v for v in segment_page_viewports(changed[0], page_number=1)}
    assert before[DrawingViewType.FLOOR_PLAN.value].scale_denominator == 100
    assert after[DrawingViewType.FLOOR_PLAN.value].scale_denominator == 200
    assert before[DrawingViewType.ELEVATION.value].scale_denominator == 50
    assert after[DrawingViewType.ELEVATION.value].scale_denominator == 50
    base.close(); changed.close()


def test_conflicting_scales_inside_one_viewport_remain_unresolved():
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.draw_rect(fitz.Rect(30, 30, 360, 260))
    page.insert_text((110, 220), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((80, 80), "SCALE 1:100", fontsize=9)
    page.insert_text((250, 80), "SCALE 1:50", fontsize=9)
    doc = _reopen(doc)
    viewport = segment_page_viewports(doc[0], page_number=1)[0]
    assert viewport.status == ViewportSegmentationStatus.RESOLVED.value
    assert viewport.scale_conflict
    assert viewport.scale_denominator is None
    assert viewport.scale_raw is None
    assert viewport.notes
    doc.close()


def test_shared_frame_for_two_view_titles_fails_closed_as_ambiguous():
    doc = fitz.open()
    page = doc.new_page(width=500, height=350)
    page.draw_rect(fitz.Rect(30, 30, 470, 300))
    page.insert_text((80, 270), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((300, 270), "WEST ELEVATION", fontsize=11)
    doc = _reopen(doc)
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert len(viewports) == 2
    assert all(v.status == ViewportSegmentationStatus.AMBIGUOUS.value for v in viewports)
    assert all(v.bounding_box is None for v in viewports)
    doc.close()


def test_prose_mention_of_elevation_does_not_create_a_viewport():
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((40, 80), "NOTE: REFER TO NORTH ELEVATION FOR CLADDING SETOUT", fontsize=10)
    doc = _reopen(doc)
    assert segment_page_viewports(doc[0], page_number=1) == []
    doc.close()


def test_single_unframed_title_is_unsupported_not_whole_page_guessed():
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((120, 250), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)
    viewport = segment_page_viewports(doc[0], page_number=1)[0]
    assert viewport.status == ViewportSegmentationStatus.UNSUPPORTED.value
    assert viewport.bounding_box is None
    doc.close()



def _single_plan_with_proven_title_block(
    *,
    include_plan_vectors: bool = True,
    drawing_title: str = "GROUND FLOOR PLAN",
) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=1200, height=842)

    # One real drawing-view title in the printable drawing area.
    page.insert_text((220, 760), drawing_title, fontsize=11)

    if include_plan_vectors:
        # Positive drawing geometry outside the title block.  A title alone
        # is insufficient to mint a page-owned viewport.
        page.draw_line((80, 100), (780, 100))
        page.draw_line((780, 100), (780, 620))
        page.draw_line((780, 620), (80, 620))
        page.draw_line((80, 620), (80, 100))
        page.draw_line((300, 100), (300, 620))

    # Explicit native title-block fields on the page edge.  This is source
    # evidence for the non-drawing region; no project-specific coordinates or
    # labels participate in production code.
    x = 1000
    page.insert_text((x, 520), "PROJECT TITLE", fontsize=6)
    page.insert_text((x, 532), "SYNTHETIC RESIDENCE", fontsize=9)
    page.insert_text((x, 556), "CLIENT", fontsize=6)
    page.insert_text((x, 568), "EXAMPLE CLIENT", fontsize=9)
    page.insert_text((x, 596), "DRAWING TITLE", fontsize=6)
    page.insert_text((x, 612), "GENERAL ARRANGEMENT", fontsize=11)
    page.insert_text((x, 650), "DRAWN", fontsize=6)
    page.insert_text((x + 60, 650), "CHECKED", fontsize=6)
    page.insert_text((x + 120, 650), "SCALE", fontsize=6)
    page.insert_text((x, 662), "AB", fontsize=8)
    page.insert_text((x + 60, 662), "CD", fontsize=8)
    page.insert_text((x + 120, 662), "1:100", fontsize=8)
    page.insert_text((x, 690), "DRAWING NO", fontsize=6)
    page.insert_text((x + 120, 690), "REVISION", fontsize=6)
    page.insert_text((x, 704), "A-201", fontsize=10)
    page.insert_text((x + 120, 704), "C", fontsize=10)
    return _reopen(doc)


def test_single_floor_plan_with_proven_title_block_owns_printable_area():
    doc = _single_plan_with_proven_title_block()
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert len(viewports) == 1
    plan = viewports[0]
    assert plan.view_type == DrawingViewType.FLOOR_PLAN.value
    assert plan.status == ViewportSegmentationStatus.DERIVED.value
    assert plan.boundary_source == ViewportBoundarySource.TITLE_PARTITION.value
    assert plan.bounding_box is not None
    assert plan.provenance["partition_mode"] == "single_floor_plan_printable_area"
    assert plan.provenance["single_view_validated"] is True
    assert plan.provenance["title_block_bbox"]
    assert plan.provenance["drawing_vector_primitive_count"] >= 2
    assert is_authoritative_derived_viewport(plan)

    authoritative = authoritative_floor_plan_viewports(doc[0], page_number=1)
    assert len(authoritative) == 1
    assert authoritative[0].bounding_box == pytest.approx(plan.bounding_box)
    doc.close()


def test_single_floor_finish_plan_with_proven_title_block_owns_printable_area():
    doc = _single_plan_with_proven_title_block(
        drawing_title="PROP. FLOOR FINISHES & PARTITIONS PLAN",
    )
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        assert len(viewports) == 1
        plan = viewports[0]
        assert plan.view_type == DrawingViewType.FLOOR_FINISH_PLAN.value
        assert plan.status == ViewportSegmentationStatus.DERIVED.value
        assert plan.boundary_source == ViewportBoundarySource.TITLE_PARTITION.value
        assert plan.bounding_box is not None
        assert (
            plan.provenance["partition_mode"]
            == "single_floor_finish_plan_printable_area"
        )
        assert plan.provenance["single_view_validated"] is True
        assert plan.provenance["title_block_bbox"]
        assert plan.provenance["drawing_vector_primitive_count"] >= 2
        assert is_authoritative_derived_viewport(plan)
        # Surface semantics remain distinct from the opening/floor-plan helper.
        assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    finally:
        doc.close()


def test_single_floor_plan_with_title_block_but_no_drawing_geometry_stays_unsupported():
    doc = _single_plan_with_proven_title_block(include_plan_vectors=False)
    viewport = segment_page_viewports(doc[0], page_number=1)[0]
    assert viewport.status == ViewportSegmentationStatus.UNSUPPORTED.value
    assert viewport.bounding_box is None
    assert not is_authoritative_derived_viewport(viewport)
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()



def _single_plan_with_sheet_drawing_frame(
    *,
    include_footer_metadata: bool = True,
    omit_right_frame_edge: bool = False,
    drawing_title: str = "GROUND FLOOR PLAN",
) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=1200, height=842)

    # Deliberately draw the large sheet drawing frame as four independent
    # source lines, not one rectangle path.  This exercises the source-owned
    # sheet-frame resolver rather than the ordinary native-frame path.
    left, top, right, bottom = 24.0, 24.0, 1170.0, 770.0
    page.draw_line((left, top), (right, top))
    page.draw_line((left, bottom), (right, bottom))
    page.draw_line((left, top), (left, bottom))
    if not omit_right_frame_edge:
        page.draw_line((right, top), (right, bottom))

    # Real drawing content, distinct from the sheet boundary itself.
    page.draw_line((90, 120), (760, 120))
    page.draw_line((760, 120), (760, 600))
    page.draw_line((760, 600), (90, 600))
    page.draw_line((90, 600), (90, 120))
    page.insert_text((180, 690), drawing_title, fontsize=11)

    # Separate source-owned footer/metadata band outside the drawing frame.
    page.draw_line((left, 774), (right, 774))
    page.draw_line((left, 820), (right, 820))
    page.draw_line((left, 774), (left, 820))
    page.draw_line((right, 774), (right, 820))
    if include_footer_metadata:
        page.insert_text((700, 788), "Drawing name:", fontsize=6)
        page.insert_text((700, 802), "Floor Plan", fontsize=9)
        page.insert_text((900, 788), "Client", fontsize=6)
        page.insert_text((900, 802), "Example Client", fontsize=9)
        page.insert_text((1040, 788), "REVISION", fontsize=6)
        page.insert_text((1120, 788), "Scale:", fontsize=6)
        page.insert_text((1120, 802), "1:100", fontsize=8)

    return _reopen(doc)


def test_single_floor_plan_sheet_frame_with_separate_metadata_band_is_authoritative():
    doc = _single_plan_with_sheet_drawing_frame()
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert len(viewports) == 1
    plan = viewports[0]
    assert plan.view_type == DrawingViewType.FLOOR_PLAN.value
    assert plan.status == ViewportSegmentationStatus.DERIVED.value
    assert plan.bounding_box == pytest.approx((24.0, 24.0, 1170.0, 770.0))
    assert plan.provenance["partition_mode"] == "single_floor_plan_sheet_frame"
    assert plan.provenance["single_view_validated"] is True
    assert plan.provenance["metadata_label_count"] >= 2
    assert plan.provenance["drawing_vector_primitive_count"] >= 2
    assert is_authoritative_derived_viewport(plan)
    assert len(authoritative_floor_plan_viewports(doc[0], page_number=1)) == 1
    doc.close()


def test_single_floor_finish_plan_sheet_frame_with_metadata_is_authoritative():
    doc = _single_plan_with_sheet_drawing_frame(
        drawing_title="PROP. FLOOR FINISHES & PARTITIONS PLAN",
    )
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        assert len(viewports) == 1
        plan = viewports[0]
        assert plan.view_type == DrawingViewType.FLOOR_FINISH_PLAN.value
        assert plan.status == ViewportSegmentationStatus.DERIVED.value
        assert plan.bounding_box == pytest.approx((24.0, 24.0, 1170.0, 770.0))
        assert (
            plan.provenance["partition_mode"]
            == "single_floor_finish_plan_sheet_frame"
        )
        assert plan.provenance["single_view_validated"] is True
        assert plan.provenance["metadata_label_count"] >= 2
        assert plan.provenance["drawing_vector_primitive_count"] >= 2
        assert is_authoritative_derived_viewport(plan)
        assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    finally:
        doc.close()


def test_single_floor_plan_sheet_frame_without_metadata_band_evidence_stays_unsupported():
    doc = _single_plan_with_sheet_drawing_frame(include_footer_metadata=False)
    viewport = segment_page_viewports(doc[0], page_number=1)[0]
    assert viewport.status == ViewportSegmentationStatus.UNSUPPORTED.value
    assert viewport.bounding_box is None
    assert not is_authoritative_derived_viewport(viewport)
    doc.close()


def test_single_floor_plan_incomplete_sheet_frame_stays_unsupported():
    doc = _single_plan_with_sheet_drawing_frame(omit_right_frame_edge=True)
    viewport = segment_page_viewports(doc[0], page_number=1)[0]
    assert viewport.status == ViewportSegmentationStatus.UNSUPPORTED.value
    assert viewport.bounding_box is None
    assert not is_authoritative_derived_viewport(viewport)
    doc.close()


def test_two_unframed_separated_titles_create_non_overlapping_derived_partition():
    doc = fitz.open()
    page = doc.new_page(width=600, height=360)
    page.insert_text((80, 320), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((390, 320), "EAST ELEVATION", fontsize=11)
    page.insert_text((85, 100), "SCALE 1:100", fontsize=9)
    page.insert_text((405, 100), "SCALE 1:50", fontsize=9)
    doc = _reopen(doc)
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert len(viewports) == 2
    assert all(v.status == ViewportSegmentationStatus.DERIVED.value for v in viewports)
    assert validate_non_overlapping_viewports(viewports)
    by_type = {v.view_type: v for v in viewports}
    assert by_type[DrawingViewType.FLOOR_PLAN.value].scale_denominator == 100
    assert by_type[DrawingViewType.ELEVATION.value].scale_denominator == 50
    # Ordinary one-axis title partitions remain diagnostic-only.
    assert not is_authoritative_derived_viewport(
        by_type[DrawingViewType.FLOOR_PLAN.value]
    )
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def _three_column_unframed_grid(*, conflicting_title: bool = False) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=900, height=700)

    # Left column.
    page.insert_text((80, 250), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((90, 620), "ROOF PLAN", fontsize=11)

    # Middle column.
    page.insert_text((380, 200), "ELEVATION E-01", fontsize=11)
    page.insert_text((380, 560), "SECTION S-01", fontsize=11)

    # Right column.
    page.insert_text((680, 200), "ELEVATION E-02", fontsize=11)
    page.insert_text((680, 560), "SECTION S-02", fontsize=11)

    if conflicting_title:
        # A distinct title inside the same minimum-height ownership band must
        # invalidate the grid rather than being collapsed as a duplicate.
        page.insert_text((382, 225), "WEST ELEVATION", fontsize=11)

    return _reopen(doc)


def test_columnar_title_grid_is_strict_derived_floor_plan_authority():
    doc = _three_column_unframed_grid()
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert validate_non_overlapping_viewports(viewports)

    plan = next(
        viewport for viewport in viewports
        if viewport.view_type == DrawingViewType.FLOOR_PLAN.value
    )
    assert plan.status == ViewportSegmentationStatus.DERIVED.value
    assert plan.boundary_source == ViewportBoundarySource.TITLE_PARTITION.value
    assert plan.bounding_box is not None
    assert plan.provenance["partition_mode"] == "columnar_title_grid"
    assert plan.provenance["grid_validated"] is True
    assert is_authoritative_derived_viewport(plan)

    authoritative = authoritative_floor_plan_viewports(doc[0], page_number=1)
    assert len(authoritative) == 1
    assert authoritative[0].label == "GROUND FLOOR PLAN"
    assert authoritative[0].bounding_box == pytest.approx(plan.bounding_box)
    doc.close()


def test_columnar_title_grid_distinct_close_titles_fail_closed():
    doc = _three_column_unframed_grid(conflicting_title=True)
    viewports = segment_page_viewports(doc[0], page_number=1)
    plan = next(
        viewport for viewport in viewports
        if viewport.view_type == DrawingViewType.FLOOR_PLAN.value
    )
    assert plan.status == ViewportSegmentationStatus.AMBIGUOUS.value
    assert plan.bounding_box is None
    assert not is_authoritative_derived_viewport(plan)
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def test_bbox_assignment_requires_unique_spatial_owner():
    doc = _two_framed_views()
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert assign_bbox_to_viewport((100, 100, 120, 120), viewports).view_type == DrawingViewType.FLOOR_PLAN.value
    assert assign_bbox_to_viewport((400, 100, 420, 120), viewports).view_type == DrawingViewType.ELEVATION.value
    assert assign_bbox_to_viewport((300, 100, 310, 120), viewports) is None
    doc.close()


def test_translation_metamorphic_preserves_semantic_segmentation():
    base = _two_framed_views()
    moved = _two_framed_views(dx=20, dy=15, page_width=680, page_height=450)
    before = segment_page_viewports(base[0], page_number=1)
    after = segment_page_viewports(moved[0], page_number=1)
    assert _semantic_signature(before) == _semantic_signature(after)
    base.close(); moved.close()


def test_page_number_and_random_identity_do_not_change_view_semantics():
    doc = _two_framed_views()
    first = segment_page_viewports(doc[0], page_number=1)
    # Random identity is deliberately kept outside the segmenter API. Changing
    # provenance page number can change IDs, but not semantic partitioning.
    _ = str(uuid.uuid4())
    second = segment_page_viewports(doc[0], page_number=77)
    assert _semantic_signature(first) == _semantic_signature(second)
    assert [v.view_id for v in first] != [v.view_id for v in second]
    doc.close()


def test_schedule_and_detail_are_separate_from_plan_when_framed():
    doc = fitz.open()
    page = doc.new_page(width=900, height=420)
    frames = [fitz.Rect(20, 30, 280, 350), fitz.Rect(320, 30, 580, 350), fitz.Rect(620, 30, 880, 350)]
    for frame in frames:
        page.draw_rect(frame)
    page.insert_text((60, 320), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((360, 320), "WINDOW SCHEDULE", fontsize=11)
    page.insert_text((690, 320), "TYPICAL DETAIL D1", fontsize=11)
    doc = _reopen(doc)
    types = {v.view_type for v in segment_page_viewports(doc[0], page_number=1)}
    assert types == {
        DrawingViewType.FLOOR_PLAN.value,
        DrawingViewType.SCHEDULE.value,
        DrawingViewType.DETAIL.value,
    }
    doc.close()


def test_plan_floor_layout_title_is_supported_without_relaxing_prose_guard():
    doc = fitz.open()
    page = doc.new_page(width=640, height=420)
    page.draw_rect(fitz.Rect(30, 30, 295, 350))
    page.draw_rect(fitz.Rect(330, 30, 595, 350))
    page.insert_text((80, 320), "PLAN : FLOOR LAYOUT", fontsize=11)
    page.insert_text((400, 320), "LEGEND", fontsize=11)
    doc = _reopen(doc)

    viewports = segment_page_viewports(doc[0], page_number=1)
    by_type = {v.view_type: v for v in viewports}
    assert DrawingViewType.FLOOR_PLAN.value in by_type
    assert by_type[DrawingViewType.FLOOR_PLAN.value].status == ViewportSegmentationStatus.RESOLVED.value
    assert by_type[DrawingViewType.FLOOR_PLAN.value].bounding_box == pytest.approx((30, 30, 295, 350))
    doc.close()

    prose = fitz.open()
    page = prose.new_page(width=400, height=300)
    page.insert_text((40, 80), "NOTE: PLAN : FLOOR LAYOUT REVISED - REFER TO ARCHITECT", fontsize=10)
    prose = _reopen(prose)
    assert segment_page_viewports(prose[0], page_number=1) == []
    prose.close()


def _single_table_frame_view(title: str) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=900, height=420)
    outer = fitz.Rect(320, 30, 580, 350)
    page.draw_rect(outer)

    x0, y0 = 340.0, 60.0
    cell_w, cell_h = 70.0, 60.0
    for row in range(3):
        for col in range(3):
            page.draw_rect(
                fitz.Rect(
                    x0 + col * cell_w,
                    y0 + row * cell_h,
                    x0 + (col + 1) * cell_w,
                    y0 + (row + 1) * cell_h,
                )
            )
    page.insert_text((360, 325), title, fontsize=11)
    return _reopen(doc)


def test_gridded_finish_schedule_table_frame_can_own_schedule_viewport():
    doc = _single_table_frame_view("FINISH SCHEDULE")
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        assert len(viewports) == 1
        schedule = viewports[0]
        assert schedule.view_type == DrawingViewType.SCHEDULE.value
        assert schedule.status == ViewportSegmentationStatus.RESOLVED.value
        assert schedule.boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
        assert schedule.bounding_box == pytest.approx((320, 30, 580, 350))
    finally:
        doc.close()


def test_gridded_table_frame_cannot_mint_floor_plan_viewport():
    doc = _single_table_frame_view("GROUND FLOOR PLAN")
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        assert len(viewports) == 1
        plan = viewports[0]
        assert plan.view_type == DrawingViewType.FLOOR_PLAN.value
        assert plan.status == ViewportSegmentationStatus.UNSUPPORTED.value
        assert plan.bounding_box is None
    finally:
        doc.close()


def test_gridded_internal_finishes_schedule_table_frame_is_authoritative():
    doc = _single_table_frame_view("INTERNAL FINISHES SCHEDULE")
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        assert len(viewports) == 1
        schedule = viewports[0]
        assert schedule.view_type == DrawingViewType.SCHEDULE.value
        assert schedule.status == ViewportSegmentationStatus.RESOLVED.value
        assert schedule.boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
        assert schedule.bounding_box == pytest.approx((320, 30, 580, 350))
    finally:
        doc.close()


def test_surface_semantic_views_do_not_become_floor_topology() -> None:
    for title, expected in (
        ("PROP. REFLECTED CEILING PLAN", DrawingViewType.REFLECTED_CEILING_PLAN.value),
        ("PROP. FLOOR FINISHES & PARTITIONS PLAN", DrawingViewType.FLOOR_FINISH_PLAN.value),
    ):
        doc = fitz.open()
        page = doc.new_page(width=500, height=350)
        frame = fitz.Rect(30, 30, 470, 300)
        page.draw_rect(frame)
        page.draw_line((80, 100), (420, 100))
        page.draw_line((80, 100), (80, 240))
        page.insert_text((95, 270), title, fontsize=11)
        doc = _reopen(doc)
        try:
            viewports = segment_page_viewports(doc[0], page_number=1)
            owned = [v for v in viewports if v.view_type == expected]
            assert len(owned) == 1
            assert owned[0].status == ViewportSegmentationStatus.RESOLVED.value
            assert owned[0].bounding_box == pytest.approx((30, 30, 470, 300))
            assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
        finally:
            doc.close()


def test_wrapped_floor_finish_title_in_one_native_block_resolves() -> None:
    doc = fitz.open()
    page = doc.new_page(width=500, height=350)
    frame = fitz.Rect(30, 30, 470, 300)
    page.draw_rect(frame)
    page.draw_line((80, 100), (420, 100))
    page.draw_line((80, 100), (80, 240))
    page.insert_textbox(
        fitz.Rect(100, 245, 420, 292),
        "PROP. FLOOR FINISHES &\nPARTITIONS PLAN",
        fontsize=11,
    )
    doc = _reopen(doc)
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        owned = [
            v for v in viewports
            if v.view_type == DrawingViewType.FLOOR_FINISH_PLAN.value
        ]
        assert len(owned) == 1
        assert owned[0].status == ViewportSegmentationStatus.RESOLVED.value
        assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    finally:
        doc.close()


def test_floor_finish_title_halves_in_separate_native_blocks_are_not_joined() -> None:
    doc = fitz.open()
    page = doc.new_page(width=500, height=350)
    page.draw_rect(fitz.Rect(30, 30, 470, 300))
    page.insert_text((100, 255), "PROP. FLOOR FINISHES &", fontsize=11)
    page.insert_text((100, 275), "PARTITIONS PLAN", fontsize=11)
    doc = _reopen(doc)
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        assert not any(
            viewport.view_type == DrawingViewType.FLOOR_FINISH_PLAN.value
            for viewport in viewports
        )
    finally:
        doc.close()


def test_single_reflected_ceiling_plan_can_own_printable_area_without_floor_topology() -> None:
    doc = fitz.open()
    page = doc.new_page(width=1200, height=842)
    page.insert_text((220, 760), "PROP. REFLECTED CEILING PLAN", fontsize=11)
    page.draw_line((80, 100), (780, 100))
    page.draw_line((780, 100), (780, 620))
    page.draw_line((780, 620), (80, 620))
    page.draw_line((80, 620), (80, 100))
    page.draw_line((300, 100), (300, 620))

    x = 1000
    page.insert_text((x, 520), "PROJECT TITLE", fontsize=6)
    page.insert_text((x, 532), "SYNTHETIC RESIDENCE", fontsize=9)
    page.insert_text((x, 556), "CLIENT", fontsize=6)
    page.insert_text((x, 568), "EXAMPLE CLIENT", fontsize=9)
    page.insert_text((x, 596), "DRAWING TITLE", fontsize=6)
    page.insert_text((x, 612), "REFLECTED CEILING PLAN", fontsize=11)
    page.insert_text((x, 650), "DRAWN", fontsize=6)
    page.insert_text((x + 60, 650), "CHECKED", fontsize=6)
    page.insert_text((x + 120, 650), "SCALE", fontsize=6)
    page.insert_text((x, 662), "AB", fontsize=8)
    page.insert_text((x + 60, 662), "CD", fontsize=8)
    page.insert_text((x + 120, 662), "1:100", fontsize=8)
    page.insert_text((x, 690), "DRAWING NO", fontsize=6)
    page.insert_text((x + 120, 690), "REVISION", fontsize=6)
    page.insert_text((x, 704), "A-501", fontsize=10)
    page.insert_text((x + 120, 704), "A", fontsize=10)

    doc = _reopen(doc)
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        rcp = [
            v for v in viewports
            if v.view_type == DrawingViewType.REFLECTED_CEILING_PLAN.value
        ]
        assert len(rcp) == 1
        assert rcp[0].status == ViewportSegmentationStatus.DERIVED.value
        assert rcp[0].boundary_source == ViewportBoundarySource.TITLE_PARTITION.value
        assert is_authoritative_derived_viewport(rcp[0])
        assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    finally:
        doc.close()


@pytest.mark.parametrize(
    "title",
    (
        "INTERNAL FINISHES SCHEDULE",
        "EXTERNAL FINISHES SCHEDULE",
        "CEILING FINISHES SCHEDULE",
        "FLOOR FINISHES SCHEDULE",
    ),
)
def test_gridded_qualified_finish_schedule_titles_are_authoritative(title: str) -> None:
    doc = _single_table_frame_view(title)
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        assert len(viewports) == 1
        schedule = viewports[0]
        assert schedule.view_type == DrawingViewType.SCHEDULE.value
        assert schedule.status == ViewportSegmentationStatus.RESOLVED.value
        assert schedule.boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
        assert schedule.bounding_box == pytest.approx((320, 30, 580, 350))
    finally:
        doc.close()


def _single_line_grid_frame_view(title: str) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=900, height=420)
    outer = fitz.Rect(320, 30, 580, 350)
    page.draw_rect(outer)
    xs = (340.0, 410.0, 480.0, 550.0)
    ys = (60.0, 120.0, 180.0, 240.0)
    for x in xs:
        page.draw_line((x, 60.0), (x, 240.0))
    for y in ys:
        page.draw_line((340.0, y), (550.0, y))
    page.insert_text((350, 325), title, fontsize=11)
    return _reopen(doc)


def test_line_grid_finish_schedule_can_own_semantic_table_viewport() -> None:
    doc = _single_line_grid_frame_view("INTERNAL FINISHES SCHEDULE")
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        assert len(viewports) == 1
        schedule = viewports[0]
        assert schedule.view_type == DrawingViewType.SCHEDULE.value
        assert schedule.status == ViewportSegmentationStatus.RESOLVED.value
        assert schedule.boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
        assert schedule.bounding_box == pytest.approx((320, 30, 580, 350))
    finally:
        doc.close()


def test_line_grid_frame_cannot_mint_floor_plan_authority() -> None:
    doc = _single_line_grid_frame_view("GROUND FLOOR PLAN")
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        assert len(viewports) == 1
        plan = viewports[0]
        assert plan.view_type == DrawingViewType.FLOOR_PLAN.value
        assert plan.status == ViewportSegmentationStatus.UNSUPPORTED.value
        assert plan.bounding_box is None
        assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    finally:
        doc.close()



def _vertical_title_line_grid_schedule() -> fitz.Document:
    """Semantic schedule whose producer-owned title advances vertically."""

    doc = fitz.open()
    page = doc.new_page(width=720, height=420)

    outer = fitz.Rect(80.0, 30.0, 300.0, 390.0)
    page.draw_rect(outer)
    xs = (100.0, 145.0, 190.0, 235.0, 280.0)
    ys = (55.0, 110.0, 165.0, 220.0, 275.0, 330.0)
    for x in xs:
        page.draw_line((x, 55.0), (x, 330.0))
    for y in ys:
        page.draw_line((100.0, y), (280.0, y))

    # Ordinary small source text keeps layout calibration representative while
    # remaining semantically inert.
    for index, label in enumerate(("A", "B", "C", "D", "E", "F")):
        page.insert_text((110.0, 75.0 + index * 45.0), label, fontsize=8.0)

    # rotate=90 yields a native vertical line. The table sits immediately to
    # its left; in the title-local basis this is the ordinary
    # "frame above, title below" ownership pattern.
    page.insert_text(
        (325.0, 310.0),
        "CEILING FINISHES SCHEDULE",
        fontsize=10.0,
        rotate=90,
    )

    # A normal drawing frame elsewhere must not steal this schedule title.
    page.draw_rect(fitz.Rect(390.0, 30.0, 690.0, 360.0))
    page.draw_line((420.0, 80.0), (650.0, 80.0))
    page.draw_line((420.0, 80.0), (420.0, 300.0))
    return _reopen(doc)


def test_vertical_native_schedule_title_owns_exact_gridded_table_frame() -> None:
    doc = _vertical_title_line_grid_schedule()
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        schedules = [
            viewport
            for viewport in viewports
            if viewport.view_type == DrawingViewType.SCHEDULE.value
        ]
        assert len(schedules) == 1
        schedule = schedules[0]
        assert schedule.status == ViewportSegmentationStatus.RESOLVED.value
        assert schedule.boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
        assert schedule.bounding_box == pytest.approx(
            (80.0, 30.0, 300.0, 390.0)
        )
        assert schedule.label == "CEILING FINISHES SCHEDULE"
    finally:
        doc.close()


def test_extreme_aspect_non_table_frame_still_rejected_for_vertical_title() -> None:
    doc = fitz.open()
    page = doc.new_page(width=1200, height=1000)
    page.draw_rect(fitz.Rect(120.0, 40.0, 220.0, 940.0))
    for index in range(8):
        page.insert_text(
            (400.0, 100.0 + index * 40.0),
            f"NOTE {index}",
            fontsize=8.0,
        )
    page.insert_text(
        (245.0, 700.0),
        "CEILING FINISHES SCHEDULE",
        fontsize=10.0,
        rotate=90,
    )
    doc = _reopen(doc)
    try:
        schedules = [
            viewport
            for viewport in segment_page_viewports(doc[0], page_number=1)
            if viewport.view_type == DrawingViewType.SCHEDULE.value
        ]
        assert len(schedules) == 1
        assert schedules[0].status == ViewportSegmentationStatus.UNSUPPORTED.value
        assert schedules[0].bounding_box is None
    finally:
        doc.close()


def test_rotated_rcps_can_use_resolved_schedule_as_nonoverlapping_band_separator() -> None:
    doc = _rotated_two_rcps_with_central_schedule()
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert validate_non_overlapping_viewports(viewports)

    schedule = [
        viewport
        for viewport in viewports
        if viewport.view_type == DrawingViewType.SCHEDULE.value
    ]
    rcps = [
        viewport
        for viewport in viewports
        if viewport.view_type == DrawingViewType.REFLECTED_CEILING_PLAN.value
    ]
    assert len(schedule) == 1
    assert schedule[0].status == ViewportSegmentationStatus.RESOLVED.value, [(v.label, v.status, v.notes, v.provenance) for v in viewports]
    assert len(rcps) == 2
    assert all(
        viewport.status == ViewportSegmentationStatus.DERIVED.value
        for viewport in rcps
    )
    assert all(is_authoritative_derived_viewport(viewport) for viewport in rcps)
    assert {
        viewport.provenance.get("separator_side")
        for viewport in rcps
    } == {"left", "right"}
    assert all(
        viewport.provenance.get("visual_band_validated") is True
        for viewport in rcps
    )
    doc.close()


def test_rotated_semantic_band_fails_closed_when_two_plan_titles_compete() -> None:
    doc = fitz.open()
    page = doc.new_page(width=600.0, height=800.0)
    page.set_rotation(90)
    schedule = fitz.Rect(150.0, 300.0, 450.0, 500.0)
    page.draw_rect(schedule)
    for x in (210.0, 270.0, 330.0, 390.0):
        page.draw_line((x, 300.0), (x, 500.0))
    for y in (340.0, 380.0, 420.0, 460.0):
        page.draw_line((150.0, y), (450.0, y))
    page.insert_text(
        (430.0, 480.0),
        "CEILING FINISHES SCHEDULE",
        fontsize=9,
        rotate=90,
    )
    page.draw_line((80.0, 560.0), (520.0, 560.0))
    page.draw_line((120.0, 690.0), (480.0, 690.0))
    page.draw_line((80.0, 120.0), (520.0, 120.0))
    page.draw_line((120.0, 230.0), (480.0, 230.0))
    page.insert_text(
        (520.0, 760.0),
        "REFLECTED CEILING PLAN",
        fontsize=11,
        rotate=90,
    )
    # A second plan title in the same visual left band destroys unique owner.
    page.insert_text(
        (480.0, 740.0),
        "GROUND FLOOR PLAN",
        fontsize=11,
        rotate=90,
    )
    page.insert_text(
        (520.0, 180.0),
        "PROP. REFLECTED CEILING PLAN",
        fontsize=11,
        rotate=90,
    )
    doc = _reopen(doc)

    viewports = segment_page_viewports(doc[0], page_number=1)
    left_competitors = [
        viewport
        for viewport in viewports
        if viewport.label in ("REFLECTED CEILING PLAN", "GROUND FLOOR PLAN")
    ]
    assert len(left_competitors) == 2
    assert all(
        not is_authoritative_derived_viewport(viewport)
        for viewport in left_competitors
    )
    doc.close()


def test_single_reflected_ceiling_plan_can_own_printable_area_without_floor_topology() -> None:
    doc = fitz.open()
    page = doc.new_page(width=1200, height=842)
    page.insert_text((220, 760), "PROP. REFLECTED CEILING PLAN", fontsize=11)
    page.draw_line((80, 100), (780, 100))
    page.draw_line((780, 100), (780, 620))
    page.draw_line((780, 620), (80, 620))
    page.draw_line((80, 620), (80, 100))
    page.draw_line((300, 100), (300, 620))

    x = 1000
    page.insert_text((x, 520), "PROJECT TITLE", fontsize=6)
    page.insert_text((x, 532), "SYNTHETIC RESIDENCE", fontsize=9)
    page.insert_text((x, 556), "CLIENT", fontsize=6)
    page.insert_text((x, 568), "EXAMPLE CLIENT", fontsize=9)
    page.insert_text((x, 596), "DRAWING TITLE", fontsize=6)
    page.insert_text((x, 612), "REFLECTED CEILING PLAN", fontsize=11)
    page.insert_text((x, 650), "DRAWN", fontsize=6)
    page.insert_text((x + 60, 650), "CHECKED", fontsize=6)
    page.insert_text((x + 120, 650), "SCALE", fontsize=6)
    page.insert_text((x, 662), "AB", fontsize=8)
    page.insert_text((x + 60, 662), "CD", fontsize=8)
    page.insert_text((x + 120, 662), "1:100", fontsize=8)
    page.insert_text((x, 690), "DRAWING NO", fontsize=6)
    page.insert_text((x + 120, 690), "REVISION", fontsize=6)
    page.insert_text((x, 704), "A-501", fontsize=10)
    page.insert_text((x + 120, 704), "A", fontsize=10)

    doc = _reopen(doc)
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        rcp = [
            v for v in viewports
            if v.view_type == DrawingViewType.REFLECTED_CEILING_PLAN.value
        ]
        assert len(rcp) == 1
        assert rcp[0].status == ViewportSegmentationStatus.DERIVED.value
        assert rcp[0].boundary_source == ViewportBoundarySource.TITLE_PARTITION.value
        assert is_authoritative_derived_viewport(rcp[0])
        assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    finally:
        doc.close()


@pytest.mark.parametrize(
    "title",
    (
        "INTERNAL FINISHES SCHEDULE",
        "EXTERNAL FINISHES SCHEDULE",
        "CEILING FINISHES SCHEDULE",
        "FLOOR FINISHES SCHEDULE",
    ),
)
def test_gridded_qualified_finish_schedule_titles_are_authoritative(title: str) -> None:
    doc = _single_table_frame_view(title)
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        assert len(viewports) == 1
        schedule = viewports[0]
        assert schedule.view_type == DrawingViewType.SCHEDULE.value
        assert schedule.status == ViewportSegmentationStatus.RESOLVED.value
        assert schedule.boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
        assert schedule.bounding_box == pytest.approx((320, 30, 580, 350))
    finally:
        doc.close()


def _single_line_grid_frame_view(title: str) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=900, height=420)
    outer = fitz.Rect(320, 30, 580, 350)
    page.draw_rect(outer)
    xs = (340.0, 410.0, 480.0, 550.0)
    ys = (60.0, 120.0, 180.0, 240.0)
    for x in xs:
        page.draw_line((x, 60.0), (x, 240.0))
    for y in ys:
        page.draw_line((340.0, y), (550.0, y))
    page.insert_text((350, 325), title, fontsize=11)
    return _reopen(doc)



def _rotated_two_rcps_with_central_schedule() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=600.0, height=800.0)
    page.set_rotation(90)

    # Native bbox -> visual center panel at x=300..500, y=150..450.
    schedule = fitz.Rect(150.0, 300.0, 450.0, 500.0)
    page.draw_rect(schedule)
    for x in (210.0, 270.0, 330.0, 390.0):
        page.draw_line((x, 300.0), (x, 500.0))
    for y in (340.0, 380.0, 420.0, 460.0):
        page.draw_line((150.0, y), (450.0, y))
    page.insert_text(
        (475.0, 480.0),
        "CEILING FINISHES SCHEDULE",
        fontsize=9,
        rotate=90,
    )

    # Two independent plan drawings on opposite visual sides of the table.
    page.draw_line((80.0, 560.0), (520.0, 560.0))
    page.draw_line((120.0, 690.0), (480.0, 690.0))
    page.draw_line((80.0, 120.0), (520.0, 120.0))
    page.draw_line((120.0, 230.0), (480.0, 230.0))
    page.insert_text(
        (520.0, 760.0),
        "REFLECTED CEILING PLAN",
        fontsize=11,
        rotate=90,
    )
    page.insert_text(
        (520.0, 260.0),
        "PROP. REFLECTED CEILING PLAN",
        fontsize=11,
        rotate=90,
    )
    return _reopen(doc)



def test_rotated_semantic_band_rejects_competing_nonplan_title() -> None:
    """An elevation title sharing the RCP side band must revoke ownership."""
    doc = _rotated_two_rcps_with_central_schedule()
    page = doc[0]
    page.insert_text(
        (480.0, 740.0), "NORTH ELEVATION", fontsize=11, rotate=90
    )
    doc = _reopen(doc)
    try:
        viewports = segment_page_viewports(doc[0], page_number=1)
        left = [
            viewport for viewport in viewports
            if viewport.label == "REFLECTED CEILING PLAN"
        ]
        assert len(left) == 1
        assert not is_authoritative_derived_viewport(left[0])
        assert left[0].bounding_box is None
        assert validate_non_overlapping_viewports(viewports)
    finally:
        doc.close()


def test_rotated_native_vertical_words_do_not_inflate_frame_calibration() -> None:
    """The length of vertical title words is not their glyph height."""
    from pb_viewport_segmentation import calibrate_viewport_layout

    doc = _rotated_two_rcps_with_central_schedule()
    try:
        words = doc[0].get_text("words")
        assert words
        raw_median_word_span = sorted(
            float(word[3]) - float(word[1]) for word in words
        )[len(words) // 2]
        calibration = calibrate_viewport_layout(doc[0])
        assert raw_median_word_span > 30.0
        assert 0.0 < calibration.median_word_height_pt < 20.0
        # Source-native 300x200 pt schedule must remain frame-eligible.
        assert calibration.minimum_frame_span_pt < 200.0
    finally:
        doc.close()


def test_native_vertical_line_direction_calibrates_unrotated_page_glyphs() -> None:
    """A page without /Rotate can still contain native vertical CAD text."""
    from pb_viewport_segmentation import calibrate_viewport_layout

    doc = fitz.open()
    page = doc.new_page(width=520, height=520)
    for x in (100.0, 230.0, 360.0):
        page.insert_text(
            (x, 430.0), "REFLECTED CEILING PLAN",
            fontsize=11, rotate=90,
        )
    doc = _reopen(doc)
    try:
        page = doc[0]
        assert page.rotation == 0
        lines = [
            line
            for block in page.get_text("dict").get("blocks", [])
            if int(block.get("type", 0)) == 0
            for line in block.get("lines", [])
        ]
        assert len(lines) == 3
        assert all(abs(float(line["dir"][1])) > 0.9 for line in lines)
        assert all(
            float(line["bbox"][3]) - float(line["bbox"][1]) > 40.0
            for line in lines
        )
        calibration = calibrate_viewport_layout(page)
        assert 0.0 < calibration.median_word_height_pt < 20.0
        assert calibration.minimum_frame_span_pt < 160.0
    finally:
        doc.close()


def test_native_horizontal_lines_keep_expected_glyph_height() -> None:
    """Horizontal source lines must not use their word length as thickness."""
    from pb_viewport_segmentation import calibrate_viewport_layout

    doc = fitz.open()
    page = doc.new_page(width=520, height=520)
    for y in (100.0, 210.0, 320.0):
        page.insert_text(
            (60.0, y), "REFLECTED CEILING PLAN",
            fontsize=11, rotate=0,
        )
    doc = _reopen(doc)
    try:
        calibration = calibrate_viewport_layout(doc[0])
        assert 0.0 < calibration.median_word_height_pt < 20.0
        assert calibration.minimum_frame_span_pt < 160.0
    finally:
        doc.close()


def test_rotated_band_coordinate_roundtrip_preserves_native_source_bbox() -> None:
    """Native page geometry must round-trip through rotated page coordinates.

    A rotated viewport's source PDF page-space dimensions and extent remain
    authoritative. Visual rotation is never a license to move the source face
    or generate a measurement scale.
    """
    from pb_viewport_segmentation import _to_native_bbox, _to_visual_bbox

    doc = fitz.open()
    page = doc.new_page(width=720, height=420)
    native = (64.0, 52.0, 300.0, 280.0)
    try:
        for rotation in (0, 90, 270):
            page.set_rotation(rotation)
            visual = _to_visual_bbox(page, native)
            restored = _to_native_bbox(page, visual)
            assert restored == pytest.approx(native)
        assert _to_native_bbox(
            page, (float("nan"), 0.0, 10.0, 20.0)
        ) is None
    finally:
        doc.close()
