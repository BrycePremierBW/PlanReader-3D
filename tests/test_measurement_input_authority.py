from __future__ import annotations

import math

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
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


def _context(*, revision: str = "R1") -> ProviderContext:
    return ProviderContext(
        run_id="run-1",
        workspace_id="ws-1",
        project_id="project-1",
        document_id="doc-1",
        source_sha256=SHA,
        revision_id=revision,
        current_revision_id=revision,
        selected_pages=(0,),
        owned_viewport_ids=("vp-1",),
        evidence_snapshot_id="ev-snap-1",
        canonical_graph_snapshot_id="graph-snap-1",
        measurement_authority_snapshot_id="measure-snap-1",
        owned_page_numbers=(1,),
        viewport_page_ownership=(("vp-1", 1),),
    )


def _document(*, evidence_ids=("ev-wall", "ev-dim")) -> DocumentEvidence:
    return DocumentEvidence(
        document_id="doc-1",
        source_sha256=SHA,
        page_count=1,
        page_ids=("page-1",),
        evidence_ids=tuple(evidence_ids),
        producer="test",
        producer_version="1",
    )


def _viewport(viewport_id: str = "vp-1") -> ViewportEvidence:
    return ViewportEvidence(
        viewport_id=viewport_id,
        document_id="doc-1",
        page_id="page-1",
        bbox=(0.0, 0.0, 100.0, 100.0),
        view_type="floor_plan",
        status=ViewportResolutionStatus.RESOLVED,
        evidence_ids=("ev-wall",),
        scale_evidence_ids=(),
        confidence=1.0,
    )


def _entity(*, evidence_ids=("ev-wall", "ev-dim"), status=EvidenceResolutionStatus.CORROBORATED) -> EntityEvidence:
    return EntityEvidence(
        candidate_entity_id="wall-1",
        candidate_type="wall",
        evidence_ids=tuple(evidence_ids),
        status=status,
        confidence=1.0,
    )


def _scale(source: ScaleSourceType, ratio: float = 100.0, *, revision: str = "R1"):
    return resolve_page_scale_calibration(
        page_no=1,
        sheet_label="A101",
        readings=[ScaleSourceReading(source.value, f"1:{ratio:g}", ratio, 1.0)],
        revision_id=revision,
    )


def _figured(text: str = "6500") -> EvidenceAtom:
    return EvidenceAtom(
        evidence_id="ev-dim",
        document_id="doc-1",
        page_id="page-1",
        viewport_id="vp-1",
        kind="figured_dimension",
        method="vector_text",
        raw_text=text,
        confidence=1.0,
        status=EvidenceResolutionStatus.CORROBORATED,
    )


def test_scale_bar_firm_scaled_geometry_resolves() -> None:
    scale = _scale(ScaleSourceType.SCALE_BAR)
    # At 1:100, px_per_m is ~28.346; 10m therefore spans px_per_m*10 page units.
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(evidence_ids=("ev-wall",)),
        viewport=_viewport(),
        entity=_entity(evidence_ids=("ev-wall",)),
        page_no=1,
        scaled_length_page_units=scale.px_per_m * 10.0,
        scale_calibration=scale,
    )
    assert result.abstained is False
    assert result.authority_status == AuthorityStatus.FIRM.value
    assert result.source_type == MeasurementAuthorityType.PDF_SCALED.value
    assert math.isclose(result.value_m or 0.0, 10.0, abs_tol=1e-6)
    assert result.scale_fingerprint == scale_calibration_fingerprint(scale)


def test_title_block_only_scale_is_not_firm_and_abstains() -> None:
    scale = _scale(ScaleSourceType.TITLE_BLOCK)
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(evidence_ids=("ev-wall",)),
        viewport=_viewport(),
        entity=_entity(evidence_ids=("ev-wall",)),
        page_no=1,
        scaled_length_page_units=100.0,
        scale_calibration=scale,
    )
    assert result.abstained
    assert result.blocking_reasons == ("scale_not_firm",)


def test_inferred_scale_is_not_firm_and_abstains() -> None:
    scale = _scale(ScaleSourceType.INFERRED)
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(evidence_ids=("ev-wall",)),
        viewport=_viewport(),
        entity=_entity(evidence_ids=("ev-wall",)),
        page_no=1,
        scaled_length_page_units=100.0,
        scale_calibration=scale,
    )
    assert result.abstained
    assert result.authority_status == AuthorityStatus.BLOCKED.value


