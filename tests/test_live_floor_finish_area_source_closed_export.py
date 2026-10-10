from __future__ import annotations

from copy import copy

from dataclasses import replace

import pytest

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_live_canonical_floor_surface import LiveCanonicalFloorSurfaceObject
from pb_live_external_physical_net_wall_publication import (
    LiveExternalPhysicalNetWallPublication,
)
from pb_customer_output_verification import verify_sealed_customer_output
from pb_live_floor_finish_customer_projection import (
    project_live_floor_finish_customer_rows,
)
from pb_live_floor_finish_area_source_closed_export import (
    build_live_floor_finish_area_source_traces,
    seal_live_floor_finish_area_run,
)
from pb_live_physical_net_wall_integration import LivePhysicalNetWallClaim
from pb_migration_contracts import EvidenceResolutionStatus, QuantityEvidence
from pb_source_closed_run_export import SourceClosedRunConflictError


def _floor() -> LiveCanonicalFloorSurfaceObject:
    return LiveCanonicalFloorSurfaceObject(
        canonical_floor_id="floor-1",
        physical_floor_surface_id="floor-1",
        room_entity_id="room-1",
        document_id="doc-1",
        revision_id="rev-1",
        source_sha256="a" * 64,
        snapshot_id="snap-1",
        page_id="1",
        viewport_id="vp-1",
        polygon_pdf_pts=((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)),
        area_page_pts2=100.0,
        bounding_wall_ids=("w1", "w2", "w3", "w4"),
        canonical_bounding_wall_ids=(),
        source_room_face_record_id="face-1",
        evidence_ids=("ev-room", "ev-area", "ev-occ", "ev-def"),
        geometry_complete=True,
        metric_geometry_complete=False,
        metric_area_m2=8.64,
        metric_area_quantity_id="room-area-1",
        metric_area_authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        finish_descriptor="tile",
        structural_slab_id=None,
        physical_floor_surface_identity_resolved=True,
        commercial_quantity_authority=False,
    )


def _quantity() -> QuantityEvidence:
    return QuantityEvidence(
        quantity_id="floor-finish-q1",
        family="floor_finish_area",
        semantic_key="floor_finish_area:floor-1:FT1:tile",
        value=8.64,
        unit="m2",
        input_entity_ids=("floor-1",),
        formula="authenticated_documented_floor_finish",
        formula_version="1",
        evidence_ids=("ev-area", "ev-occ", "ev-def"),
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        status=AuthorityStatus.FIRM.value,
        confidence=1.0,
        abstained=False,
        blocking_reasons=(),
        reason_codes=("authenticated_cross_view_floor_finish_area",),
        metadata={
            "source_sha256": "a" * 64,
            "revision_id": "rev-1",
            "page_no": "1",
            "viewport_id": "vp-1",
            "canonical_floor_id": "floor-1",
            "physical_floor_surface_id": "floor-1",
            "source_room_face_record_id": "face-1",
            "finish_code": "FT1",
            "semantic_finish": "tile",
            "support_snapshot_id": "semantic-snap-1",
            "support_page_id": "9",
            "support_viewport_id": "finish-vp",
            "finish_definition_record_id": "def-1",
            "finish_occurrence_record_id": "occ-1",
            "finish_occurrence_evidence_id": "ev-occ",
            "source_dimension_page_id": "2",
        },
    )


def _publication() -> LiveExternalPhysicalNetWallPublication:
    return LiveExternalPhysicalNetWallPublication(
        revision_id="rev-1",
        status=EvidenceResolutionStatus.ABSTAINED,
        reason_codes=("test",),
        quantity_evidence=None,
        canonical_walls=(),
        external_wall_ids=(),
        gross_geometry_record_ids=(),
        whole_wall_role_record_ids=(),
        physical_void_record_ids=(),
        opening_universe_record_ids=(),
    )


