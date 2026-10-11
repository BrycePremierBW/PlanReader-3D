from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

from pb_live_opening_source_closed_export import (
    build_live_opening_area_source_traces,
    seal_live_opening_area_run,
)
from pb_live_opening_area_quantity_publication import (
    LIVE_OPENING_ELEVATION_FRAME_AREA_QUANTITY_AUTHORITY,
    LIVE_OPENING_FIGURED_AREA_QUANTITY_AUTHORITY,
    LIVE_OPENING_FRAME_SCHEDULE_AREA_QUANTITY_AUTHORITY,
    LIVE_OPENING_GEOMETRY_AREA_QUANTITY_AUTHORITY,
    _opening_quantity,
    publish_live_opening_area_quantities,
)
from pb_live_physical_opening_void_composition import (
    LiveCanonicalOpeningObject,
    LivePhysicalOpeningVoidComposition,
)
from pb_migration_contracts import EvidenceResolutionStatus
from pb_quantity_takeoff_adapter import (
    CommercialMeasurementAuthority,
    CommercialTakeoffSourceTrace,
    quantity_evidence_to_takeoff_output_row,
)
from pb_source_closed_run_export import seal_source_closed_quantity


SHA = "a" * 64


def _opening(
    *,
    canonical_id: str = "opening-1",
    kind: str | None = "window",
    area_m2: float | None = 2.172,
    area_basis: str | None = "figured_opening_label",
    figured_area_record_id: str | None = "figured-1",
    opening_void_record_id: str | None = None,
) -> LiveCanonicalOpeningObject:
    evidence_ids = tuple(
        value
        for value in (
            canonical_id,
            "source-observation-1",
            "host-binding-1",
            "host-frame-1",
            figured_area_record_id,
            opening_void_record_id,
        )
        if value
    )
    return LiveCanonicalOpeningObject(
        canonical_opening_id=canonical_id,
        physical_opening_id=canonical_id,
        document_id="doc-1",
        revision_id="rev-1",
        source_sha256=SHA,
        snapshot_id="snap-1",
        page_id="3",
        viewport_id="vp-floor-1",
        semantic_class="physical_opening",
        structural_pattern="gap_corroborated_window_jamb_pair",
        representative_observation_id="source-observation-1",
        source_observation_ids=("source-observation-1",),
        source_lineage_root_ids=("source-root-1",),
        source_geometries=((0.0, 0.0, 1.0, 0.0),),
        host_wall_id="wall-1",
        host_binding_record_id="host-binding-1",
        host_frame_record_id="host-frame-1",
        wall_local_frame_id=None,
        profile_kind=None,
        coordinate_unit=None,
        u0=None,
        u1=None,
        z0=None,
        z1=None,
        width_m=None,
        height_m=None,
        area_m2=area_m2,
        area_basis=area_basis,
        figured_area_record_id=figured_area_record_id,
        opening_void_record_id=opening_void_record_id,
        opening_universe_record_id=None,
        width_record_id=None,
        height_record_id=None,
        vertical_placement_record_id=None,
        scale_record_id=None,
        schedule_binding_record_id=None,
        opening_kind=kind,
        type_mark=None,
        schedule_page_id=None,
        schedule_declared_width_mm=None,
        schedule_declared_height_mm=None,
        schedule_declared_count=None,
        schedule_count_explicit=False,
        schedule_row_observation_ids=(),
        tag_observation_id=None,
        evidence_ids=evidence_ids,
        geometry_complete=False,
    )


def _composition(*openings: LiveCanonicalOpeningObject):
    return LivePhysicalOpeningVoidComposition(
        revision_id="rev-1",
        status=EvidenceResolutionStatus.ABSTAINED,
        reason_codes=("partial",),
        traces=(),
        physical_opening_void_authorities=MappingProxyType({}),
        void_selectors=MappingProxyType({}),
        canonical_openings=tuple(openings),
    )


