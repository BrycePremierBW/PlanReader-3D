"""tests/editable_3d/test_editable_3d_takeoff_end_to_end.py — PR D.6.

One deterministic end-to-end proof, no live AI/API, wiring together D.1-D.5's
editable-3D correction pipeline with B.4's takeoff authority and PR C's JobHub
publish contract:

  generate geometry -> derive quantity -> approve it
  -> edit a wall in editable 3D -> old quantity stales, publishability turns false
  -> recalculate the new quantity (review_required, not publishable)
  -> approve the corrected geometry, then the new quantity
  -> commercial publishability turns true
  -> build a JobHub payload: only the latest approved quantity appears,
     the old stale quantity is excluded, fingerprints/revisions differ
     appropriately, and the whole audit chain (events, revisions, correction_ids)
     remains inspectable throughout.

Fixture: a simple rectangular room's single wall — known length/height, one door
opening, one finish tag — corrected once (a site remeasure of wall length).
"""
from __future__ import annotations

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_takeoff_output_authority import (
    TakeoffSourceType,
    approve_takeoff_output_row,
    create_takeoff_output_row,
)
from pb_editable_3d_correction_model import (
    CorrectionField,
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
    approve_corrected_geometry,
)
from pb_editable_3d_quantity_recalculation import (
    RecalculationTarget,
    recalculate_quantities_for_correction,
)
from pb_planreader_jobhub_publish_contract import (
    PublishMode,
    build_jobhub_payload,
    partition_publishable_rows,
    run_jobhub_publish_preflight,
)


# Fixture: rectangular room, one wall, one door opening, known height, known finish.
WALL_ID = "WALL-LIVING-01"
INITIAL_LENGTH_M = 5.8
INITIAL_HEIGHT_M = 2.7
OPENING = {
    "opening_id": "DOOR-01", "opening_type": "door",
    "width_m": 0.9, "height_m": 2.1, "area_m2": 1.89, "deducts": True,
}
# Gross = 5.8 * 2.7 = 15.66; net = 15.66 - 1.89 = 13.77
INITIAL_GROSS_M2 = 15.66
INITIAL_NET_M2 = 13.77

PROJECT_IDENTITY = {"project_id": "JOB-E2E-1", "identity_confirmed": True}