def _claim(floor: LiveCanonicalFloorSurfaceObject | None = None) -> LivePhysicalNetWallClaim:
    floor = floor or _floor()
    return LivePhysicalNetWallClaim(
        status=EvidenceResolutionStatus.ABSTAINED,
        reason_codes=("test",),
        quantity_m2=None,
        source_pages=(),
        canonical_walls=(),
        canonical_wall_status=EvidenceResolutionStatus.ABSTAINED,
        canonical_wall_reason_codes=(),
        canonical_wall_source_pages=(),
        unresolved_wall_candidate_ids=(),
        canonical_openings=(),
        canonical_rooms=(),
        canonical_floors=(floor,),
        canonical_floor_status=EvidenceResolutionStatus.CORROBORATED,
        canonical_floor_reason_codes=(),
        canonical_floor_source_pages=(1,),
        canonical_room_status=EvidenceResolutionStatus.ABSTAINED,
        canonical_room_reason_codes=(),
        canonical_room_source_pages=(),
        external_wall_ids=(),
        evidence_ids=(),
        quantity_id=None,
        confidence=0.0,
        publication=_publication(),
        floor_finish_quantity_evidence=(_quantity(),),
    )


def test_floor_finish_quantity_seals_on_exact_canonical_floor_lineage() -> None:
    run = seal_live_floor_finish_area_run(
        _claim(),
        workspace_id=1,
        project_id="project-1",
    )

    assert len(run.quantities) == 1
    row = run.quantities[0]
    assert row.family == "floor_finish_area"
    assert row.value == 8.64
    assert row.object_identity_refs == ("floor-1",)
    assert row.lineage_ok is True
    assert set(row.trace_canonical_entity_ids) >= {"floor-1", "room-1"}

    claim = _claim()
    traces = build_live_floor_finish_area_source_traces(
        claim,
        workspace_id=1,
        project_id="project-1",
    )
    quantity_id = claim.floor_finish_quantity_evidence[0].quantity_id
    trace = traces[quantity_id]
    assert trace.metadata["support_page_id"] == "9"
    assert trace.metadata["support_viewport_id"] == "finish-vp"


def test_floor_finish_export_rejects_missing_semantic_snapshot() -> None:
    claim = _claim()
    quantity = claim.floor_finish_quantity_evidence[0]
    tampered = replace(
        quantity,
        metadata={
            **dict(quantity.metadata),
            "support_snapshot_id": "",
        },
    )
    claim = replace(claim, floor_finish_quantity_evidence=(tampered,))
    with pytest.raises(
        SourceClosedRunConflictError,
        match="semantic mismatch",
    ):
        seal_live_floor_finish_area_run(
            claim,
            workspace_id=1,
            project_id="project-1",
        )


def test_floor_finish_export_rejects_semantic_drift_from_canonical_floor() -> None:
    bad_floor = replace(_floor(), finish_descriptor="vinyl")
    with pytest.raises(
        SourceClosedRunConflictError,
        match="semantic mismatch",
    ):
        seal_live_floor_finish_area_run(
            _claim(bad_floor),
            workspace_id=1,
            project_id="project-1",
        )


def test_floor_finish_seal_projects_exactly_one_customer_row() -> None:
    claim = _claim()
    run = seal_live_floor_finish_area_run(
        claim,
        workspace_id=1,
        project_id="project-1",
    )
    rows = project_live_floor_finish_customer_rows(
        claim,
        workspace_id=1,
        project_id="project-1",
    )

    assert len(run.quantities) == len(rows) == 1
    row = rows[0]
    assert row["quantity_id"] == run.quantities[0].quantity_id
    assert row["quantity_family"] == "floor_finish_area"
    assert row["quantity_status"] == "To review"
    assert row["origin"] == "AI"
    assert row["row_role"] == "floor_area"
    assert row["finish_system"] == "tile"

    report = verify_sealed_customer_output(run, rows)
    assert report.valid_quantity_count == 1
    assert report.customer_row_count == 1
    assert report.verified_quantity_ids == (run.quantities[0].quantity_id,)

    persisted = {
        "workspace_id": row["workspace_id"],
        "section": row["section"],
        "element": row["element"],
        "location": row["location"],
        "substrate": row["substrate"],
        "finish_system": row["finish_system"],
        "quantity": row["quantity"],
        "unit": "m²",
        "quantity_status": row["quantity_status"],
        "source_page": row["source_page"],
        "source_reference": "PB Auto Geometry v1.2.19 · " + row["source_reference"],
        "inclusion_status": row["inclusion_status"],
        "confidence": "Documented",
        "notes": row["notes"],
        "row_role": row["row_role"],
    }
    persisted_report = verify_sealed_customer_output(run, [persisted])
    assert persisted_report.verified_quantity_ids == (
        run.quantities[0].quantity_id,
    )


