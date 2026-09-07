"""tests/editable_3d/test_commercial_sync.py — PR D.11H test suite.

pb_editable_3d_commercial_sync.py is the pure logic bridging D.11G's
approved editable-3D quantities into the app's real, independent commercial
take-off pipeline (pb_takeoff_authority_v164.py — model-surface rows). It
never invents its own "is this commercially eligible" answer; it only
decides whether the *sync action* is allowed to run, then builds a row
candidate that the existing, unmodified pb_takeoff_authority_v164 functions
(is_model_surface_row, approve_model_surface_row, model_surface_authority,
takeoff_row_publishability, is_jobhub_eligible_row) independently recognize
as genuinely commercial. This suite proves both halves: the eligibility
gate rejects everything it should, and a row built for an eligible
object/quantity is actually, verifiably accepted by the real pipeline —
never merely asserted.
"""
from __future__ import annotations

import math

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import EditableObjectType, EditableGeometryObject
from pb_editable_3d_commercial_sync import build_model_surface_row_candidate, check_sync_eligibility
from pb_takeoff_authority_v164 import (
    approve_model_surface_row,
    is_jobhub_eligible_row,
    is_model_surface_row,
    model_surface_authority,
    takeoff_row_publishability,
)
from pb_takeoff_output_authority import TakeoffOutputRow, TakeoffSourceType, create_takeoff_output_row


def _approved_object(**overrides) -> EditableGeometryObject:
    defaults = dict(
        object_id="MASS-1", object_type=EditableObjectType.WALL.value,
        source_page=3, source_sheet="WD-03", level_id="Ground",
        coordinates_or_measurements={"length": 9.0, "height": 2.7},
        authority_status=AuthorityStatus.FIRM.value,
        approved_by="Lead Estimator Bryce", approved_at="2026-09-08T00:00:00+00:00",
        revision_hash="REV-CURRENT",
    )
    defaults.update(overrides)
    return EditableGeometryObject(**defaults)


def _current_row(**overrides) -> TakeoffOutputRow:
    kwargs = dict(
        quantity_id="MASS-1-wall_gross_area-BASELINE-REV-CORR-1",
        description="Wall MASS-1 — Gross Area (corrected)",
        value=24.3, unit="m²", trade="general",
        source_type=TakeoffSourceType.USER_APPROVED.value,
        source_page=3, source_sheet="WD-03", geometry_ref="MASS-1",
        approved_by="Lead Estimator Bryce", approved_at="2026-09-08T00:00:00+00:00",
        revision_hash="REV-CURRENT", current_revision_hash="REV-CURRENT",
        allow_zero=False,
    )
    kwargs.update(overrides)
    return create_takeoff_output_row(**kwargs)


class TestCheckSyncEligibilityAcceptsARealApprovedQuantity:
    def test_eligible_object_and_row_produce_no_blocking_reasons(self):
        obj = _approved_object()
        row = _current_row()
        assert row.is_publishable is True  # sanity check on the fixture
        assert check_sync_eligibility(obj, row) == []


class TestCheckSyncEligibilityFailsClosed:
    def test_unapproved_object_is_rejected(self):
        obj = _approved_object(
            authority_status=AuthorityStatus.REVIEW_REQUIRED.value, approved_by=None, approved_at=None,
        )
        row = _current_row()
        reasons = check_sync_eligibility(obj, row)
        assert any("not explicitly approved" in r for r in reasons)

    def test_stale_revision_is_rejected(self):
        obj = _approved_object(revision_hash="REV-NEWER")
        row = _current_row()  # still revision_hash="REV-CURRENT"
        reasons = check_sync_eligibility(obj, row)
        assert any("stale" in r for r in reasons)

    def test_unpublishable_row_is_rejected(self):
        obj = _approved_object()
        row = _current_row(source_type=TakeoffSourceType.USER_CORRECTED.value, approved_by=None, approved_at=None)
        assert row.is_publishable is False  # sanity check on the fixture
        reasons = check_sync_eligibility(obj, row)
        assert any("not commercially publishable" in r for r in reasons)

    def test_row_with_blocking_reasons_is_rejected(self):
        obj = _approved_object()
        row = _current_row()
        row.blocking_reasons = ["Stale revision: drawing revision was superseded"]
        reasons = check_sync_eligibility(obj, row)
        assert any("blocking reasons" in r for r in reasons)

    def test_non_finite_value_is_rejected(self):
        obj = _approved_object()
        row = _current_row()
        row.value = float("nan")  # simulate corrupted downstream state (mutated post-construction)
        reasons = check_sync_eligibility(obj, row)
        assert any("non-finite" in r for r in reasons)

    def test_negative_value_is_rejected(self):
        obj = _approved_object()
        row = _current_row()
        row.value = -1.0
        reasons = check_sync_eligibility(obj, row)
        assert any("non-finite or negative" in r for r in reasons)

    def test_missing_source_trace_is_rejected(self):
        obj = _approved_object(source_page=None, source_sheet=None)
        row = _current_row()
        reasons = check_sync_eligibility(obj, row)
        assert any("missing source trace" in r for r in reasons)


