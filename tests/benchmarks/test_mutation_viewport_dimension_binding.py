"""F.07 -> F.13 integration tests using only synthetic multi-view sheets."""
from __future__ import annotations

import fitz
import pytest

from pb_dimension_graph_constraint_engine import DimensionOrientation, DimensionObservation
from pb_drawing_evidence_binding import DrawingViewType
from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_viewport_dimension_binding import extract_dimension_evidence_by_viewport
from pb_viewport_segmentation import ViewportSegmentationStatus, segment_page_viewports


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


def _multi_view_dimension_page() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=640, height=420)
    page.draw_rect(fitz.Rect(30, 30, 295, 350))
    page.draw_rect(fitz.Rect(330, 30, 595, 350))

    # Left PLAN: horizontal 3800 dimension with two witnesses.
    page.draw_line((70, 120), (250, 120))
    page.draw_line((70, 95), (70, 145))
    page.draw_line((250, 95), (250, 145))
    page.insert_text((145, 116), "3800", fontsize=10)

    # Right ELEVATION: vertical 2700 dimension with two witnesses.
    page.draw_line((460, 80), (460, 250))
    page.draw_line((435, 80), (485, 80))
    page.draw_line((435, 250), (485, 250))
    page.insert_text((464, 185), "2700", fontsize=10, rotate=90)

    page.insert_text((80, 320), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((390, 320), "NORTH ELEVATION", fontsize=11)
    return _reopen(doc)


def _by_type(viewports):
    return {v.view_type: v for v in viewports}


def test_resolved_viewports_isolate_plan_and_elevation_dimension_evidence():
    doc = _multi_view_dimension_page()
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert all(v.status == ViewportSegmentationStatus.RESOLVED.value for v in viewports)
    by_type = _by_type(viewports)

    result = extract_dimension_evidence_by_viewport(doc[0], page_num=1, viewports=viewports)
    plan_bundle = result.bundles[by_type[DrawingViewType.FLOOR_PLAN.value].view_id]
    elevation_bundle = result.bundles[by_type[DrawingViewType.ELEVATION.value].view_id]

    assert [o.value_m for o in plan_bundle.observations] == pytest.approx([3.8])
    assert [o.value_m for o in elevation_bundle.observations] == pytest.approx([2.7])
    assert plan_bundle.observations[0].view_type == DrawingViewType.FLOOR_PLAN.value
    assert elevation_bundle.observations[0].view_type == DrawingViewType.ELEVATION.value
    assert plan_bundle.observations[0].orientation == DimensionOrientation.HORIZONTAL.value
    assert elevation_bundle.observations[0].orientation == DimensionOrientation.VERTICAL.value
    assert plan_bundle.observations[0].view_id != elevation_bundle.observations[0].view_id
    doc.close()


def test_neighbouring_view_linework_cannot_make_other_view_dimension_ambiguous():
    doc = _multi_view_dimension_page()
    viewports = segment_page_viewports(doc[0], page_number=1)
    result = extract_dimension_evidence_by_viewport(doc[0], page_num=1, viewports=viewports)
    assert len(result.bundles) == 2
    for bundle in result.bundles.values():
        assert len(bundle.observations) == 1
        assert len(bundle.bindings) == 1
        assert bundle.bindings[0].status == "witness_bound"
    doc.close()


def test_derived_viewports_are_not_used_for_authority_sensitive_binding_by_default():
    doc = fitz.open()
    page = doc.new_page(width=600, height=360)
    page.insert_text((80, 320), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((390, 320), "EAST ELEVATION", fontsize=11)
    page.insert_text((100, 100), "4100", fontsize=10)
    page.insert_text((420, 100), "2600", fontsize=10)
    doc = _reopen(doc)
    viewports = segment_page_viewports(doc[0], page_number=1)
    assert all(v.status == ViewportSegmentationStatus.DERIVED.value for v in viewports)

    blocked = extract_dimension_evidence_by_viewport(doc[0], page_num=1, viewports=viewports)
    assert blocked.bundles == {}
    assert len(blocked.skipped_viewports) == 2

    allowed = extract_dimension_evidence_by_viewport(
        doc[0], page_num=1, viewports=viewports, allow_derived=True
    )
    assert len(allowed.bundles) == 2
    values = sorted(o.value_m for bundle in allowed.bundles.values() for o in bundle.observations)
    assert values == pytest.approx([2.6, 4.1])
    doc.close()


def test_ocr_candidate_is_preserved_but_only_assigned_to_unique_resolved_owner():
    doc = _multi_view_dimension_page()
    viewports = segment_page_viewports(doc[0], page_number=1)
    ocr = DimensionObservation(
        dimension_id="ocr-candidate",
        source_page=1,
        bbox=(100, 180, 140, 195),
        raw_text="5200",
        value=5200.0,
        unit="mm",
        authority=MeasurementAuthorityType.AI_DETECTED.value,
        confidence=0.7,
        extraction_method="ocr",
    )
    result = extract_dimension_evidence_by_viewport(
        doc[0], page_num=1, viewports=viewports, ocr_candidates=[ocr]
    )
    plan = _by_type(viewports)[DrawingViewType.FLOOR_PLAN.value]
    elevation = _by_type(viewports)[DrawingViewType.ELEVATION.value]
    assert any(o.dimension_id == "ocr-candidate" for o in result.bundles[plan.view_id].observations)
    assert not any(o.dimension_id == "ocr-candidate" for o in result.bundles[elevation.view_id].observations)
    assert result.unassigned_ocr_ids == []
    # Original candidate is not destructively rewritten.
    assert ocr.view_id == ""
    assert ocr.view_type == DrawingViewType.UNKNOWN.value
    doc.close()


def test_unresolved_viewport_does_not_consume_ocr_candidate():
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((120, 250), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)
    viewports = segment_page_viewports(doc[0], page_number=1)
    ocr = DimensionObservation(
        dimension_id="orphan-ocr",
        source_page=1,
        bbox=(100, 100, 130, 112),
        raw_text="3600",
        value=3600.0,
        unit="mm",
        authority=MeasurementAuthorityType.AI_DETECTED.value,
        confidence=0.6,
        extraction_method="ocr",
    )
    result = extract_dimension_evidence_by_viewport(
        doc[0], page_num=1, viewports=viewports, ocr_candidates=[ocr]
    )
    assert result.bundles == {}
    assert result.unassigned_ocr_ids == ["orphan-ocr"]
    doc.close()