def test_full_correction_and_approval_lifecycle_reaches_jobhub_payload():
    # ---------------------------------------------------------------------
    # 1. Generate geometry: extracted from the source PDF, registered in the
    #    editable-3D correction ledger.
    # ---------------------------------------------------------------------
    ledger = Editable3DCorrectionLedger()
    wall = EditableGeometryObject(
        object_id=WALL_ID,
        object_type=EditableObjectType.WALL.value,
        source_file_id="FILE-E2E-1",
        source_page=4,
        source_sheet="WD-04",
        source_region="B2:D6",
        geometry_ref="VEC-WALL-LIVING-01",
        scale_id="SCALE-P4-1_100",
        dimension_text_ids=["DIM-LIVING-LENGTH", "DIM-LIVING-HEIGHT"],
        confidence=0.9,
        coordinates_or_measurements={
            "length": INITIAL_LENGTH_M,
            "height": INITIAL_HEIGHT_M,
            "openings": [OPENING],
            "finish_tag": "PB01",
        },
        authority_status=AuthorityStatus.PROVISIONAL.value,
        revision_hash="GENESIS",
    )
    ledger.register_object(wall)
    initial_revision = ledger.get_object(WALL_ID).revision_hash
    assert initial_revision == "GENESIS"

    # ---------------------------------------------------------------------
    # 2. Derive the initial quantity from that (still-provisional) geometry.
    # ---------------------------------------------------------------------
    initial_row = create_takeoff_output_row(
        quantity_id="QTY-LIVING-GROSS-1",
        description="Living Room Wall — Wall Gross Area",
        value=INITIAL_GROSS_M2,
        unit="m²",
        trade="painting",
        source_type=TakeoffSourceType.PDF_SCALED,
        source_page=4,
        source_sheet="WD-04",
        geometry_ref=WALL_ID,
        scale_id="SCALE-P4-1_100",
        revision_hash=initial_revision,
    )
    assert initial_row.authority_status == AuthorityStatus.PROVISIONAL.value
    assert initial_row.is_publishable is False

    # ---------------------------------------------------------------------
    # 3. Approve the initial quantity (an estimator reviews the scaled draft).
    # ---------------------------------------------------------------------
    approved_initial_row = approve_takeoff_output_row(
        initial_row, approved_by="Estimator A", current_revision_hash=initial_revision,
    )
    assert approved_initial_row.is_publishable is True
    assert approved_initial_row.authority_status == "user_approved"
    initial_fingerprint = approved_initial_row.compute_fingerprint()

    ledger.link_dependent_quantities(WALL_ID, [approved_initial_row.quantity_id])
    assert ledger.get_object(WALL_ID).dependent_quantity_ids == [approved_initial_row.quantity_id]

    # ---------------------------------------------------------------------
    # 4. Edit one wall in editable 3D: a site remeasure corrects the length.
    # ---------------------------------------------------------------------
    CORRECTED_LENGTH_M = 6.0
    outcome = ledger.apply_correction(
        correction_id="CORR-E2E-LENGTH-1",
        object_id=WALL_ID,
        field=CorrectionField.LENGTH.value,
        new_value=CORRECTED_LENGTH_M,
        reason="Corrected against site remeasure",
        actor="Estimator B",
        source=CorrectionSource.EDITOR_3D.value,
        affected_quantity_ids=[approved_initial_row.quantity_id],
    )
    assert outcome.ok is True
    corrected_wall = ledger.get_object(WALL_ID)
    corrected_revision = corrected_wall.revision_hash
    assert corrected_revision != initial_revision
    # Correction is not approval (D.2): the object requires re-review.
    assert corrected_wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
    assert corrected_wall.approved_by is None
    assert corrected_wall.correction_ids == ["CORR-E2E-LENGTH-1"]
    # Original evidence is untouched (D.4).
    assert corrected_wall.source_page == 4
    assert corrected_wall.source_sheet == "WD-04"
    assert corrected_wall.original_geometry_ref == "VEC-WALL-LIVING-01"

    # ---------------------------------------------------------------------
    # 5 & 6. The old quantity becomes stale and loses commercial publishability.
    # ---------------------------------------------------------------------
    results = recalculate_quantities_for_correction(
        outcome.event, corrected_wall, existing_rows=[approved_initial_row],
    )
    gross_result = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)

    stale_old_row = gross_result.old_row
    assert stale_old_row is not None
    assert stale_old_row.quantity_id == approved_initial_row.quantity_id
    assert stale_old_row.is_publishable is False
    assert "stale_after_geometry_correction" in stale_old_row.blocking_reasons
    # The fingerprint over core commercial fields is unchanged — this proves the
    # underlying (now-superseded) measurement itself was never silently altered,
    # only its publishability was.
    assert stale_old_row.compute_fingerprint() == initial_fingerprint

    # ---------------------------------------------------------------------
    # 7 & 8. The new quantity is recalculated and starts review_required / not
    #    publishable — never auto-approved by the correction itself.
    # ---------------------------------------------------------------------
    new_row = gross_result.new_row
    assert new_row is not None
    expected_new_gross = CORRECTED_LENGTH_M * INITIAL_HEIGHT_M  # gross, before opening deduction
    assert gross_result.new_value == pytest.approx(expected_new_gross)
    assert new_row.value == pytest.approx(expected_new_gross)
    assert new_row.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
    assert new_row.is_publishable is False
    assert new_row.revision_hash == corrected_revision
    assert new_row.correction_id == "CORR-E2E-LENGTH-1"
    assert new_row.source_page == 4
    assert new_row.source_sheet == "WD-04"

    # ---------------------------------------------------------------------
    # 9. Approve the corrected geometry, then the new quantity — two separate,
    #    explicit acts (D.2), neither automatic.
    # ---------------------------------------------------------------------
    approve_corrected_geometry(
        ledger, object_id=WALL_ID, approved_by="Lead Estimator Bryce",
        current_revision_hash=corrected_revision,
    )
    approved_wall = ledger.get_object(WALL_ID)
    assert approved_wall.authority_status == AuthorityStatus.FIRM.value
    assert approved_wall.approved_by == "Lead Estimator Bryce"

    approved_new_row = approve_takeoff_output_row(
        new_row, approved_by="Lead Estimator Bryce", current_revision_hash=corrected_revision,
    )

    # ---------------------------------------------------------------------
    # 10. Commercial publishability becomes true.
    # ---------------------------------------------------------------------
    assert approved_new_row.is_publishable is True
    assert approved_new_row.revision_hash == corrected_revision
    assert approved_new_row.compute_fingerprint() != initial_fingerprint  # value changed

    # ---------------------------------------------------------------------
    # 11-13. Build the JobHub payload: only the latest approved quantity may
    #    enter a commercial payload; the stale row must be excluded first.
    # ---------------------------------------------------------------------
    all_candidate_rows = [stale_old_row, approved_new_row]
    partitioned = partition_publishable_rows(all_candidate_rows)
    assert len(partitioned["publishable"]) == 1
    assert partitioned["publishable"][0].quantity_id == approved_new_row.quantity_id
    assert stale_old_row not in partitioned["publishable"]

    preflight = run_jobhub_publish_preflight(
        rows=all_candidate_rows,
        project_identity=PROJECT_IDENTITY,
        drawing_revision={"revision_hash": corrected_revision},
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    # The full candidate set (stale + approved) is NOT valid for commercial
    # publish — the stale row must be filtered out first, exactly as PR C intends.
    assert preflight.is_valid is False

    payload = build_jobhub_payload(
        rows=partitioned["publishable"],
        project_identity=PROJECT_IDENTITY,
        drawing_revision={"revision_hash": corrected_revision},
        source_files=["living_room_plan.pdf"],
        created_by="Lead Estimator Bryce",
        publish_mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert payload.is_commercial_ready is True
    assert len(payload.quantities) == 1
    assert payload.quantities[0].quantity_id == approved_new_row.quantity_id
    assert payload.quantities[0].value == pytest.approx(CORRECTED_LENGTH_M * INITIAL_HEIGHT_M)
    # The stale row never appears anywhere in the payload.
    payload_ids = {q.quantity_id for q in payload.quantities}
    assert stale_old_row.quantity_id not in payload_ids or stale_old_row is approved_new_row

    # ---------------------------------------------------------------------
    # 14. Fingerprints/revisions differ appropriately.
    # ---------------------------------------------------------------------
    assert stale_old_row.revision_hash == initial_revision
    assert approved_new_row.revision_hash == corrected_revision
    assert stale_old_row.revision_hash != approved_new_row.revision_hash
    assert stale_old_row.compute_fingerprint() != approved_new_row.compute_fingerprint()
    payload_fp_1 = payload.payload_fingerprint
    payload_2 = build_jobhub_payload(
        rows=partitioned["publishable"],
        project_identity=PROJECT_IDENTITY,
        drawing_revision={"revision_hash": corrected_revision},
        source_files=["living_room_plan.pdf"],
        created_by="Lead Estimator Bryce",
        created_at=payload.created_at,
        publish_mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    # Same inputs -> same payload fingerprint (deterministic).
    assert payload_2.payload_fingerprint == payload_fp_1

    # ---------------------------------------------------------------------
    # 15. The entire audit chain remains available: the old row's original
    #    fingerprint, the correction event, the revision history, and the
    #    object's accumulated correction_ids are all still inspectable.
    # ---------------------------------------------------------------------
    assert stale_old_row.compute_fingerprint() == initial_fingerprint
    events = ledger.events_for_object(WALL_ID)
    assert len(events) == 1
    assert events[0].correction_id == "CORR-E2E-LENGTH-1"
    assert events[0].old_value == INITIAL_LENGTH_M
    assert events[0].new_value == CORRECTED_LENGTH_M
    assert events[0].reason == "Corrected against site remeasure"

    revisions = ledger.revisions_for_object(WALL_ID)
    assert len(revisions) == 1
    assert revisions[0].revision_hash == corrected_revision
    assert revisions[0].measurements_snapshot["length"] == CORRECTED_LENGTH_M

    final_wall = ledger.get_object(WALL_ID)
    assert final_wall.correction_ids == ["CORR-E2E-LENGTH-1"]
    assert final_wall.dependent_quantity_ids == [approved_initial_row.quantity_id]

    replayed_hash = ledger.replay(WALL_ID, genesis_hash="GENESIS")
    assert replayed_hash == corrected_revision

    # Deterministic replay proves the whole chain is reconstructable purely
    # from the event log — not just trusted because the live object says so.
    assert ledger.replay(WALL_ID, genesis_hash="GENESIS") == replayed_hash
