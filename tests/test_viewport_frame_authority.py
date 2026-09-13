"""Synthetic F.07 frame-authority tests.

All drawings are synthetic. Production code is not allowed to branch on
project name, benchmark id, page number, or expected quantity.
"""
from __future__ import annotations

import fitz
import pytest

from pb_drawing_evidence_binding import DrawingViewType
from pb_hosted_opening_instance_adapter import authoritative_floor_plan_viewports
from pb_viewport_segmentation import (
    ViewportBoundarySource,
    ViewportSegmentationStatus,
    calibrate_viewport_layout,
    extract_vector_frames,
    segment_page_viewports,
    validate_non_overlapping_viewports,
)


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


def _draw_closed_line_rect(page: fitz.Page, rect: fitz.Rect) -> None:
    shape = page.new_shape()
    shape.draw_line((rect.x0, rect.y0), (rect.x1, rect.y0))
    shape.draw_line((rect.x1, rect.y0), (rect.x1, rect.y1))
    shape.draw_line((rect.x1, rect.y1), (rect.x0, rect.y1))
    shape.draw_line((rect.x0, rect.y1), (rect.x0, rect.y0))
    shape.finish(color=(0, 0, 0), width=1, closePath=False)
    shape.commit()


def _one_framed_plan(
    *,
    kind: str = "re",
    dx: float = 0.0,
    dy: float = 0.0,
    scale: float = 1.0,
    page_width: float = 520,
    page_height: float = 400,
    title_inside: bool = True,
    title_gap: float | None = None,
    extra_title: str | None = None,
    extra_title_xy: tuple[float, float] | None = None,
) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=page_width * scale, height=page_height * scale)
    frame = fitz.Rect(
        (40 + dx) * scale,
        (30 + dy) * scale,
        (360 + dx) * scale,
        (260 + dy) * scale,
    )
    if kind == "re":
        page.draw_rect(frame)
    elif kind == "lines":
        _draw_closed_line_rect(page, frame)
    elif kind == "quad":
        page.draw_quad(fitz.Quad(frame.tl, frame.tr, frame.bl, frame.br), color=(0, 0, 0), width=1)
    else:
        raise ValueError(kind)
    page.draw_line(
        ((70 + dx) * scale, (80 + dy) * scale),
        ((300 + dx) * scale, (80 + dy) * scale),
    )
    page.draw_line(
        ((70 + dx) * scale, (80 + dy) * scale),
        ((70 + dx) * scale, (200 + dy) * scale),
    )
    fontsize = max(8.0, 11.0 * scale)
    if title_inside:
        page.insert_text(((80 + dx) * scale, (240 + dy) * scale), "GROUND FLOOR PLAN", fontsize=fontsize)
    else:
        gap = 24.0 if title_gap is None else title_gap
        page.insert_text(
            ((80 + dx) * scale, (260 + dy + gap) * scale + fontsize),
            "GROUND FLOOR PLAN",
            fontsize=fontsize,
        )
    if extra_title and extra_title_xy:
        page.insert_text(
            ((extra_title_xy[0] + dx) * scale, (extra_title_xy[1] + dy) * scale),
            extra_title,
            fontsize=fontsize,
        )
    return _reopen(doc)


def _floor_plans(viewports):
    return [v for v in viewports if v.view_type == DrawingViewType.FLOOR_PLAN.value]


def _authority_signature(viewports):
    return sorted(
        (
            v.view_type,
            v.status,
            v.boundary_source,
            None
            if v.bounding_box is None
            else round((v.bounding_box[2] - v.bounding_box[0]) / max(v.bounding_box[3] - v.bounding_box[1], 1e-6), 3),
        )
        for v in viewports
    )


@pytest.mark.parametrize("kind", ["re", "lines", "quad"])
def test_one_floor_plan_title_and_one_enclosing_frame_is_resolved(kind: str) -> None:
    doc = _one_framed_plan(kind=kind)
    viewports = segment_page_viewports(doc[0], page_number=1)
    plans = _floor_plans(viewports)
    assert len(plans) == 1
    plan = plans[0]
    assert plan.status == ViewportSegmentationStatus.RESOLVED.value
    assert plan.boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
    assert plan.bounding_box == pytest.approx((40, 30, 360, 260), abs=1.5)
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == [plan]
    doc.close()


def test_title_immediately_below_unique_frame_is_resolved() -> None:
    doc = _one_framed_plan(title_inside=False, title_gap=28, page_height=420)
    viewports = segment_page_viewports(doc[0], page_number=1)
    plan = _floor_plans(viewports)[0]
    assert plan.status == ViewportSegmentationStatus.RESOLVED.value
    assert plan.bounding_box == pytest.approx((40, 30, 360, 260), abs=1.5)
    doc.close()