def test_figured_opening_area_becomes_identity_bound_quantity_evidence() -> None:
    opening = _opening()
    quantity = _opening_quantity(opening)
    assert quantity is not None
    assert quantity.family == "opening_area"
    assert quantity.semantic_key == "window_area:opening-1"
    assert quantity.value == pytest.approx(2.172)
    assert quantity.unit == "m2"
    assert quantity.input_entity_ids == ("opening-1",)
    assert quantity.authority == LIVE_OPENING_FIGURED_AREA_QUANTITY_AUTHORITY
    assert quantity.status == "corroborated"
    assert quantity.abstained is False
    assert "figured-1" in quantity.evidence_ids
    assert quantity.metadata["area_basis"] == "figured_opening_label"
    assert quantity.metadata["measurement_record_id"] == "figured-1"
    assert quantity.metadata["host_wall_id"] == "wall-1"
    assert quantity.metadata["host_binding_record_id"] == "host-binding-1"


def test_untyped_opening_never_publishes_trade_area() -> None:
    assert _opening_quantity(_opening(kind=None)) is None


def test_opening_without_authenticated_host_never_publishes_area_quantity() -> None:
    assert _opening_quantity(
        replace(
            _opening(),
            host_wall_id=None,
            host_binding_record_id=None,
            host_frame_record_id=None,
        )
    ) is None


def test_host_identity_requires_source_binding_or_frame_record() -> None:
    assert _opening_quantity(
        replace(
            _opening(),
            host_wall_id="wall-1",
            host_binding_record_id=None,
            host_frame_record_id=None,
        )
    ) is None


@pytest.mark.parametrize("unproven_host", ("host-binding-1", "host-frame-1"))
def test_opening_requires_exact_host_receipt_in_canonical_provenance(
    unproven_host: str,
) -> None:
    opening = _opening()
    assert _opening_quantity(opening) is not None
    tampered = replace(
        opening,
        evidence_ids=tuple(
            receipt for receipt in opening.evidence_ids if receipt != unproven_host
        ),
    )
    assert _opening_quantity(tampered) is None


def test_valid_single_source_host_receipt_still_publishes() -> None:
    opening = _opening()
    only_binding = replace(
        opening,
        host_frame_record_id=None,
        evidence_ids=tuple(
            receipt
            for receipt in opening.evidence_ids
            if receipt != "host-frame-1"
        ),
    )
    assert _opening_quantity(only_binding) is not None


def test_opening_without_owned_viewport_never_publishes_area_quantity() -> None:
    opening = replace(_opening(), viewport_id=None)
    assert _opening_quantity(opening) is None


def test_figured_area_requires_its_measurement_record_in_canonical_provenance() -> None:
    opening = replace(
        _opening(),
        evidence_ids=("opening-1", "source-observation-1"),
    )
    assert _opening_quantity(opening) is None


def test_resolved_geometry_area_requires_physical_void_evidence() -> None:
    opening = _opening(
        area_m2=1.827,
        area_basis="resolved_opening_geometry",
        figured_area_record_id=None,
        opening_void_record_id="void-1",
    )
    quantity = _opening_quantity(opening)
    assert quantity is not None
    assert quantity.value == pytest.approx(1.827)
    assert quantity.authority == LIVE_OPENING_GEOMETRY_AREA_QUANTITY_AUTHORITY
    assert quantity.metadata["measurement_record_id"] == "void-1"

    assert _opening_quantity(
        replace(opening, opening_void_record_id=None)
    ) is None


def test_authenticated_elevation_frame_area_is_identity_bound_commercial_evidence() -> None:
    opening = _opening(
        area_m2=7.2,
        area_basis="authenticated_elevation_frame",
        figured_area_record_id="elevation-frame-1",
    )
    quantity = _opening_quantity(opening)
    assert quantity is not None
    assert quantity.value == pytest.approx(7.2)
    assert quantity.unit == "m2"
    assert quantity.input_entity_ids == ("opening-1",)
    assert quantity.authority == LIVE_OPENING_ELEVATION_FRAME_AREA_QUANTITY_AUTHORITY
    assert quantity.metadata["area_basis"] == "authenticated_elevation_frame"
    assert quantity.metadata["measurement_record_id"] == "elevation-frame-1"

    assert _opening_quantity(
        replace(
            opening,
            evidence_ids=("opening-1", "source-observation-1"),
        )
    ) is None


