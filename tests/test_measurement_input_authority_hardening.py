from __future__ import annotations

from pb_measurement_input_authority import (
    resolve_linear_measurement_input,
    scale_calibration_fingerprint,
)
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    ViewportEvidence,
    ViewportResolutionStatus,
)
from pb_migration_provider_envelope import ProviderContext
from pb_page_scale_calibration_authority import (
    ScaleSourceReading,
    ScaleSourceType,
    resolve_page_scale_calibration,
)

SHA = "a" * 64


def _context(*, multi_viewport: bool = False) -> ProviderContext:
    viewports = ("vp-1", "vp-2") if multi_viewport else ("vp-1",)
    ownership = (("vp-1", 1), ("vp-2", 1)) if multi_viewport else (("vp-1", 1),)
    return ProviderContext(
        run_id="run",
        workspace_id="ws",
        project_id="project",
        document_id="doc",
        source_sha256=SHA,
        revision_id="R1",
        current_revision_id="R1",
        selected_pages=(0,),
        owned_viewport_ids=viewports,
        evidence_snapshot_id="snapshot",
        owned_page_numbers=(1,),
        viewport_page_ownership=ownership,
    )


def _document() -> DocumentEvidence:
    return DocumentEvidence(
        document_id="doc",
        source_sha256=SHA,
        page_count=1,
        page_ids=("page-1",),
        evidence_ids=("ev-wall", "ev-dim"),
    )


def _viewport(*, resolved_scale_id=None, status=ViewportResolutionStatus.RESOLVED) -> ViewportEvidence:
    return ViewportEvidence(
        viewport_id="vp-1",
        document_id="doc",
        page_id="page-1",
        bbox=(0.0, 0.0, 100.0, 100.0),
        view_type="floor_plan",
        status=status,
        evidence_ids=("ev-wall",),
        resolved_scale_id=resolved_scale_id,
        confidence=1.0,
    )


def _entity(status=EvidenceResolutionStatus.CORROBORATED) -> EntityEvidence:
    return EntityEvidence(
        candidate_entity_id="wall-1",
        candidate_type="wall",
        evidence_ids=("ev-wall", "ev-dim"),
        status=status,
        confidence=1.0,
    )


def _figured(status=EvidenceResolutionStatus.CORROBORATED) -> EvidenceAtom:
    return EvidenceAtom(
        evidence_id="ev-dim",
        document_id="doc",
        page_id="page-1",
        viewport_id="vp-1",
        kind="figured_dimension",
        method="vector_text",
        raw_text="6500",
        status=status,
        confidence=1.0,
    )


def _scale():
    return resolve_page_scale_calibration(
        page_no=1,
        sheet_label="A101",
        readings=[ScaleSourceReading(ScaleSourceType.SCALE_BAR.value, "1:100", 100.0, 1.0)],
        revision_id="R1",
    )


def test_candidate_figured_evidence_cannot_become_firm() -> None:
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        figured_evidence=_figured(EvidenceResolutionStatus.CANDIDATE),
    )
    assert result.abstained
    assert "figured_evidence_unresolved" in result.blocking_reasons


def test_candidate_entity_cannot_back_firm_measurement() -> None:
    scale = _scale()
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(EvidenceResolutionStatus.CANDIDATE),
        page_no=1,
        scaled_length_page_units=scale.px_per_m * 4.0,
        scale_calibration=scale,
    )
    assert result.abstained
    assert "entity_unresolved" in result.blocking_reasons


def test_ambiguous_viewport_status_cannot_measure() -> None:
    scale = _scale()
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(),
        viewport=_viewport(status=ViewportResolutionStatus.AMBIGUOUS),
        entity=_entity(),
        page_no=1,
        scaled_length_page_units=scale.px_per_m * 4.0,
        scale_calibration=scale,
    )
    assert result.abstained
    assert "viewport_unresolved" in result.blocking_reasons


def test_page_scale_cannot_leak_across_multiple_viewports_without_binding() -> None:
    scale = _scale()
    result = resolve_linear_measurement_input(
        context=_context(multi_viewport=True),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        scaled_length_page_units=scale.px_per_m * 4.0,
        scale_calibration=scale,
    )
    assert result.abstained
    assert "scale_not_bound_to_multi_viewport" in result.blocking_reasons


def test_multi_viewport_scale_may_measure_when_fingerprint_is_explicitly_bound() -> None:
    scale = _scale()
    result = resolve_linear_measurement_input(
        context=_context(multi_viewport=True),
        document=_document(),
        viewport=_viewport(resolved_scale_id=scale_calibration_fingerprint(scale)),
        entity=_entity(),
        page_no=1,
        scaled_length_page_units=scale.px_per_m * 4.0,
        scale_calibration=scale,
    )
    assert not result.abstained
    assert result.value_m == 4.0