def test_title_too_far_below_frame_is_not_resolved() -> None:
    doc = _one_framed_plan(title_inside=False, title_gap=160, page_height=520)
    plan = _floor_plans(segment_page_viewports(doc[0], page_number=1))[0]
    assert plan.status != ViewportSegmentationStatus.RESOLVED.value
    assert plan.bounding_box is None or plan.status == ViewportSegmentationStatus.DERIVED.value
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def test_page_border_is_not_a_viewport_frame() -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.draw_rect(fitz.Rect(2, 2, 398, 298))
    page.insert_text((80, 160), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert viewports
    assert all(v.status != ViewportSegmentationStatus.RESOLVED.value for v in viewports)
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def test_crop_box_near_page_edges_is_rejected() -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.draw_rect(fitz.Rect(4, 5, 396, 294))
    page.insert_text((90, 160), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def test_title_block_panel_is_not_viewport_authority() -> None:
    doc = fitz.open()
    page = doc.new_page(width=640, height=420)
    page.draw_rect(fitz.Rect(430, 270, 620, 400))
    page.insert_text((440, 295), "DRAWING TITLE", fontsize=8)
    page.insert_text((440, 320), "GROUND FLOOR PLAN", fontsize=10)
    page.insert_text((440, 350), "DRAWING NO", fontsize=8)
    doc = _reopen(doc)
    plan = _floor_plans(segment_page_viewports(doc[0], page_number=1))[0]
    assert plan.status != ViewportSegmentationStatus.RESOLVED.value
    assert plan.bounding_box is None
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def test_schedule_table_frame_is_not_floor_plan_authority() -> None:
    doc = fitz.open()
    page = doc.new_page(width=720, height=480)
    page.draw_rect(fitz.Rect(40, 30, 520, 390))
    for col in range(4):
        for row in range(3):
            page.draw_rect(fitz.Rect(55 + col * 110, 50 + row * 90, 150 + col * 110, 125 + row * 90))
    page.insert_text((80, 370), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)
    plan = _floor_plans(segment_page_viewports(doc[0], page_number=1))[0]
    assert plan.status != ViewportSegmentationStatus.RESOLVED.value
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def test_elevation_frame_does_not_own_distant_floor_plan_title() -> None:
    doc = fitz.open()
    page = doc.new_page(width=640, height=400)
    page.draw_rect(fitz.Rect(330, 30, 600, 300))
    page.insert_text((360, 280), "NORTH ELEVATION", fontsize=11)
    page.insert_text((40, 80), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)
    viewports = segment_page_viewports(doc[0], page_number=1)
    by_type = {v.view_type: v for v in viewports}
    assert by_type[DrawingViewType.ELEVATION.value].status == ViewportSegmentationStatus.RESOLVED.value
    plan = by_type[DrawingViewType.FLOOR_PLAN.value]
    assert plan.status != ViewportSegmentationStatus.RESOLVED.value
    assert plan.bounding_box is None
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def test_two_competing_equivalent_frames_are_ambiguous() -> None:
    doc = fitz.open()
    page = doc.new_page(width=520, height=400)
    page.draw_rect(fitz.Rect(30, 30, 420, 330))
    page.draw_rect(fitz.Rect(55, 50, 395, 305))
    page.insert_text((90, 300), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)
    plan = _floor_plans(segment_page_viewports(doc[0], page_number=1))[0]
    assert plan.status == ViewportSegmentationStatus.AMBIGUOUS.value
    assert plan.bounding_box is None
    assert "compete" in " ".join(plan.notes)
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def test_title_outside_frame_ownership_is_not_resolved() -> None:
    doc = fitz.open()
    page = doc.new_page(width=520, height=400)
    page.draw_rect(fitz.Rect(280, 30, 490, 260))
    page.insert_text((40, 80), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)
    plan = _floor_plans(segment_page_viewports(doc[0], page_number=1))[0]
    assert plan.status == ViewportSegmentationStatus.UNSUPPORTED.value
    assert plan.bounding_box is None
    doc.close()


def test_decorative_and_room_rectangles_do_not_create_authority() -> None:
    doc = fitz.open()
    page = doc.new_page(width=520, height=400)
    page.draw_rect(fitz.Rect(20, 20, 48, 48))
    page.draw_rect(fitz.Rect(90, 70, 170, 140))
    page.insert_text((80, 320), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)
    plan = _floor_plans(segment_page_viewports(doc[0], page_number=1))[0]
    assert plan.status == ViewportSegmentationStatus.UNSUPPORTED.value
    assert plan.bounding_box is None
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def test_drawing_without_floor_plan_title_has_no_floor_plan_viewport() -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.draw_rect(fitz.Rect(30, 30, 360, 250))
    page.insert_text((80, 220), "CLASSROOM 01", fontsize=11)
    doc = _reopen(doc)
    assert _floor_plans(segment_page_viewports(doc[0], page_number=1)) == []
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


def test_nested_title_band_does_not_compete_with_enclosing_frame() -> None:
    doc = fitz.open()
    page = doc.new_page(width=520, height=400)
    page.draw_rect(fitz.Rect(40, 30, 400, 260))
    page.draw_rect(fitz.Rect(40, 230, 400, 260))
    page.insert_text((90, 290), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)
    plan = _floor_plans(segment_page_viewports(doc[0], page_number=1))[0]
    assert plan.status == ViewportSegmentationStatus.RESOLVED.value
    assert plan.bounding_box == pytest.approx((40, 30, 400, 260), abs=1.5)
    doc.close()


def test_derived_partition_is_still_not_hosted_authority() -> None:
    doc = fitz.open()
    page = doc.new_page(width=600, height=360)
    page.insert_text((80, 320), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((390, 320), "EAST ELEVATION", fontsize=11)
    doc = _reopen(doc)
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert all(v.status == ViewportSegmentationStatus.DERIVED.value for v in viewports)
    assert authoritative_floor_plan_viewports(doc[0], page_number=1) == []
    doc.close()


@pytest.mark.parametrize("scale", [0.5, 1.35, 2.0])
@pytest.mark.parametrize("kind", ["re", "lines"])
def test_scale_metamorphic_keeps_frame_authority(kind: str, scale: float) -> None:
    base = _one_framed_plan(kind=kind)
    scaled = _one_framed_plan(kind=kind, scale=scale, page_width=520, page_height=420)
    assert _authority_signature(segment_page_viewports(base[0], page_number=1)) == _authority_signature(
        segment_page_viewports(scaled[0], page_number=1)
    )
    base.close()
    scaled.close()


def test_translation_and_page_offset_keep_frame_authority() -> None:
    base = _one_framed_plan()
    moved = _one_framed_plan(dx=36, dy=22, page_width=600, page_height=460)
    assert _authority_signature(segment_page_viewports(base[0], page_number=1)) == _authority_signature(
        segment_page_viewports(moved[0], page_number=1)
    )
    base.close()
    moved.close()


def test_rotated_sheet_layout_keeps_title_frame_ownership() -> None:
    portrait = _one_framed_plan(page_width=420, page_height=560)
    landscape = _one_framed_plan(dx=80, dy=10, page_width=640, page_height=420)
    assert _authority_signature(segment_page_viewports(portrait[0], page_number=1)) == _authority_signature(
        segment_page_viewports(landscape[0], page_number=1)
    )
    portrait.close()
    landscape.close()


class _Point:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


class _Rect:
    def __init__(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1


class _FakePage:
    def __init__(self, width: float, height: float, drawings: list[dict]) -> None:
        self.rect = type("R", (), {"width": width, "height": height})()
        self._drawings = drawings

    def get_drawings(self):
        return self._drawings

    def get_text(self, mode: str = "dict"):
        if mode == "words":
            return [(10, 10, 22, 22, "A", 0, 0, 0)]
        if mode == "dict":
            return {"blocks": []}
        return []


def test_extract_vector_frames_accepts_quad_and_four_line_path() -> None:
    quad_page = _FakePage(
        500,
        400,
        [{"items": [("qu", _Rect(40, 30, 360, 260))]}],
    )
    line_page = _FakePage(
        500,
        400,
        [{
            "items": [
                ("l", _Point(40, 30), _Point(360, 30)),
                ("l", _Point(360, 30), _Point(360, 260)),
                ("l", _Point(360, 260), _Point(40, 260)),
                ("l", _Point(40, 260), _Point(40, 30)),
            ]
        }],
    )
    quad_frames = extract_vector_frames(quad_page, calibrate_viewport_layout(quad_page))
    line_frames = extract_vector_frames(line_page, calibrate_viewport_layout(line_page))
    assert len(quad_frames) == 1
    assert quad_frames[0] == pytest.approx((40.0, 30.0, 360.0, 260.0))
    assert len(line_frames) == 1
    assert line_frames[0] == pytest.approx((40.0, 30.0, 360.0, 260.0))


def test_extract_vector_frames_does_not_assemble_loose_wall_lines() -> None:
    page = _FakePage(
        500,
        400,
        [
            {"items": [("l", _Point(40, 30), _Point(360, 30))]},
            {"items": [("l", _Point(360, 30), _Point(360, 260))]},
            {"items": [("l", _Point(360, 260), _Point(40, 260))]},
            {"items": [("l", _Point(40, 260), _Point(40, 30))]},
        ],
    )
    assert extract_vector_frames(page, calibrate_viewport_layout(page)) == []


def test_two_framed_views_remain_non_overlapping() -> None:
    doc = fitz.open()
    page = doc.new_page(width=640, height=420)
    page.draw_rect(fitz.Rect(30, 30, 295, 350))
    page.draw_rect(fitz.Rect(330, 30, 595, 350))
    page.insert_text((80, 320), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((390, 320), "NORTH ELEVATION", fontsize=11)
    doc = _reopen(doc)
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert validate_non_overlapping_viewports(viewports)
    assert {v.status for v in viewports} == {ViewportSegmentationStatus.RESOLVED.value}
    doc.close()
