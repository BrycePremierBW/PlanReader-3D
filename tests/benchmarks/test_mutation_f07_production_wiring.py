"""Synthetic mutation/red-team tests for F.07 production wall-thickness wiring.

No benchmark identity, source path, or expected tender quantity is used here.
"""
from __future__ import annotations

import fitz
import pytest

from pb_dimension_chain_evidence_extractor import (
    extract_dimension_chains_from_page,
    resolve_corroborated_wall_thickness_m,
)
from pb_dimension_graph_constraint_engine import DimensionObservation
from pb_drawing_evidence_binding import DrawingViewType
from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_viewport_dimension_binding import extract_dimension_evidence_by_viewport
from pb_viewport_segmentation import (
    SegmentedViewport,
    ViewportBoundarySource,
    ViewportSegmentationStatus,
)


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


def _framed_plan_and_elevation() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=720, height=460)
    page.draw_rect(fitz.Rect(20, 20, 330, 400))
    page.draw_rect(fitz.Rect(380, 20, 700, 400))

    # Two independent plan rows corroborate a 150 mm wall bracket.
    page.insert_text((70, 120), "150 5,700 150", fontsize=10)
    page.insert_text((70, 165), "150 7,100 150", fontsize=10)
    page.insert_text((85, 365), "GROUND FLOOR PLAN", fontsize=11)

    # A different, equally plausible-looking bracket exists in the elevation.
    # F.07 must keep it out of the floor-plan wall-thickness consumer.
    page.insert_text((435, 120), "300 2,900 300", fontsize=10)
    page.insert_text((435, 165), "300 3,400 300", fontsize=10)
    page.insert_text((455, 365), "WEST ELEVATION", fontsize=11)
    return _reopen(doc)


def test_production_page_marker_uses_only_resolved_floor_plan_chains():
    doc = _framed_plan_and_elevation()
    chains = extract_dimension_chains_from_page(doc[0], page_num=1, view_id="page_1")

    assert chains
    assert {chain.view_id for chain in chains} != {"page_1"}
    assert all(
        observation.view_type == DrawingViewType.FLOOR_PLAN.value
        for chain in chains
        for observation in chain.observations
    )
    assert resolve_corroborated_wall_thickness_m(chains) == pytest.approx(0.15)
    assert all(
        observation.value_m != pytest.approx(0.3)
        for chain in chains
        for observation in chain.observations
    )
    doc.close()


def test_direct_legacy_call_remains_page_wide_for_backwards_compatibility():
    doc = _framed_plan_and_elevation()
    chains = extract_dimension_chains_from_page(doc[0], page_num=1, view_id="")
    values = [round(o.value_m, 3) for chain in chains for o in chain.observations]
    assert 0.15 in values
    assert 0.3 in values
    doc.close()


def test_no_resolved_viewport_preserves_proven_page_wide_fallback():
    doc = fitz.open()
    page = doc.new_page(width=500, height=360)
    page.insert_text((70, 100), "150 5,700 150", fontsize=10)
    page.insert_text((70, 145), "150 7,100 150", fontsize=10)
    page.insert_text((100, 320), "GROUND FLOOR PLAN", fontsize=11)
    doc = _reopen(doc)

    production = extract_dimension_chains_from_page(doc[0], page_num=1, view_id="page_1")
    legacy = extract_dimension_chains_from_page(doc[0], page_num=1, view_id="")
    production_values = [[round(o.value_m, 3) for o in c.observations] for c in production]
    legacy_values = [[round(o.value_m, 3) for o in c.observations] for c in legacy]
    assert production_values == legacy_values
    assert resolve_corroborated_wall_thickness_m(production) == pytest.approx(0.15)
    doc.close()


def test_resolved_non_plan_view_does_not_become_wall_thickness_authority():
    doc = fitz.open()
    page = doc.new_page(width=500, height=360)
    page.draw_rect(fitz.Rect(30, 30, 470, 320))
    page.insert_text((80, 100), "150 5,700 150", fontsize=10)
    page.insert_text((80, 145), "150 7,100 150", fontsize=10)
    page.insert_text((180, 290), "NORTH ELEVATION", fontsize=11)
    doc = _reopen(doc)

    chains = extract_dimension_chains_from_page(doc[0], page_num=1, view_id="page_1")
    assert chains == []
    assert resolve_corroborated_wall_thickness_m(chains) is None
    doc.close()


def _manual_plan_viewport() -> SegmentedViewport:
    return SegmentedViewport(
        view_id="plan_view",
        page_number=1,
        view_type=DrawingViewType.FLOOR_PLAN.value,
        label="GROUND FLOOR PLAN",
        title_bbox=(20.0, 80.0, 90.0, 95.0),
        bounding_box=(0.0, 0.0, 100.0, 100.0),
        status=ViewportSegmentationStatus.RESOLVED.value,
        boundary_source=ViewportBoundarySource.VECTOR_FRAME.value,
        confidence=1.0,
    )


def test_vector_segment_crossing_viewport_boundary_is_not_owned_by_midpoint():
    doc = fitz.open()
    page = doc.new_page(width=220, height=140)
    # Midpoint x=80 lies inside the viewport, but the segment ends outside.
    page.draw_line((20, 50), (140, 50))
    doc = _reopen(doc)

    result = extract_dimension_evidence_by_viewport(
        doc[0], page_num=1, viewports=[_manual_plan_viewport()]
    )
    assert result.bundles["plan_view"].observed_geometry == []
    doc.close()


def test_boundary_straddling_ocr_bbox_remains_unassigned():
    doc = fitz.open()
    page = doc.new_page(width=220, height=140)
    doc = _reopen(doc)
    candidate = DimensionObservation(
        dimension_id="boundary-ocr",
        source_page=1,
        bbox=(90.0, 40.0, 110.0, 55.0),
        raw_text="4200",
        value=4200.0,
        unit="mm",
        authority=MeasurementAuthorityType.AI_DETECTED.value,
        confidence=0.7,
        extraction_method="ocr",
    )

    result = extract_dimension_evidence_by_viewport(
        doc[0],
        page_num=1,
        viewports=[_manual_plan_viewport()],
        ocr_candidates=[candidate],
    )
    assert result.unassigned_ocr_ids == ["boundary-ocr"]
    assert all(
        observation.dimension_id != "boundary-ocr"
        for observation in result.bundles["plan_view"].observations
    )
    doc.close()