def test_authenticated_frame_schedule_area_is_commercial_only_with_frame_basis() -> None:
    opening = replace(
        _opening(
            area_m2=2.16,
            area_basis="authenticated_frame_schedule",
            figured_area_record_id=None,
        ),
        schedule_binding_record_id="schedule-binding-1",
        schedule_declared_width_mm=1200,
        schedule_declared_height_mm=1800,
        schedule_row_dimension_basis="frame",
        schedule_row_basis_source="frame width",
        evidence_ids=(
            "opening-1",
            "source-observation-1",
            "schedule-binding-1",
            "schedule-row-1",
            "host-binding-1",
            "host-frame-1",
        ),
    )
    quantity = _opening_quantity(opening)
    assert quantity is not None
    assert quantity.value == pytest.approx(2.16)
    assert quantity.authority == LIVE_OPENING_FRAME_SCHEDULE_AREA_QUANTITY_AUTHORITY
    assert quantity.metadata["area_basis"] == "authenticated_frame_schedule"
    assert quantity.metadata["measurement_record_id"] == "schedule-binding-1"
    assert quantity.metadata["schedule_row_dimension_basis"] == "frame"

    assert _opening_quantity(
        replace(opening, schedule_row_dimension_basis="")
    ) is None
    assert _opening_quantity(
        replace(opening, schedule_row_dimension_basis="leaf")
    ) is None
    assert _opening_quantity(
        replace(
            opening,
            evidence_ids=("opening-1", "source-observation-1", "schedule-row-1"),
        )
    ) is None


def test_publication_is_one_quantity_per_physical_opening_identity() -> None:
    quantities = publish_live_opening_area_quantities(
        _composition(
            _opening(canonical_id="opening-a"),
            _opening(canonical_id="opening-b", kind="door", area_m2=3.15),
        )
    )
    assert len(quantities) == 2
    assert {
        quantity.input_entity_ids[0] for quantity in quantities
    } == {"opening-a", "opening-b"}


def test_duplicate_physical_opening_identity_fails_closed() -> None:
    duplicate = _opening()
    with pytest.raises(ValueError, match="duplicate canonical opening identity"):
        publish_live_opening_area_quantities(
            _composition(duplicate, duplicate)
        )



def test_duplicate_with_abstained_member_cannot_hide_opening_identity_conflict() -> None:
    firm = _opening()
    unsupported = replace(
        firm,
        opening_kind=None,
        area_m2=None,
        figured_area_record_id=None,
        evidence_ids=("opening-1", "source-observation-2"),
    )
    assert _opening_quantity(firm) is not None
    assert _opening_quantity(unsupported) is None
    with pytest.raises(ValueError, match="duplicate canonical opening identity"):
        publish_live_opening_area_quantities(
            _composition(firm, unsupported)
        )


def test_duplicate_physical_id_across_distinct_canonical_ids_fails_closed() -> None:
    firm = _opening()
    unsupported = replace(
        _opening(canonical_id="opening-conflicting"),
        physical_opening_id=firm.physical_opening_id,
    )
    # Neither the conflicting canonical ID nor the duplicate physical ID
    # can be selected opportunistically based on which candidate has area.
    assert _opening_quantity(unsupported) is None
    with pytest.raises(ValueError, match="duplicate physical opening identity"):
        publish_live_opening_area_quantities(
            _composition(firm, unsupported)
        )


def test_independent_partial_opening_does_not_suppress_valid_hosted_quantity() -> None:
    firm = _opening()
    unresolved = replace(
        _opening(canonical_id="unresolved-opening"),
        host_wall_id=None,
        host_binding_record_id=None,
        host_frame_record_id=None,
    )
    assert _opening_quantity(unresolved) is None
    quantities = publish_live_opening_area_quantities(
        _composition(firm, unresolved)
    )
    assert len(quantities) == 1
    assert quantities[0].input_entity_ids == ("opening-1",)


