from __future__ import annotations

from pb_measurement_input_authority import resolve_linear_measurement_input
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
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

SHA = "f" * 64


def _context(*, revision: str | None = "R1", current: str | None = "R1") -> ProviderContext:
    return ProviderContext(
        run_id="run",
        workspace_id="ws",
        project_id="project",
        document_id="doc",
        source_sha256=SHA,
        revision_id=revision,
        current_revision_id=current,
        selected_pages=(0,),
        owned_viewport_ids=("vp",),
        evidence_snapshot_id="evsnap",
        measurement_authority_snapshot_id="measuresnap",
        owned_page_numbers=(1,),
        viewport_page_ownership=(("vp", 1),),
    )


def _document() -> DocumentEvidence:
    return DocumentEvidence(
        document_id="doc",
        source_sha256=SHA,
        page_count=1,
        page_ids=("page-1",),
        evidence_ids=("ev-wall",),
    )


def _viewport() -> ViewportEvidence:
    return ViewportEvidence(
        viewport_id="vp",
        document_id="doc",
        page_id="page-1",
        bbox=(0.0, 0.0, 100.0, 100.0),
        view_type="floor_plan",
        status=ViewportResolutionStatus.RESOLVED,
        evidence_ids=("ev-wall",),
        confidence=1.0,
    )


def _entity() -> EntityEvidence:
    return EntityEvidence(
        candidate_entity_id="wall-1",
        candidate_type="wall",
        evidence_ids=("ev-wall",),
        status=EvidenceResolutionStatus.CORROBORATED,
        confidence=1.0,
    )


def _scale(*, revision: str | None):
    return resolve_page_scale_calibration(
        page_no=1,
        sheet_label="A101",
        readings=[ScaleSourceReading(ScaleSourceType.SCALE_BAR.value, "1:100", 100.0, 1.0)],
        revision_id=revision,
    )


def test_unversioned_scale_cannot_become_firm_measurement() -> None:
    scale = _scale(revision=None)
    result = resolve_linear_measurement_input(
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        scaled_length_page_units=scale.px_per_m * 5.0,
        scale_calibration=scale,
    )
    assert result.abstained is True
    assert result.value_m is None
    assert "scale_revision_unbound" in result.blocking_reasons


def test_unbound_run_revision_blocks_before_measurement() -> None:
    scale = _scale(revision="R1")
    result = resolve_linear_measurement_input(
        context=_context(revision=None, current="R1"),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        scaled_length_page_units=scale.px_per_m * 5.0,
        scale_calibration=scale,
    )
    assert result.abstained is True
    assert "revision_unbound" in result.blocking_reasons