class TestBuildModelSurfaceRowCandidateEntersTheRealCommercialPipeline:
    def test_candidate_is_recognized_as_a_model_surface_row(self):
        obj = _approved_object()
        row = _current_row()
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        assert is_model_surface_row(candidate)
        # Not yet approved — the real pipeline must not treat it as eligible
        # until approve_model_surface_row() has actually been called.
        approved_yet, _ = model_surface_authority(candidate)
        assert approved_yet is False

    def test_approved_candidate_is_genuinely_publishable_and_jobhub_eligible(self):
        obj = _approved_object()
        row = _current_row()
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        approved = approve_model_surface_row(
            candidate, source=f"Editable 3D approval — revision {obj.revision_hash}",
            reviewed_by="Senior Estimator Jones", reviewed_at="2026-09-08T00:05:00+00:00",
        )

        authority_ok, authority_reason = model_surface_authority(approved)
        assert authority_ok, authority_reason

        publishable, publishable_reason = takeoff_row_publishability(approved)
        assert publishable, publishable_reason

        eligible, eligible_reason = is_jobhub_eligible_row(approved)
        assert eligible, eligible_reason

    def test_editing_a_consequential_field_after_approval_revokes_authority(self):
        # Proves the existing pipeline's own tamper-detection genuinely
        # applies to a synced row — this module never bypasses it.
        obj = _approved_object()
        row = _current_row()
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        approved = approve_model_surface_row(
            candidate, source="Editable 3D approval", reviewed_by="Bryce", reviewed_at="2026-09-08T00:05:00+00:00",
        )
        tampered = dict(approved)
        tampered["quantity"] = approved["quantity"] + 1.0  # edited after approval, fingerprint unchanged
        authority_ok, _ = model_surface_authority(tampered)
        assert authority_ok is False

    def test_candidate_preserves_real_source_trace_and_traceability_notes(self):
        obj = _approved_object(source_page=7, source_sheet="WD-12")
        row = _current_row(source_page=7, source_sheet="WD-12")
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        assert candidate["source_page"] == "7"
        assert candidate["source_reference"] == "WD-12"
        assert obj.object_id in candidate["notes"]
        assert obj.revision_hash in candidate["notes"]
        assert obj.approved_by in candidate["notes"]

    def test_candidate_quantity_and_unit_match_the_synced_row_exactly(self):
        obj = _approved_object()
        row = _current_row(value=24.3, unit="m²")
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        assert candidate["quantity"] == 24.3
        assert candidate["unit"] == "m²"
        assert math.isfinite(candidate["quantity"])

    def test_source_page_is_text_matching_the_takeoff_rows_column_affinity(self):
        # takeoff_rows.source_page is a TEXT column — SQLite coerces any
        # non-text value into text on storage regardless of what Python
        # type was passed to the INSERT. If the candidate carried an int
        # here, the fingerprint computed before insert would never match
        # the row once read back from the database (caught via full manual
        # browser + real-DB verification, not by an in-memory-only test).
        obj = _approved_object(source_page=3)
        row = _current_row(source_page=3)
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        assert candidate["source_page"] == "3"
        assert isinstance(candidate["source_page"], str)

    def test_fingerprint_survives_a_simulated_sqlite_text_affinity_round_trip(self):
        obj = _approved_object(source_page=3)
        row = _current_row(source_page=3)
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        approved = approve_model_surface_row(
            candidate, source="Editable 3D approval", reviewed_by="Bryce",
            reviewed_at="2026-09-08T00:05:00+00:00",
        )
        # Simulate exactly what sqlite3 does to a TEXT-affinity column on a
        # real round trip: source_page comes back as str regardless of what
        # was inserted. A correct candidate is a no-op under this cast.
        round_tripped = dict(approved)
        round_tripped["source_page"] = str(approved["source_page"])
        authority_ok, reason = model_surface_authority(round_tripped)
        assert authority_ok, reason