def test_floor_finish_seal_rejects_one_occurrence_on_two_physical_floors() -> None:
    original = _floor()
    other = replace(
        original,
        canonical_floor_id="floor-2",
        physical_floor_surface_id="floor-2",
        room_entity_id="room-2",
        source_room_face_record_id="face-2",
    )
    first = _quantity()
    second = replace(
        first,
        quantity_id="floor-finish-q2",
        semantic_key="floor_finish_area:floor-2:FT1:tile",
        input_entity_ids=("floor-2",),
        metadata={
            **dict(first.metadata),
            "canonical_floor_id": "floor-2",
            "physical_floor_surface_id": "floor-2",
            "source_room_face_record_id": "face-2",
        },
    )
    claim = replace(
        _claim(), canonical_floors=(original, other),
        floor_finish_quantity_evidence=(first, second),
    )
    with pytest.raises(
        SourceClosedRunConflictError,
        match="source occurrence has competing physical floors",
    ):
        seal_live_floor_finish_area_run(
            claim, workspace_id=1, project_id="project-1",
        )


def test_floor_finish_seal_rejects_multiple_quantities_for_one_floor() -> None:
    first = _quantity()
    second = replace(
        first,
        quantity_id="floor-finish-q2",
        semantic_key="floor_finish_area:floor-1:FT2:tile",
        metadata={
            **dict(first.metadata),
            "finish_occurrence_record_id": "occ-2",
        },
    )
    claim = replace(
        _claim(),
        floor_finish_quantity_evidence=(first, second),
    )
    with pytest.raises(
        SourceClosedRunConflictError,
        match="canonical floor has competing finish area quantities",
    ):
        seal_live_floor_finish_area_run(
            claim, workspace_id=1, project_id="project-1",
        )


@pytest.mark.parametrize(
    "receipt",
    ("finish_occurrence_record_id", "finish_definition_record_id"),
)
def test_floor_finish_seal_rejects_missing_source_semantic_receipt(receipt: str) -> None:
    quantity = _quantity()
    invalid = replace(
        quantity,
        metadata={**dict(quantity.metadata), receipt: ""},
    )
    claim = replace(_claim(), floor_finish_quantity_evidence=(invalid,))
    with pytest.raises(
        SourceClosedRunConflictError,
        match="source occurrence/definition receipt is missing",
    ):
        seal_live_floor_finish_area_run(
            claim, workspace_id=1, project_id="project-1",
        )


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"unit": "ft2"}, "FIRM m2"),
        ({"status": AuthorityStatus.BLOCKED.value}, "FIRM m2"),
    ),
)
def test_floor_finish_seal_requires_firm_metric_area_quantity(
    changes: dict, reason: str,
) -> None:
    invalid = replace(_quantity(), **changes)
    claim = replace(_claim(), floor_finish_quantity_evidence=(invalid,))
    with pytest.raises(SourceClosedRunConflictError, match=reason):
        seal_live_floor_finish_area_run(
            claim, workspace_id=1, project_id="project-1",
        )


@pytest.mark.parametrize(
    ("receipt_key", "reason"),
    (
        ("source_room_face_record_id", "source room face mismatch"),
        ("page_no", "source page mismatch"),
    ),
)
def test_floor_finish_seal_rejects_stale_source_face_or_page(
    receipt_key: str, reason: str,
) -> None:
    quantity = _quantity()
    stale = replace(
        quantity,
        metadata={**dict(quantity.metadata), receipt_key: "foreign-source"},
    )
    claim = replace(_claim(), floor_finish_quantity_evidence=(stale,))
    with pytest.raises(SourceClosedRunConflictError, match=reason):
        seal_live_floor_finish_area_run(
            claim, workspace_id=1, project_id="project-1",
        )