def test_stale_scale_abstains() -> None:
    scale = _scale(ScaleSourceType.SCALE_BAR, revision="R0")
    result = resolve_linear_measurement_input(
        context=_context(revision="R1"),
        document=_document(evidence_ids=("ev-wall",)),
        viewport=_viewport(),
        entity=_entity(evidence_ids=("ev-wall",)),
        page_no=1,
        scaled_length_page_units=100.0,
        scale_calibration=scale,
    )
    assert result.abstained
    assert result.blocking_reasons == ("scale_not_firm",)
    assert "Stale calibration" in result.notes


def test_foreign_viewport_abstains_before_measurement() -> None:
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(evidence_ids=("ev-wall",)),
        viewport=_viewport("vp-foreign"),
        entity=_entity(evidence_ids=("ev-wall",)),
        page_no=1,
        scaled_length_page_units=100.0,
        scale_calibration=_scale(ScaleSourceType.SCALE_BAR),
    )
    assert result.abstained
    assert "viewport_not_owned" in result.blocking_reasons


def test_source_hash_mismatch_abstains() -> None:
    document = DocumentEvidence(
        document_id="doc-1",
        source_sha256="b" * 64,
        page_count=1,
        page_ids=("page-1",),
        evidence_ids=("ev-wall",),
    )
    result = resolve_linear_measurement_input(
        context=_context(),
        document=document,
        viewport=_viewport(),
        entity=_entity(evidence_ids=("ev-wall",)),
        page_no=1,
        scaled_length_page_units=100.0,
        scale_calibration=_scale(ScaleSourceType.SCALE_BAR),
    )
    assert result.abstained
    assert "source_sha256_mismatch" in result.blocking_reasons


def test_figured_dimension_resolves_without_scale() -> None:
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        figured_evidence=_figured("6500"),
    )
    assert result.abstained is False
    assert result.value_m == 6.5
    assert result.source_type == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value
    assert result.authority_status == AuthorityStatus.FIRM.value


def test_figured_dimension_outweighs_agreeing_scaled_geometry() -> None:
    scale = _scale(ScaleSourceType.SCALE_BAR)
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        scaled_length_page_units=scale.px_per_m * 6.5,
        scale_calibration=scale,
        figured_evidence=_figured("6500"),
    )
    assert result.abstained is False
    assert result.value_m == 6.5
    assert result.source_type == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value


def test_figured_vs_scaled_conflict_abstains() -> None:
    scale = _scale(ScaleSourceType.SCALE_BAR)
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        scaled_length_page_units=scale.px_per_m * 9.0,
        scale_calibration=scale,
        figured_evidence=_figured("6500"),
    )
    assert result.abstained
    assert result.blocking_reasons == ("figured_measurement_not_firm",)


def test_unresolved_entity_abstains() -> None:
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(evidence_ids=("ev-wall",)),
        viewport=_viewport(),
        entity=_entity(evidence_ids=("ev-wall",), status=EvidenceResolutionStatus.ABSTAINED),
        page_no=1,
        scaled_length_page_units=100.0,
        scale_calibration=_scale(ScaleSourceType.SCALE_BAR),
    )
    assert result.abstained
    assert "entity_unresolved" in result.blocking_reasons


def test_resolution_fingerprint_is_deterministic_and_changes_with_scale() -> None:
    scale_100 = _scale(ScaleSourceType.SCALE_BAR, 100.0)
    scale_50 = _scale(ScaleSourceType.SCALE_BAR, 50.0)
    kwargs = dict(
        context=_context(),
        document=_document(evidence_ids=("ev-wall",)),
        viewport=_viewport(),
        entity=_entity(evidence_ids=("ev-wall",)),
        page_no=1,
    )
    first = resolve_linear_measurement_input(
        **kwargs,
        scaled_length_page_units=scale_100.px_per_m * 4.0,
        scale_calibration=scale_100,
    )
    replay = resolve_linear_measurement_input(
        **kwargs,
        scaled_length_page_units=scale_100.px_per_m * 4.0,
        scale_calibration=scale_100,
    )
    changed = resolve_linear_measurement_input(
        **kwargs,
        scaled_length_page_units=scale_50.px_per_m * 4.0,
        scale_calibration=scale_50,
    )
    assert first.fingerprint() == replay.fingerprint()
    assert first.fingerprint() != changed.fingerprint()
