"""Viewport-scoped scale binding: mixed-scale sheets, fail-closed, no gold.

All drawings are synthetic. No named development-benchmark projects, gold
quantities, or expected takeoff totals are used.

v2: ordinary viewport-owned textual ratios stay non-FIRM. This module must
not invent graphic SCALE_BAR evidence. The unmodified authority mapper still
makes independently corroborated VALID SCALE_BAR calibrations FIRM.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

import fitz
import pytest

from pb_drawing_evidence_binding import DrawingViewType
from pb_geometry_takeoff_model import AuthorityStatus
from pb_measurement_input_authority import (
    resolve_linear_measurement_input,
    scale_calibration_fingerprint,
)
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceResolutionStatus,
    ViewportEvidence,
    ViewportResolutionStatus,
)
from pb_migration_provider_envelope import ProviderContext
from pb_page_scale_calibration_authority import (
    ScaleCalibrationStatus,
    ScaleSourceReading,
    ScaleSourceType,
    check_calibration_freshness,
    measurement_authority_for_page_scale,
    resolve_page_scale_calibration,
)
from pb_viewport_scale_binding import (
    ViewportScaleBinding,
    ViewportScaleBindingError,
    assert_binding_matches_viewport,
    bind_page_viewport_scales,
    bind_viewport_scale,
    classify_viewport_scale_source,
    scale_representation_mismatch_reason,
    viewport_evidence_with_bound_scale,
    viewport_scale_readings,
)
from pb_viewport_segmentation import (
    SegmentedViewport,
    ViewportBoundarySource,
    ViewportSegmentationStatus,
    segment_page_viewports,
)

MODULE_SOURCE = Path("pb_viewport_scale_binding.py").read_text(encoding="utf-8")
SHA = "b" * 64


def _viewport(
    *,
    view_id: str = "view_p1_1",
    page_number: int = 1,
    label: str = "GROUND FLOOR PLAN",
    view_type: str = DrawingViewType.FLOOR_PLAN.value,
    scale_raw: str | None = "SCALE 1:100",
    scale_denominator: float | None = 100.0,
    scale_conflict: bool = False,
    status: str = ViewportSegmentationStatus.RESOLVED.value,
    bbox: tuple[float, float, float, float] | None = (30.0, 30.0, 295.0, 350.0),
    notes: list[str] | None = None,
    confidence: float = 1.0,
) -> SegmentedViewport:
    return SegmentedViewport(
        view_id=view_id,
        page_number=page_number,
        view_type=view_type,
        label=label,
        title_bbox=(80.0, 310.0, 240.0, 330.0),
        bounding_box=bbox,
        status=status,
        boundary_source=ViewportBoundarySource.VECTOR_FRAME.value,
        confidence=confidence,
        scale_raw=scale_raw,
        scale_denominator=scale_denominator,
        scale_conflict=scale_conflict,
        notes=list(notes or []),
    )


def _mixed_viewports() -> tuple[SegmentedViewport, SegmentedViewport]:
    plan = _viewport(view_id="view_p1_1", scale_raw="SCALE 1:100", scale_denominator=100.0)
    elev = _viewport(
        view_id="view_p1_2",
        label="NORTH ELEVATION",
        view_type=DrawingViewType.ELEVATION.value,
        scale_raw="SCALE 1:50",
        scale_denominator=50.0,
        bbox=(330.0, 30.0, 595.0, 350.0),
    )
    return plan, elev


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


def _mixed_scale_sheet(*, dx: float = 0.0, dy: float = 0.0) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=640, height=420)
    page.draw_rect(fitz.Rect(30 + dx, 30 + dy, 295 + dx, 350 + dy))
    page.draw_rect(fitz.Rect(330 + dx, 30 + dy, 595 + dx, 350 + dy))
    page.insert_text((80 + dx, 320 + dy), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((92 + dx, 338 + dy), "SCALE 1:100", fontsize=9)
    page.insert_text((390 + dx, 320 + dy), "NORTH ELEVATION", fontsize=11)
    page.insert_text((405 + dx, 338 + dy), "SCALE 1:50", fontsize=9)
    return _reopen(doc)


def _evidence(viewport_id: str, bbox: tuple[float, float, float, float], *, resolved_scale_id: str | None = None) -> ViewportEvidence:
    return ViewportEvidence(
        viewport_id=viewport_id,
        document_id="doc-1",
        page_id="page-1",
        bbox=bbox,
        view_type="floor_plan",
        status=ViewportResolutionStatus.RESOLVED,
        evidence_ids=("ev-plan",),
        resolved_scale_id=resolved_scale_id,
        confidence=1.0,
    )


def _provider_context(*viewport_ids: str) -> ProviderContext:
    owned = tuple(viewport_ids)
    return ProviderContext(
        run_id="run-1",
        workspace_id="ws-1",
        project_id="synthetic-workspace",
        document_id="doc-1",
        source_sha256=SHA,
        revision_id="R1",
        current_revision_id="R1",
        selected_pages=(0,),
        owned_viewport_ids=owned,
        evidence_snapshot_id="ev-snap-1",
        owned_page_numbers=(1,),
        viewport_page_ownership=tuple((viewport_id, 1) for viewport_id in owned),
    )


def _document(*evidence_ids: str) -> DocumentEvidence:
    return DocumentEvidence(
        document_id="doc-1",
        source_sha256=SHA,
        page_count=1,
        page_ids=("page-1",),
        evidence_ids=tuple(evidence_ids) or ("ev-plan", "ev-elev"),
        producer="test",
        producer_version="1",
    )


def _entity(entity_id: str, evidence_id: str) -> EntityEvidence:
    return EntityEvidence(
        candidate_entity_id=entity_id,
        candidate_type="wall",
        evidence_ids=(evidence_id,),
        status=EvidenceResolutionStatus.CORROBORATED,
        confidence=1.0,
    )


# ---------------------------------------------------------------------------
# P1 — textual viewport scale is never SCALE_BAR / never FIRM
# ---------------------------------------------------------------------------


def test_isolated_scale_callout_is_textual_not_scale_bar_or_inferred() -> None:
    source = classify_viewport_scale_source(label="GROUND FLOOR PLAN", scale_raw="SCALE 1:100")
    assert source == ScaleSourceType.TITLE_BLOCK.value
    assert source != ScaleSourceType.SCALE_BAR.value
    assert source != ScaleSourceType.INFERRED.value


def test_plain_viewport_scale_text_is_not_firm() -> None:
    binding = bind_viewport_scale(_viewport(), page_no=1, revision_id="R1", source_sha256=SHA)
    assert binding.abstained is True
    assert "scale_not_firm" in binding.blocking_reasons
    assert binding.measurement_authority == AuthorityStatus.PROVISIONAL.value
    assert binding.measurement_authority != AuthorityStatus.FIRM.value
    assert binding.calibration.source_type == ScaleSourceType.TITLE_BLOCK.value
    assert binding.calibration.source_type != ScaleSourceType.SCALE_BAR.value
    evidence = viewport_evidence_with_bound_scale(
        _evidence("view_p1_1", (30.0, 30.0, 295.0, 350.0)),
        binding,
    )
    assert evidence.resolved_scale_id is None


def test_module_does_not_invent_graphic_scale_bar_evidence() -> None:
    assert "ScaleSourceType.SCALE_BAR" not in MODULE_SOURCE
    assert not re.search(r"source_type\s*=\s*[\"']scale_bar[\"']", MODULE_SOURCE)
    for viewport in (
        _viewport(scale_raw="SCALE 1:100", scale_denominator=100.0),
        _viewport(label="GROUND FLOOR PLAN SCALE 1:100", scale_raw="SCALE 1:100"),
        _viewport(scale_raw="1:75", scale_denominator=None),
        _viewport(scale_raw=None, scale_denominator=50.0),
    ):
        readings = viewport_scale_readings(viewport)
        assert all(reading.source_type != ScaleSourceType.SCALE_BAR.value for reading in readings)
        binding = bind_viewport_scale(viewport, page_no=1, revision_id="R1")
        assert binding.calibration.source_type != ScaleSourceType.SCALE_BAR.value


def test_scale_embedded_in_view_title_remains_provisional() -> None:
    source = classify_viewport_scale_source(
        label="GROUND FLOOR PLAN SCALE 1:100",
        scale_raw="SCALE 1:100",
    )
    assert source == ScaleSourceType.TITLE_BLOCK.value
    binding = bind_viewport_scale(
        _viewport(label="GROUND FLOOR PLAN SCALE 1:100", scale_raw="SCALE 1:100"),
        page_no=1,
        revision_id="R1",
    )
    assert binding.abstained
    assert "scale_not_firm" in binding.blocking_reasons
    assert binding.measurement_authority == AuthorityStatus.PROVISIONAL.value
    assert binding.measurement_authority != AuthorityStatus.FIRM.value
    assert binding.calibration.source_type == ScaleSourceType.TITLE_BLOCK.value


def test_classify_never_returns_inferred() -> None:
    for raw in (None, "", "SCALE 1:50", "1:200"):
        assert classify_viewport_scale_source(label="PLAN", scale_raw=raw) != ScaleSourceType.INFERRED.value
        assert classify_viewport_scale_source(label="PLAN", scale_raw=raw) != ScaleSourceType.SCALE_BAR.value


def test_authority_mapper_is_not_weakened_for_real_scale_bar() -> None:
    graphic = resolve_page_scale_calibration(
        page_no=1,
        sheet_label="A-101",
        readings=[
            ScaleSourceReading(
                source_type=ScaleSourceType.SCALE_BAR.value,
                scale_text="graphic scale bar 1:50",
                ratio=50.0,
                confidence=0.95,
            )
        ],
        revision_id="R1",
    )
    assert graphic.status == ScaleCalibrationStatus.VALID.value
    assert graphic.source_type == ScaleSourceType.SCALE_BAR.value
    assert measurement_authority_for_page_scale(graphic) == AuthorityStatus.FIRM.value
    producer_readings = viewport_scale_readings(_viewport(scale_raw="SCALE 1:50", scale_denominator=50.0))
    assert producer_readings
    assert all(reading.source_type != ScaleSourceType.SCALE_BAR.value for reading in producer_readings)


# ---------------------------------------------------------------------------
# P2 — raw/denominator cross-check and unversioned local block
# ---------------------------------------------------------------------------


def test_raw_and_denominator_mismatch_blocks() -> None:
    viewport = _viewport(scale_raw="1:50", scale_denominator=100.0)
    assert scale_representation_mismatch_reason(viewport) == "viewport_scale_ratio_mismatch"
    assert viewport_scale_readings(viewport) == ()
    binding = bind_viewport_scale(viewport, page_no=1, revision_id="R1")
    assert binding.abstained
    assert "viewport_scale_ratio_mismatch" in binding.blocking_reasons
    evidence = viewport_evidence_with_bound_scale(
        _evidence("view_p1_1", (30.0, 30.0, 295.0, 350.0)),
        binding,
    )
    assert evidence.resolved_scale_id is None


def test_unparseable_raw_with_denominator_is_mismatch() -> None:
    viewport = _viewport(scale_raw="NTS", scale_denominator=100.0)
    assert scale_representation_mismatch_reason(viewport) == "viewport_scale_ratio_mismatch"
    assert viewport_scale_readings(viewport) == ()
    binding = bind_viewport_scale(viewport, page_no=1, revision_id="R1")
    assert "viewport_scale_ratio_mismatch" in binding.blocking_reasons


def test_near_five_percent_disagreement_is_still_mismatch() -> None:
    """Tight local tolerance — not the page-scale 5% reconciler."""
    viewport = _viewport(scale_raw="1:100", scale_denominator=105.0)
    assert scale_representation_mismatch_reason(viewport) == "viewport_scale_ratio_mismatch"
    binding = bind_viewport_scale(viewport, page_no=1, revision_id="R1")
    assert "viewport_scale_ratio_mismatch" in binding.blocking_reasons


def test_matching_raw_and_denominator_is_provisional_not_firm() -> None:
    viewport = _viewport(scale_raw="1:100", scale_denominator=100.0)
    assert scale_representation_mismatch_reason(viewport) is None
    readings = viewport_scale_readings(viewport)
    assert len(readings) == 1
    assert readings[0].ratio == pytest.approx(100.0)
    assert readings[0].source_type == ScaleSourceType.TITLE_BLOCK.value
    binding = bind_viewport_scale(viewport, page_no=1, revision_id="R1")
    assert binding.measurement_authority == AuthorityStatus.PROVISIONAL.value
    assert binding.measurement_authority != AuthorityStatus.FIRM.value
    assert "scale_not_firm" in binding.blocking_reasons
    evidence = viewport_evidence_with_bound_scale(
        _evidence("view_p1_1", (30.0, 30.0, 295.0, 350.0)),
        binding,
    )
    assert evidence.resolved_scale_id is None


def test_unversioned_viewport_scale_blocks_locally() -> None:
    binding = bind_viewport_scale(_viewport(), page_no=1, revision_id=None, source_sha256=SHA)
    assert "scale_revision_unbound" in binding.blocking_reasons
    assert binding.revision_id is None
    assert binding.calibration.revision_id is None
    evidence = viewport_evidence_with_bound_scale(
        _evidence("view_p1_1", (30.0, 30.0, 295.0, 350.0)),
        binding,
    )
    assert evidence.resolved_scale_id is None


def test_blank_revision_id_is_unversioned() -> None:
    binding = bind_viewport_scale(_viewport(), page_no=1, revision_id="  \t")
    assert "scale_revision_unbound" in binding.blocking_reasons
    assert binding.revision_id is None
    evidence = viewport_evidence_with_bound_scale(
        _evidence("view_p1_1", (30.0, 30.0, 295.0, 350.0)),
        binding,
    )
    assert evidence.resolved_scale_id is None


# ---------------------------------------------------------------------------
# Mixed-scale independence, substitution, translation, replay
# ---------------------------------------------------------------------------


def test_mixed_scale_viewports_keep_independent_textual_calibrations() -> None:
    plan, elev = _mixed_viewports()
    bindings = bind_page_viewport_scales((plan, elev), page_no=1, revision_id="R1", source_sha256=SHA)
    assert [item.viewport_id for item in bindings] == ["view_p1_1", "view_p1_2"]
    assert bindings[0].measurement_authority == AuthorityStatus.PROVISIONAL.value
    assert bindings[1].measurement_authority == AuthorityStatus.PROVISIONAL.value
    assert bindings[0].calibration.source_type == ScaleSourceType.TITLE_BLOCK.value
    assert bindings[1].calibration.source_type == ScaleSourceType.TITLE_BLOCK.value
    assert bindings[0].scale_fingerprint != bindings[1].scale_fingerprint
    assert bindings[1].calibration.px_per_m == pytest.approx(bindings[0].calibration.px_per_m * 2.0, rel=1e-9)
    assert bindings[0].abstained is True
    assert bindings[1].abstained is True


def test_sibling_scale_does_not_leak_into_viewport_without_scale() -> None:
    plan = _viewport(view_id="view_p1_1", scale_raw="SCALE 1:100", scale_denominator=100.0)
    elev = _viewport(
        view_id="view_p1_2",
        label="NORTH ELEVATION",
        scale_raw=None,
        scale_denominator=None,
        bbox=(330.0, 30.0, 595.0, 350.0),
    )
    plan_binding, elev_binding = bind_page_viewport_scales((plan, elev), page_no=1, revision_id="R1")
    assert plan_binding.calibration.source_type == ScaleSourceType.TITLE_BLOCK.value
    assert plan_binding.measurement_authority == AuthorityStatus.PROVISIONAL.value
    assert elev_binding.abstained
    assert "viewport_scale_missing" in elev_binding.blocking_reasons


def test_same_ratio_still_viewport_bound_fingerprints() -> None:
    left = _viewport(view_id="view_p1_1", scale_raw="SCALE 1:100", scale_denominator=100.0)
    right = _viewport(
        view_id="view_p1_2",
        label="ROOF PLAN",
        scale_raw="SCALE 1:100",
        scale_denominator=100.0,
        bbox=(330.0, 30.0, 595.0, 350.0),
    )
    left_b, right_b = bind_page_viewport_scales((left, right), page_no=1, revision_id="R1")
    assert left_b.calibration.px_per_m == pytest.approx(right_b.calibration.px_per_m)
    assert left_b.scale_fingerprint != right_b.scale_fingerprint
    with pytest.raises(ViewportScaleBindingError):
        assert_binding_matches_viewport(left_b, right.view_id)


def test_reordered_viewport_input_does_not_alter_stable_bindings() -> None:
    plan, elev = _mixed_viewports()
    forward = bind_page_viewport_scales((plan, elev), page_no=1, revision_id="R1", source_sha256=SHA)
    reverse = bind_page_viewport_scales((elev, plan), page_no=1, revision_id="R1", source_sha256=SHA)
    by_id_forward = {item.viewport_id: item for item in forward}
    by_id_reverse = {item.viewport_id: item for item in reverse}
    assert by_id_forward.keys() == by_id_reverse.keys()
    for viewport_id, binding in by_id_forward.items():
        other = by_id_reverse[viewport_id]
        assert binding.scale_fingerprint == other.scale_fingerprint
        assert binding.calibration.px_per_m == pytest.approx(other.calibration.px_per_m)
        assert binding.measurement_authority == other.measurement_authority
        assert binding.blocking_reasons == other.blocking_reasons


def test_mixed_scale_matching_measurement_abstains_because_text_is_not_firm() -> None:
    plan, elev = _mixed_viewports()
    plan_binding, elev_binding = bind_page_viewport_scales(
        (plan, elev), page_no=1, revision_id="R1", source_sha256=SHA
    )
    context = _provider_context(plan.view_id, elev.view_id)
    document = _document("ev-plan", "ev-elev")
    plan_evidence = replace(
        viewport_evidence_with_bound_scale(
            ViewportEvidence(
                viewport_id=plan.view_id,
                document_id="doc-1",
                page_id="page-1",
                bbox=plan.bounding_box or (0.0, 0.0, 1.0, 1.0),
                view_type=plan.view_type,
                status=ViewportResolutionStatus.RESOLVED,
                evidence_ids=("ev-plan",),
                confidence=1.0,
            ),
            plan_binding,
        ),
        resolved_scale_id=plan_binding.scale_fingerprint,
    )
    result = resolve_linear_measurement_input(
        context=context,
        document=document,
        viewport=plan_evidence,
        entity=_entity("wall-plan", "ev-plan"),
        page_no=1,
        scaled_length_page_units=plan_binding.calibration.px_per_m * 8.0,
        scale_calibration=plan_binding.calibration,
    )
    assert result.abstained
    assert "scale_not_firm" in result.blocking_reasons
    assert "scale_not_bound_to_multi_viewport" not in result.blocking_reasons
    assert viewport_evidence_with_bound_scale(
        ViewportEvidence(
            viewport_id=plan.view_id,
            document_id="doc-1",
            page_id="page-1",
            bbox=plan.bounding_box or (0.0, 0.0, 1.0, 1.0),
            view_type=plan.view_type,
            status=ViewportResolutionStatus.RESOLVED,
            evidence_ids=("ev-plan",),
            confidence=1.0,
        ),
        plan_binding,
    ).resolved_scale_id is None
    assert elev_binding.measurement_authority == AuthorityStatus.PROVISIONAL.value


def test_mixed_scale_sibling_substitution_is_blocked() -> None:
    plan, elev = _mixed_viewports()
    plan_binding, elev_binding = bind_page_viewport_scales(
        (plan, elev), page_no=1, revision_id="R1", source_sha256=SHA
    )
    # Producer no longer attaches fingerprints for textual (non-FIRM) evidence.
    # Construct ViewportEvidence with the plan fingerprint + elevation calibration.
    swapped = resolve_linear_measurement_input(
        context=_provider_context(plan.view_id, elev.view_id),
        document=_document("ev-plan", "ev-elev"),
        viewport=ViewportEvidence(
            viewport_id=plan.view_id,
            document_id="doc-1",
            page_id="page-1",
            bbox=plan.bounding_box or (0.0, 0.0, 1.0, 1.0),
            view_type=plan.view_type,
            status=ViewportResolutionStatus.RESOLVED,
            evidence_ids=("ev-plan",),
            resolved_scale_id=plan_binding.scale_fingerprint,
            confidence=1.0,
        ),
        entity=_entity("wall-plan", "ev-plan"),
        page_no=1,
        scaled_length_page_units=plan_binding.calibration.px_per_m * 8.0,
        scale_calibration=elev_binding.calibration,
    )
    assert swapped.abstained
    assert "scale_not_bound_to_multi_viewport" in swapped.blocking_reasons


def test_mixed_scale_pdf_bindings_are_translation_invariant_at_provisional() -> None:
    base = _mixed_scale_sheet()
    shifted = _mixed_scale_sheet(dx=12.0, dy=-8.0)
    before_viewports = segment_page_viewports(base[0], page_number=1)
    after_viewports = segment_page_viewports(shifted[0], page_number=1)
    before = bind_page_viewport_scales(
        before_viewports, page_no=1, revision_id="R1", source_sha256=SHA
    )
    after = bind_page_viewport_scales(
        after_viewports, page_no=1, revision_id="R1", source_sha256=SHA
    )
    by_type_before = {
        next(v.view_type for v in before_viewports if v.view_id == item.viewport_id): item
        for item in before
    }
    by_type_after = {
        next(v.view_type for v in after_viewports if v.view_id == item.viewport_id): item
        for item in after
    }
    assert set(by_type_before) == set(by_type_after)
    for view_type, binding in by_type_before.items():
        other = by_type_after[view_type]
        assert binding.calibration.px_per_m == pytest.approx(other.calibration.px_per_m)
        assert binding.measurement_authority == AuthorityStatus.PROVISIONAL.value
        assert other.measurement_authority == AuthorityStatus.PROVISIONAL.value
        assert binding.abstained is True
        assert binding.calibration.source_type != ScaleSourceType.SCALE_BAR.value
    base.close()
    shifted.close()


def test_deterministic_replay() -> None:
    viewport = _viewport()
    first = bind_viewport_scale(viewport, page_no=1, revision_id="R1", source_sha256=SHA, sheet_label="A101")
    second = bind_viewport_scale(viewport, page_no=1, revision_id="R1", source_sha256=SHA, sheet_label="A101")
    assert first == second
    assert first.scale_fingerprint == second.scale_fingerprint
    assert first.measurement_authority == AuthorityStatus.PROVISIONAL.value


def test_conflicting_scales_in_one_viewport_fail_closed() -> None:
    binding = bind_viewport_scale(
        _viewport(
            scale_raw=None,
            scale_denominator=None,
            scale_conflict=True,
            notes=["conflicting viewport scales: 50.0, 100.0"],
        ),
        page_no=1,
        revision_id="R1",
    )
    readings = viewport_scale_readings(
        _viewport(
            scale_raw=None,
            scale_denominator=None,
            scale_conflict=True,
            notes=["conflicting viewport scales: 50.0, 100.0"],
        )
    )
    assert readings
    assert all(reading.source_type == ScaleSourceType.TITLE_BLOCK.value for reading in readings)
    assert all(reading.source_type != ScaleSourceType.SCALE_BAR.value for reading in readings)
    assert binding.abstained
    assert "viewport_scale_conflict" in binding.blocking_reasons
    assert binding.measurement_authority == AuthorityStatus.BLOCKED.value
    assert binding.calibration.status == ScaleCalibrationStatus.MANUAL_REQUIRED.value


def test_unparseable_conflict_notes_fail_closed_without_invented_scale_bar() -> None:
    viewport = _viewport(
        scale_raw=None,
        scale_denominator=None,
        scale_conflict=True,
        notes=["conflicting viewport scales: unreadable"],
    )
    assert viewport_scale_readings(viewport) == ()
    binding = bind_viewport_scale(viewport, page_no=1, revision_id="R1")
    assert binding.abstained
    assert "viewport_scale_conflict" in binding.blocking_reasons
    assert binding.calibration.source_type != ScaleSourceType.SCALE_BAR.value


def test_stale_revision_blocks_through_existing_freshness_check() -> None:
    binding = bind_viewport_scale(_viewport(), page_no=1, revision_id="R1")
    stale = check_calibration_freshness(binding.calibration, "R2")
    assert stale.status == ScaleCalibrationStatus.BLOCKED.value
    assert stale.px_per_m == binding.calibration.px_per_m


def test_viewport_evidence_does_not_receive_fingerprint_for_textual_scale() -> None:
    textual = bind_viewport_scale(_viewport(), page_no=1, revision_id="R1")
    evidence = _evidence("view_p1_1", (30.0, 30.0, 295.0, 350.0))
    assert viewport_evidence_with_bound_scale(evidence, textual).resolved_scale_id is None

    title = bind_viewport_scale(
        _viewport(label="GROUND FLOOR PLAN SCALE 1:100"),
        page_no=1,
        revision_id="R1",
    )
    assert viewport_evidence_with_bound_scale(evidence, title).resolved_scale_id is None


def test_firm_binding_from_real_scale_bar_still_attaches_resolved_scale_id() -> None:
    """Attacher still works for independently corroborated FIRM SCALE_BAR."""
    firm_calib = resolve_page_scale_calibration(
        page_no=1,
        sheet_label="A101#viewport:view_p1_1",
        readings=[
            ScaleSourceReading(
                source_type=ScaleSourceType.SCALE_BAR.value,
                scale_text="graphic scale bar 1:100",
                ratio=100.0,
                confidence=1.0,
            )
        ],
        revision_id="R1",
    )
    assert measurement_authority_for_page_scale(firm_calib) == AuthorityStatus.FIRM.value
    binding = ViewportScaleBinding(
        viewport_id="view_p1_1",
        page_no=1,
        source_sha256=SHA,
        revision_id="R1",
        calibration=firm_calib,
        scale_fingerprint=scale_calibration_fingerprint(firm_calib),
        measurement_authority=measurement_authority_for_page_scale(firm_calib),
        blocking_reasons=(),
    )
    bound = viewport_evidence_with_bound_scale(
        _evidence("view_p1_1", (30.0, 30.0, 295.0, 350.0)),
        binding,
    )
    assert bound.resolved_scale_id == binding.scale_fingerprint
    assert all(
        reading.source_type != ScaleSourceType.SCALE_BAR.value
        for reading in viewport_scale_readings(_viewport())
    )


def test_ambiguous_viewport_cannot_bind_firm_scale() -> None:
    binding = bind_viewport_scale(
        _viewport(status=ViewportSegmentationStatus.AMBIGUOUS.value, bbox=None),
        page_no=1,
        revision_id="R1",
    )
    assert binding.abstained
    assert "viewport_unresolved" in binding.blocking_reasons


def test_ambiguous_viewport_evidence_cannot_carry_resolved_scale() -> None:
    textual = bind_viewport_scale(_viewport(), page_no=1, revision_id="R1")
    evidence = ViewportEvidence(
        viewport_id="view_p1_1",
        document_id="doc-1",
        page_id="page-1",
        bbox=(30.0, 30.0, 295.0, 350.0),
        view_type="floor_plan",
        status=ViewportResolutionStatus.AMBIGUOUS,
        confidence=0.0,
    )
    assert viewport_evidence_with_bound_scale(evidence, textual).resolved_scale_id is None


def test_missing_scale_abstains() -> None:
    binding = bind_viewport_scale(
        _viewport(scale_raw=None, scale_denominator=None),
        page_no=1,
        revision_id="R1",
    )
    assert binding.abstained
    assert "viewport_scale_missing" in binding.blocking_reasons
    assert "scale_not_firm" in binding.blocking_reasons


def test_malformed_non_positive_raw_only_abstains() -> None:
    viewport = _viewport(scale_raw="SCALE 1:0", scale_denominator=None)
    readings = viewport_scale_readings(viewport)
    assert readings
    assert readings[0].ratio is None
    binding = bind_viewport_scale(viewport, page_no=1, revision_id="R1")
    assert binding.abstained


def test_page_mismatch_fails_closed() -> None:
    binding = bind_viewport_scale(_viewport(page_number=2), page_no=1, revision_id="R1")
    assert "scale_page_mismatch" in binding.blocking_reasons


def test_source_sha256_is_not_used_semantically() -> None:
    first = bind_viewport_scale(_viewport(), page_no=1, revision_id="R1", source_sha256="a" * 64)
    second = bind_viewport_scale(_viewport(), page_no=1, revision_id="R1", source_sha256="c" * 64)
    assert first.calibration.px_per_m == pytest.approx(second.calibration.px_per_m)
    assert first.measurement_authority == second.measurement_authority
    assert first.scale_fingerprint == second.scale_fingerprint


def test_module_has_no_benchmark_gold_tokens() -> None:
    for token in (
        "expected_boq",
        "tenders_ke",
        "item_mappings",
        "headline_accuracy",
        "NEW_SELECTIVE",
        "NEW_AUTHORITATIVE",
        "project_id",
    ):
        assert token not in MODULE_SOURCE


def test_adversarial_labels_cannot_promote_text_to_scale_bar() -> None:
    for label in (
        "GROUND FLOOR PLAN",
        "",
        "GRAPHIC SCALE",
        "SCALE BAR",
        "NORTH ELEVATION",
        "GROUND FLOOR PLAN SCALE 1:100",
    ):
        source = classify_viewport_scale_source(label=label, scale_raw="SCALE 1:100")
        assert source == ScaleSourceType.TITLE_BLOCK.value
        assert source != ScaleSourceType.SCALE_BAR.value
        assert source != ScaleSourceType.INFERRED.value


def test_adversarial_scale_text_variants_stay_provisional() -> None:
    for raw in ("SCALE 1:100", "scale 1:100", "  SCALE  1:100  ", "1:100"):
        binding = bind_viewport_scale(
            _viewport(scale_raw=raw, scale_denominator=None),
            page_no=1,
            revision_id="R1",
        )
        assert binding.calibration.source_type == ScaleSourceType.TITLE_BLOCK.value
        assert binding.measurement_authority == AuthorityStatus.PROVISIONAL.value
        assert binding.measurement_authority != AuthorityStatus.FIRM.value


def test_adversarial_swapped_ratio_tokens_block() -> None:
    viewport = _viewport(scale_raw="100:1", scale_denominator=100.0)
    assert scale_representation_mismatch_reason(viewport) == "viewport_scale_ratio_mismatch"
    binding = bind_viewport_scale(viewport, page_no=1, revision_id="R1")
    assert "viewport_scale_ratio_mismatch" in binding.blocking_reasons
    assert viewport_evidence_with_bound_scale(
        _evidence("view_p1_1", (30.0, 30.0, 295.0, 350.0)),
        binding,
    ).resolved_scale_id is None


def test_adversarial_zero_denominator_with_parseable_raw_blocks() -> None:
    viewport = _viewport(scale_raw="SCALE 1:100", scale_denominator=0.0)
    assert scale_representation_mismatch_reason(viewport) == "viewport_scale_ratio_mismatch"
    binding = bind_viewport_scale(viewport, page_no=1, revision_id="R1")
    assert "viewport_scale_ratio_mismatch" in binding.blocking_reasons


def test_adversarial_unusable_binding_clears_prepopulated_resolved_scale_id() -> None:
    stale = _evidence(
        "view_p1_1",
        (30.0, 30.0, 295.0, 350.0),
        resolved_scale_id="stale-fingerprint",
    )
    unversioned = bind_viewport_scale(_viewport(), page_no=1, revision_id=None)
    assert "scale_revision_unbound" in unversioned.blocking_reasons
    assert viewport_evidence_with_bound_scale(stale, unversioned).resolved_scale_id is None

    mismatched = bind_viewport_scale(
        _viewport(scale_raw="1:50", scale_denominator=100.0),
        page_no=1,
        revision_id="R1",
    )
    assert viewport_evidence_with_bound_scale(stale, mismatched).resolved_scale_id is None


def test_adversarial_fingerprint_tracks_viewport_and_revision_not_path_identity() -> None:
    plan = bind_viewport_scale(
        _viewport(view_id="view_p1_1"),
        page_no=1,
        revision_id="R1",
        sheet_label="A101",
        source_sha256=SHA,
    )
    other_view = bind_viewport_scale(
        _viewport(view_id="view_p1_2"),
        page_no=1,
        revision_id="R1",
        sheet_label="A101",
        source_sha256=SHA,
    )
    other_revision = bind_viewport_scale(
        _viewport(view_id="view_p1_1"),
        page_no=1,
        revision_id="R2",
        sheet_label="A101",
        source_sha256=SHA,
    )
    other_sha = bind_viewport_scale(
        _viewport(view_id="view_p1_1"),
        page_no=1,
        revision_id="R1",
        sheet_label="A101",
        source_sha256="c" * 64,
    )
    assert plan.scale_fingerprint != other_view.scale_fingerprint
    assert plan.scale_fingerprint != other_revision.scale_fingerprint
    assert plan.scale_fingerprint == other_sha.scale_fingerprint
    assert "viewport:view_p1_1" in plan.calibration.sheet_label
    assert plan.calibration.revision_id == "R1"
    assert plan.source_sha256 == SHA
    assert other_sha.source_sha256 == "c" * 64