def test_figured_opening_quantity_is_sealable_and_commercially_projectable() -> None:
    opening = _opening()
    quantity = _opening_quantity(opening)
    assert quantity is not None

    trace = CommercialTakeoffSourceTrace(
        workspace_id=1,
        project_id="project-fixture",
        document_id=opening.document_id,
        source_sha256=opening.source_sha256,
        source_page=opening.page_id,
        viewport_id=opening.viewport_id or "viewport-fixture",
        revision_id=opening.revision_id,
        current_revision_id=opening.revision_id,
        evidence_ids=tuple(quantity.evidence_ids),
        canonical_entity_ids=(opening.canonical_opening_id,),
    )
    authority = CommercialMeasurementAuthority(
        method="figured_dimension",
        figured_dimension_ids=(opening.figured_area_record_id,),
    )

    sealed = seal_source_closed_quantity(quantity, trace=trace)
    assert sealed.lineage_ok is True
    assert sealed.object_identity_refs == (opening.canonical_opening_id,)
    assert sealed.value == pytest.approx(2.172)
    assert sealed.unit == "m2"

    row = quantity_evidence_to_takeoff_output_row(
        quantity,
        trace=trace,
        authority=authority,
    )
    assert row is not None
    assert row["quantity"] == pytest.approx(2.172)
    assert row["quantity_id"] == quantity.quantity_id
    assert row["canonical_entity_ids"] == [opening.canonical_opening_id]
    assert row["measurement_method"] == "figured_dimension"
    assert row["figured_dimension_ids"] == [opening.figured_area_record_id]
    # Existing commercial governance remains intact: automated quantities
    # enter customer takeoff as review rows rather than bypassing approval.
    assert row["quantity_status"] == "To review"


def test_live_opening_run_seals_identity_and_source_lineage_without_identity_map() -> None:
    composition = _composition(
        _opening(canonical_id="opening-a"),
        _opening(
            canonical_id="opening-b",
            kind="door",
            area_m2=3.15,
            figured_area_record_id="figured-b",
        ),
    )
    traces = build_live_opening_area_source_traces(
        composition,
        workspace_id=7,
        project_id="source-project",
    )
    quantities = publish_live_opening_area_quantities(composition)

    assert set(traces) == {quantity.quantity_id for quantity in quantities}
    for quantity in quantities:
        trace = traces[quantity.quantity_id]
        assert trace.project_id == "source-project"
        assert trace.source_sha256 == SHA
        assert trace.viewport_id == quantity.metadata["viewport_id"]
        assert trace.canonical_entity_ids == quantity.input_entity_ids
        assert set(quantity.evidence_ids).issubset(set(trace.evidence_ids))

    sealed = seal_live_opening_area_run(
        composition,
        workspace_id=7,
        project_id="source-project",
    )
    assert len(sealed.quantities) == 2
    assert all(row.lineage_ok for row in sealed.quantities)
    assert {
        row.object_identity_refs[0] for row in sealed.quantities
    } == {"opening-a", "opening-b"}
    assert sealed.source_sha256s == (SHA,)
    assert sealed.revision_ids == ("rev-1",)


def test_source_closed_export_excludes_unhosted_openings() -> None:
    hosted = _opening(canonical_id="hosted")
    unhosted = replace(
        _opening(canonical_id="unhosted"),
        host_wall_id=None,
        host_binding_record_id=None,
        host_frame_record_id=None,
    )
    sealed = seal_live_opening_area_run(
        _composition(hosted, unhosted),
        workspace_id=3,
        project_id="source-project",
    )
    assert len(sealed.quantities) == 1
    assert sealed.quantities[0].object_identity_refs == ("hosted",)


def test_source_closed_trace_rejects_canonical_evidence_dropout() -> None:
    opening = _opening()
    quantity = _opening_quantity(opening)
    assert quantity is not None
    damaged = replace(
        opening,
        evidence_ids=tuple(
            value
            for value in opening.evidence_ids
            if value != opening.figured_area_record_id
        ),
    )
    composition = _composition(damaged)
    # The publication gate itself rejects this quantity before sealing rather
    # than allowing an incomplete source trace to be constructed.
    assert publish_live_opening_area_quantities(composition) == ()


def test_live_opening_source_closed_run_is_deterministic() -> None:
    composition = _composition(
        _opening(canonical_id="opening-a"),
        _opening(
            canonical_id="opening-b",
            kind="door",
            area_m2=3.15,
            figured_area_record_id="figured-b",
        ),
    )
    first = seal_live_opening_area_run(
        composition,
        workspace_id=7,
        project_id="source-project",
    )
    second = seal_live_opening_area_run(
        composition,
        workspace_id=7,
        project_id="source-project",
    )
    assert first.run_id == second.run_id
    assert first.fingerprint == second.fingerprint
    assert first.to_json() == second.to_json()


