"""Real-PDF F.07 floor-plan authority regressions.

Fixture filenames identify official source drawings for reviewers.
Production segmentation never branches on those names, page numbers, or
expected quantities.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_drawing_evidence_binding import DrawingViewType
from pb_hosted_opening_instance_adapter import authoritative_floor_plan_viewports
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor
from pb_viewport_segmentation import (
    ViewportBoundarySource,
    ViewportSegmentationStatus,
    extract_view_title_anchors,
    extract_vector_frames,
    calibrate_viewport_layout,
    segment_page_viewports,
)

_REPO = Path(__file__).resolve().parents[1]
_SOURCES = _REPO / "benchmarks" / "sources"

_KSTVET = _SOURCES / "1727358888238-bq-nd-drawing.pdf"
_MURERA = _SOURCES / "1785347143869-bqs-drawings.pdf"
_GHAZI = _SOURCES / "1739211305954-tender-document-for-construction-of-science-laboratory-at-ghazi-primary-school.pdf"
_UMMA = _SOURCES / "umma-university-hostels-builders-work.pdf"
_LAMU = _SOURCES / "lamu-ishakani-ecd-classrooms-boq.pdf"


def _require(pdf: Path) -> Path:
    if not pdf.exists():
        pytest.skip(f"official source PDF not present: {pdf}")
    return pdf


def _floor_plans(viewports):
    return [v for v in viewports if v.view_type == DrawingViewType.FLOOR_PLAN.value]


def test_kstvet_ground_floor_plan_stays_unframed_ambiguous() -> None:
    doc = fitz.open(str(_require(_KSTVET)))
    page = doc[53]
    viewports = segment_page_viewports(page, page_number=54)
    plans = _floor_plans(viewports)
    assert len(plans) == 1
    plan = plans[0]
    assert plan.label.upper() == "GROUND FLOOR PLAN"
    assert plan.status == ViewportSegmentationStatus.AMBIGUOUS.value
    assert plan.bounding_box is None
    assert authoritative_floor_plan_viewports(page, page_number=54) == []
    doc.close()


def test_lamu_titled_plan_resolves_only_when_native_quad_owns_the_title() -> None:
    doc = fitz.open(str(_require(_LAMU)))
    page_41 = doc[40]
    page_42 = doc[41]
    plan_41 = _floor_plans(segment_page_viewports(page_41, page_number=41))
    plan_42 = _floor_plans(segment_page_viewports(page_42, page_number=42))
    assert len(plan_41) == 1 and len(plan_42) == 1
    assert plan_41[0].label.upper() == "GROUND FLOOR PLAN"
    assert plan_42[0].label.upper() == "GROUND FLOOR PLAN"
    assert plan_42[0].status == ViewportSegmentationStatus.DERIVED.value
    assert plan_42[0].boundary_source == ViewportBoundarySource.TITLE_PARTITION.value
    assert authoritative_floor_plan_viewports(page_42, page_number=42) == []
    assert plan_41[0].status == ViewportSegmentationStatus.RESOLVED.value
    assert plan_41[0].boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
    assert plan_41[0].bounding_box == pytest.approx((200.5, 110.1, 654.1, 342.6), abs=2.0)
    assert authoritative_floor_plan_viewports(page_41, page_number=41) == plan_41
    doc.close()


def test_murera_ghazi_umma_have_no_resolved_floor_plan_without_title_evidence() -> None:
    for pdf in (_require(_MURERA), _require(_GHAZI), _require(_UMMA)):
        doc = fitz.open(str(pdf))
        floor_titles = []
        resolved = []
        for index in range(len(doc)):
            page = doc[index]
            floor_titles.extend(
                anchor for anchor in extract_view_title_anchors(page)
                if anchor.view_type == DrawingViewType.FLOOR_PLAN.value
            )
            resolved.extend(authoritative_floor_plan_viewports(page, page_number=index + 1))
        assert floor_titles == []
        assert resolved == []
        doc.close()


def test_lamu_resolved_shadow_does_not_enter_live_predictions() -> None:
    extractor = GenericPlanReaderExtractor()
    preds = extractor.extract_from_pdf(_require(_LAMU))
    assert not any(str(item.tag).startswith("hosted-span-") for item in preds)
    assert extractor.hosted_opening_shadow.get("status") == "found"
    for row in extractor.hosted_opening_shadow.get("evidence") or []:
        assert row.get("width_m") is None
        assert str(row.get("span_id", "")).startswith("hosted-span-")
    resolutions = extractor.opening_provenance_shadow.get("resolutions") or []
    assert resolutions
    assert all(item.get("status") == "UNBOUND" for item in resolutions)
    assert all(item.get("height_m") is None for item in resolutions)
    assert all(item.get("bound_wall_id") is None for item in resolutions)
    assert all(item.get("resolved_type_mark") is None for item in resolutions)


def test_native_frame_extractors_do_not_mint_page_border_frames() -> None:
    doc = fitz.open(str(_require(_LAMU)))
    page = doc[40]
    calibration = calibrate_viewport_layout(page)
    frames = extract_vector_frames(page, calibration)
    page_area = calibration.page_width_pt * calibration.page_height_pt
    assert frames
    assert all((frame[2] - frame[0]) * (frame[3] - frame[1]) / page_area < 0.95 for frame in frames)
    doc.close()