def test_floor_finish_seal_rejects_alias_canonical_ids_for_same_physical_floor() -> None:
    original = _floor()
    alias = replace(
        original,
        canonical_floor_id="floor-alias",
        # Replayed source owned by the same physical floor, not a second one.
        physical_floor_surface_id=original.physical_floor_surface_id,
    )
    first = _quantity()
    alias_quantity = replace(
        first,
        quantity_id="floor-finish-alias-q2",
        semantic_key="floor_finish_area:floor-alias:FT2:tile",
        input_entity_ids=(alias.canonical_floor_id,),
        metadata={
            **dict(first.metadata),
            "canonical_floor_id": alias.canonical_floor_id,
            "finish_occurrence_record_id": "occ-alias",
        },
    )
    claim = replace(
        _claim(),
        canonical_floors=(original, alias),
        floor_finish_quantity_evidence=(first, alias_quantity),
    )
    with pytest.raises(
        SourceClosedRunConflictError,
        match="physical floor has competing finish area quantities",
    ):
        seal_live_floor_finish_area_run(
            claim, workspace_id=1, project_id="project-1",
        )


@pytest.mark.parametrize(
    ("receipt", "value"),
    (
        ("finish_occurrence_evidence_id", ""),
        ("finish_occurrence_evidence_id", "foreign-evidence"),
    ),
)
def test_floor_finish_seal_requires_exact_source_occurrence_witness(
    receipt: str, value: str,
) -> None:
    original = _quantity()
    altered = replace(
        original,
        metadata={**dict(original.metadata), receipt: value},
    )
    claim = replace(_claim(), floor_finish_quantity_evidence=(altered,))
    with pytest.raises(
        SourceClosedRunConflictError,
        match="occurrence evidence receipt mismatch",
    ):
        seal_live_floor_finish_area_run(
            claim, workspace_id=1, project_id="project-1",
        )


def test_floor_finish_seal_cannot_use_missing_floor_occurrence_witness() -> None:
    original = _floor()
    replayed = replace(
        original,
        evidence_ids=tuple(
            source for source in original.evidence_ids if source != "ev-occ"
        ),
    )
    claim = replace(_claim(replayed))
    with pytest.raises(
        SourceClosedRunConflictError,
        match="occurrence evidence receipt mismatch",
    ):
        seal_live_floor_finish_area_run(
            claim, workspace_id=1, project_id="project-1",
        )


@pytest.mark.parametrize("evidence", (
    ("ev-area", "ev-occ", "ev-occ", "ev-def"),
    ("ev-area", "ev-occ", "   ", "ev-def"),
    ("ev-area", "", "ev-occ", "ev-def"),
    (),
))
def test_floor_finish_source_seal_rejects_incomplete_or_duplicate_evidence(evidence):
    claim = _claim()
    altered_quantity = copy(claim.floor_finish_quantity_evidence[0])
    object.__setattr__(altered_quantity, "evidence_ids", evidence)
    altered_claim = replace(claim, floor_finish_quantity_evidence=(altered_quantity,))
    with pytest.raises(SourceClosedRunConflictError):
        build_live_floor_finish_area_source_traces(
            altered_claim, workspace_id=1, project_id="project-1",
        )
    assert len(build_live_floor_finish_area_source_traces(
        claim, workspace_id=1, project_id="project-1",
    )) == 1


@pytest.mark.parametrize("points", (
    ((0., 0.), (float("nan"), 0.), (2., 2.)),
    ((0., 0.), (float("inf"), 0.), (2., 2.)),
    ((1., 1.), (1., 2.), (1., 3.)),
    ((1., 1.), (2., 1.)),
))
def test_floor_finish_source_seal_rejects_invalid_source_polygon(points):
    altered_floor = replace(_floor(), polygon_pdf_pts=points)
    with pytest.raises(SourceClosedRunConflictError, match="source polygon is invalid"):
        build_live_floor_finish_area_source_traces(
            _claim(altered_floor), workspace_id=1, project_id="project-1",
        )


def test_floor_finish_cannot_seal_without_complete_original_physical_room_face():
    for floor in (
        replace(_floor(), geometry_complete=False),
        replace(_floor(), polygon_pdf_pts=()),
    ):
        with pytest.raises(SourceClosedRunConflictError, match="polygon is invalid or incomplete"):
            build_live_floor_finish_area_source_traces(
                _claim(floor), workspace_id=1, project_id="project-1",
            )