@pytest.mark.parametrize(
    "missing",
    (
        "document_id",
        "revision_id",
        "source_sha256",
        "snapshot_id",
        "page_id",
        "representative_observation_id",
    ),
)
def test_opening_area_rejects_missing_source_lineage(missing: str) -> None:
    opening = _opening()
    assert _opening_quantity(opening) is not None
    assert _opening_quantity(replace(opening, **{missing: ""})) is None


def test_opening_area_quantity_retains_source_snapshot_metadata() -> None:
    quantity = _opening_quantity(_opening())
    assert quantity is not None
    assert quantity.metadata["snapshot_id"] == "snap-1"


def test_foreign_revision_opening_cannot_publish_area() -> None:
    stale = replace(_opening(), revision_id="foreign-revision")
    with pytest.raises(ValueError, match="revision conflicts"):
        publish_live_opening_area_quantities(_composition(stale))


def test_foreign_revision_unsupported_opening_cannot_hide_conflict() -> None:
    proven = _opening(canonical_id="opening-proven")
    stale = replace(
        _opening(canonical_id="opening-stale", area_m2=None),
        revision_id="foreign-revision",
    )
    with pytest.raises(ValueError, match="revision conflicts"):
        publish_live_opening_area_quantities(_composition(proven, stale))


@pytest.mark.parametrize("untyped_metric", (True, False, "2.172", None))
def test_opening_area_requires_typed_original_metric_m2(untyped_metric):
    assert _opening_quantity(_opening(area_m2=untyped_metric)) is None
    assert _opening_quantity(_opening()) is not None


@pytest.mark.parametrize("receipts", (
    (), ("source-observation-1", "source-observation-1"),
    ("source-observation-1", ""),
    ("source-observation-1", "  "),
    ("source-observation-1", 42),
    None,
))
def test_opening_area_never_normalizes_corrupted_original_source_receipts(receipts):
    forged = replace(_opening(), evidence_ids=receipts)
    assert _opening_quantity(forged) is None
    assert _opening_quantity(_opening()) is not None


@pytest.mark.parametrize("field,value", (
    ("document_id", "foreign-document"),
    ("revision_id", "foreign-revision"),
    ("source_sha256", "f" * 64),
    ("snapshot_id", "foreign-snapshot"),
    ("viewport_id", "foreign-viewport"),
    ("canonical_opening_id", "foreign-opening"),
    ("physical_opening_id", "foreign-opening"),
))
def test_sealed_opening_area_rejects_replayed_foreign_source_ownership(field, value):
    from pb_live_opening_source_closed_export import _build_opening_area_source_traces
    from pb_source_closed_run_export import SourceClosedRunConflictError

    opening = _opening()
    quantity = _opening_quantity(opening)
    assert quantity is not None
    forged = replace(quantity, metadata={**dict(quantity.metadata), field: value})
    with pytest.raises(SourceClosedRunConflictError, match="source.*identity mismatch"):
        _build_opening_area_source_traces(
            (forged,), (opening,),
            workspace_id=1, project_id="source-project",
        )


def test_source_closed_opening_claim_cannot_hide_duplicate_physical_evidence():
    from pb_live_opening_source_closed_export import _build_opening_area_source_traces
    from pb_source_closed_run_export import SourceClosedRunConflictError
    from copy import copy

    opening = _opening()
    quantity = _opening_quantity(opening)
    assert quantity is not None
    bad_opening = replace(opening, evidence_ids=(
        *opening.evidence_ids, opening.evidence_ids[0],
    ))
    with pytest.raises(SourceClosedRunConflictError, match="source evidence"):
        _build_opening_area_source_traces(
            (quantity,), (bad_opening,),
            workspace_id=1, project_id="source-project",
        )

    forged = copy(quantity)
    object.__setattr__(forged, "evidence_ids", (*quantity.evidence_ids, ""))
    with pytest.raises(SourceClosedRunConflictError, match="source evidence"):
        _build_opening_area_source_traces(
            (forged,), (opening,),
            workspace_id=1, project_id="source-project",
        )
    assert len(_build_opening_area_source_traces(
        (quantity,), (opening,),
        workspace_id=1, project_id="source-project",
    )) == 1
