"""Extractor attachment of opening provenance is diagnostic-only."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import fitz

from pb_drawing_evidence_binding import DrawingViewType
from pb_hosted_opening_geometry import HostedOpeningEvidence, HostedOpeningSpan
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor
from pb_viewport_segmentation import (
    SegmentedViewport,
    ViewportBoundarySource,
    ViewportSegmentationStatus,
)


def _span() -> HostedOpeningSpan:
    return HostedOpeningSpan(
        page=1,
        host_orientation_deg=0.0,
        jamb_start=(40.0, 80.0),
        jamb_end=(88.0, 80.0),
        span_pt=48.0,
        width_m=None,
        wall_thickness_pt=8.0,
        subtype="window_like",
        evidence_flags=(
            "host_wall_band",
            "aligned_two_face_gap",
            "jamb_boundaries_confirmed",
        ),
        reason="test",
    )


def _viewport() -> SegmentedViewport:
    return SegmentedViewport(
        view_id="view_p1_1",
        page_number=1,
        view_type=DrawingViewType.FLOOR_PLAN.value,
        label="GROUND FLOOR PLAN",
        title_bbox=(20.0, 20.0, 200.0, 36.0),
        bounding_box=(10.0, 10.0, 400.0, 400.0),
        status=ViewportSegmentationStatus.RESOLVED.value,
        boundary_source=ViewportBoundarySource.VECTOR_FRAME.value,
        confidence=1.0,
    )


def _blank_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page(width=400, height=400)
    doc.save(path)
    doc.close()
    return path


def test_extractor_attaches_provenance_shadow_without_mutating_predictions(tmp_path: Path) -> None:
    pdf = _blank_pdf(tmp_path)
    extractor = GenericPlanReaderExtractor()
    with (
        patch(
            "pb_hosted_opening_instance_adapter.authoritative_floor_plan_viewports",
            return_value=[_viewport()],
        ),
        patch(
            "pb_hosted_opening_geometry.resolve_hosted_opening_spans",
            return_value=HostedOpeningEvidence(
                status="found", openings=(_span(),), reason="found"
            ),
        ),
    ):
        preds = extractor.extract_from_pdf(pdf)
    tags = {item.tag for item in preds}
    assert "W1" not in tags
    assert "W2" not in tags
    assert "D1" not in tags
    assert extractor.opening_provenance_shadow["resolutions"]
    assert extractor.opening_provenance_shadow["resolutions"][0]["status"] == "UNBOUND"
    assert extractor.opening_provenance_shadow["resolutions"][0]["height_m"] is None
    assert extractor.opening_provenance_shadow["resolutions"][0]["bound_wall_id"] is None


def test_provenance_exception_does_not_abort_extraction(tmp_path: Path) -> None:
    pdf = _blank_pdf(tmp_path)
    extractor = GenericPlanReaderExtractor()
    with patch(
        "pb_opening_provenance_graph.collect_opening_provenance_shadow_for_doc",
        side_effect=RuntimeError("graph failed"),
    ):
        preds = extractor.extract_from_pdf(pdf)
    assert isinstance(preds, list)
    assert extractor.opening_provenance_shadow["status"] == "abstained"
    assert extractor.opening_provenance_shadow["reason"] == "provenance_exception"


def test_blocked_hosted_shadow_blocks_provenance_without_guessing(tmp_path: Path) -> None:
    pdf = _blank_pdf(tmp_path)
    extractor = GenericPlanReaderExtractor()
    with patch(
        "pb_hosted_opening_instance_adapter.authoritative_floor_plan_viewports",
        return_value=[],
    ):
        preds = extractor.extract_from_pdf(pdf)
    assert isinstance(preds, list)
    assert extractor.hosted_opening_shadow["reason"] == "BLOCKED_ON_VIEWPORT_AUTHORITY"
    assert extractor.opening_provenance_shadow["reason"] == "BLOCKED_ON_VIEWPORT_AUTHORITY"
    assert extractor.opening_provenance_shadow["resolutions"] == []
