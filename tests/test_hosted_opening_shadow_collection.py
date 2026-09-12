"""Shadow-only hosted-opening collection: viewport-gated, never live deduction."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import fitz

from pb_drawing_evidence_binding import DrawingViewType
from pb_hosted_opening_geometry import HostedOpeningEvidence, HostedOpeningSpan
from pb_hosted_opening_instance_adapter import (
    SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY,
    collect_hosted_opening_shadow_evidence,
    hosted_opening_span_id,
    hosted_span_to_shadow_record,
)
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor
from pb_viewport_segmentation import (
    SegmentedViewport,
    ViewportBoundarySource,
    ViewportSegmentationStatus,
)


def _span(**overrides) -> HostedOpeningSpan:
    values = dict(
        page=1,
        host_orientation_deg=0.0,
        jamb_start=(40.0, 80.0),
        jamb_end=(88.0, 80.0),
        span_pt=48.0,
        width_m=None,
        wall_thickness_pt=6.0,
        subtype="window_like",
        evidence_flags=("host_wall_band", "aligned_two_face_gap", "jamb_boundaries_confirmed"),
        reason="test hosted span",
    )
    values.update(overrides)
    return HostedOpeningSpan(**values)


def _viewport(
    *,
    view_type: str = DrawingViewType.FLOOR_PLAN.value,
    status: str = ViewportSegmentationStatus.RESOLVED.value,
    bbox: tuple[float, float, float, float] | None = (10.0, 10.0, 400.0, 400.0),
) -> SegmentedViewport:
    return SegmentedViewport(
        view_id="view_p1_1",
        page_number=1,
        view_type=view_type,
        label="GROUND FLOOR PLAN",
        title_bbox=(20.0, 20.0, 200.0, 36.0),
        bounding_box=bbox,
        status=status,
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


def _quarter(page: fitz.Page, origin: tuple[float, float], radius: float) -> None:
    x, y = origin
    page.draw_bezier(
        (x, y),
        (x, y + 0.55 * radius),
        (x - 0.45 * radius, y + radius),
        (x - radius, y + radius),
        color=(0, 0, 0),
        width=0.7,
    )


def _swing_and_callout_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "swing_callout.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 36), "GROUND FLOOR PLAN  SCALE 1:100", fontsize=11)
    page.insert_text(
        (40, 54),
        "1,000mm x 2,100mm timber batten door with 3 nos. butt hinges",
        fontsize=9,
    )
    for i in range(12):
        _quarter(page, (80 + (i % 8) * 28, 90 + (i // 8) * 28), 16)
    _quarter(page, (120, 320), 40)
    doc.save(path)
    doc.close()
    return path


def test_shadow_record_omits_wall_binding_and_height() -> None:
    record = hosted_span_to_shadow_record(_span(width_m=1.72))
    assert record is not None
    assert record["span_id"] == hosted_opening_span_id(_span(width_m=1.72))
    assert record["width_m"] == 1.72
    assert "height_m" not in record
    assert "bound_wall_id" not in record
    assert "W1" not in record["span_id"]


def test_arc_alone_span_is_not_shadowed() -> None:
    assert (
        hosted_span_to_shadow_record(
            _span(evidence_flags=("jamb_anchored_door_swing",), subtype="door_like")
        )
        is None
    )


def test_no_authoritative_viewport_abstains_without_calling_detector() -> None:
    doc = fitz.open()
    doc.new_page()
    with (
        patch(
            "pb_hosted_opening_instance_adapter.authoritative_floor_plan_viewports",
            return_value=[],
        ),
        patch("pb_hosted_opening_geometry.resolve_hosted_opening_spans") as detect,
    ):
        shadow = collect_hosted_opening_shadow_evidence(doc, [0])
    doc.close()
    detect.assert_not_called()
    assert shadow["status"] == "abstained"
    assert shadow["reason"] == SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY
    assert shadow["evidence"] == []


def test_resolved_floor_plan_viewport_allows_shadow_evidence() -> None:
    doc = fitz.open()
    doc.new_page()
    span = _span()
    with (
        patch(
            "pb_hosted_opening_instance_adapter.authoritative_floor_plan_viewports",
            return_value=[_viewport()],
        ),
        patch(
            "pb_hosted_opening_geometry.resolve_hosted_opening_spans",
            return_value=HostedOpeningEvidence(
                status="found", openings=(span,), reason="found"
            ),
        ) as detect,
    ):
        shadow = collect_hosted_opening_shadow_evidence(doc, [0])
    doc.close()
    detect.assert_called_once()
    assert detect.call_args.kwargs["viewport_bbox"] == (10.0, 10.0, 400.0, 400.0)
    assert detect.call_args.kwargs["scale_authority"] is None
    assert shadow["status"] == "found"
    assert shadow["evidence"][0]["span_id"] == hosted_opening_span_id(span)


def test_derived_or_elevation_viewport_is_not_authority() -> None:
    doc = fitz.open()
    page = doc.new_page()
    derived = _viewport(status=ViewportSegmentationStatus.DERIVED.value)
    elevation = _viewport(view_type=DrawingViewType.ELEVATION.value)
    with patch(
        "pb_viewport_segmentation.segment_page_viewports",
        return_value=[derived, elevation],
    ):
        assert authoritative_floor_plan_viewports_via_public(page) == []
        shadow = collect_hosted_opening_shadow_evidence(doc, [0])
    doc.close()
    assert shadow["reason"] == SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY


def authoritative_floor_plan_viewports_via_public(page):
    from pb_hosted_opening_instance_adapter import authoritative_floor_plan_viewports

    return authoritative_floor_plan_viewports(page, page_number=1)


def test_extractor_does_not_mutate_predictions_when_shadow_found(tmp_path: Path) -> None:
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
    assert not any(str(item.tag).startswith("hosted-span-") for item in preds)
    assert extractor.hosted_opening_shadow["status"] == "found"
    assert extractor.hosted_opening_shadow["evidence"]


def test_detector_exception_does_not_abort_extraction(tmp_path: Path) -> None:
    pdf = _blank_pdf(tmp_path)
    extractor = GenericPlanReaderExtractor()
    with patch(
        "pb_hosted_opening_instance_adapter.collect_hosted_opening_shadow_evidence",
        side_effect=RuntimeError("detector failed"),
    ):
        preds = extractor.extract_from_pdf(pdf)
    assert isinstance(preds, list)
    assert extractor.hosted_opening_shadow["status"] == "abstained"
    assert extractor.hosted_opening_shadow["reason"] == "detector_exception"


def test_existing_d1_path_unchanged_when_shadow_abstains(tmp_path: Path) -> None:
    pdf = _swing_and_callout_pdf(tmp_path)
    extractor = GenericPlanReaderExtractor()
    with patch(
        "pb_hosted_opening_instance_adapter.authoritative_floor_plan_viewports",
        return_value=[],
    ):
        preds = {item.tag: item for item in extractor.extract_from_pdf(pdf)}
    assert preds["D1"].quantity == 1.0
    assert preds["D1"].dimensions == [1000.0, 2100.0]
    assert "W1" not in preds
    assert "W2" not in preds
    assert extractor.hosted_opening_shadow["reason"] == SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY
