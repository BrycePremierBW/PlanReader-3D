"""tests/editable_3d/test_approval_persistence.py — PR D.11G test suite.

approve_corrected_geometry() (D.1/D.2) is reused verbatim as the single
approval mechanism — no second approval path is introduced. This suite
covers the three new fail-closed guards D.11G adds to it (BLOCKED
authority, non-finite geometry, internally inconsistent geometry), the
append-only persist/replay wrapper (approval_result_to_row /
replay_persisted_approvals), and the central D.11G invariant: a later
correction immediately invalidates a persisted approval, and replay must
never restore an approval that no longer matches the object's current
revision.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import (
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
    approve_corrected_geometry,
)
from pb_editable_3d_correction_persistence import (
    approval_result_to_row,
    correction_event_to_row,
    replay_persisted_approvals,
    replay_persisted_corrections,
)
from pb_editable_3d_model import WallHeightAuthority, WallModel
from pb_editable_3d_model_bridge import wall_model_to_editable_geometry_object


def _wall(**overrides) -> WallModel:
    kwargs = dict(
        wall_id="MASS-1", level_id="Ground", start_pt=(0.0, 0.0), end_pt=(6.0, 0.0),
        length_m=6.0, height_m=2.7, height_authority=WallHeightAuthority.USER_ENTERED.value,
        wall_type="standard", source_page_no=0, source_sheet_label="WD-04",
        scale_ratio="unknown", authority_status=AuthorityStatus.REVIEW_REQUIRED.value,
    )
    kwargs.update(overrides)
    return WallModel(**kwargs)


def _ledger_with_wall(wall: WallModel) -> Editable3DCorrectionLedger:
    ledger = Editable3DCorrectionLedger()
    ledger.register_object(wall_model_to_editable_geometry_object(wall))
    return ledger


def _correct_length(ledger: Editable3DCorrectionLedger, object_id: str, new_value: float, correction_id: str = "CORR-1"):
    return ledger.apply_correction(
        correction_id=correction_id, object_id=object_id, field="length",
        new_value=new_value, reason="Site remeasure", actor="Estimator",
        source=CorrectionSource.EDITOR_3D.value,
    )


class TestApprovalFailsClosedOnBlankActor:
    def test_whitespace_only_actor_is_rejected_by_the_backend_itself(self):
        # The UI already strips/validates before calling approve_corrected_geometry(),
        # but the backend must not rely on that — a whitespace-only string is
        # truthy in Python and must not slip past `if not approved_by`.
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        obj = ledger.get_object("MASS-1")
        with pytest.raises(ValueError, match="approved_by"):
            approve_corrected_geometry(
                ledger, object_id="MASS-1", approved_by="   ",
                current_revision_hash=obj.revision_hash,
            )

    def test_actor_is_stripped_before_being_stored(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        obj = ledger.get_object("MASS-1")
        result = approve_corrected_geometry(
            ledger, object_id="MASS-1", approved_by="  Bryce  ",
            current_revision_hash=obj.revision_hash,
        )
        assert result.approved_by == "Bryce"
        assert ledger.get_object("MASS-1").approved_by == "Bryce"


class TestApprovalFailsClosedOnBlockedAuthority:
    def test_blocked_object_cannot_be_approved(self):
        wall = _wall(height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value)
        ledger = _ledger_with_wall(wall)
        obj = ledger.get_object("MASS-1")
        assert obj.authority_status == AuthorityStatus.BLOCKED.value  # sanity check on the fixture
        with pytest.raises(ValueError, match="BLOCKED"):
            approve_corrected_geometry(
                ledger, object_id="MASS-1", approved_by="Estimator",
                current_revision_hash=obj.revision_hash,
            )


class TestApprovalFailsClosedOnNonFiniteGeometry:
    def test_non_finite_measurement_blocks_approval(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        obj = ledger.get_object("MASS-1")
        # apply_correction() itself would never produce a non-finite value
        # (create_correction_event already rejects it) — this simulates
        # malformed upstream data to exercise approval's own independent,
        # defensive check.
        corrupted = replace(obj, coordinates_or_measurements={**obj.coordinates_or_measurements, "height": float("nan")})
        ledger._objects["MASS-1"] = corrupted
        with pytest.raises(ValueError, match="non-finite"):
            approve_corrected_geometry(
                ledger, object_id="MASS-1", approved_by="Estimator",
                current_revision_hash=corrupted.revision_hash,
            )


class TestApprovalFailsClosedOnInconsistentGeometry:
    def test_length_mismatched_with_endpoint_segment_blocks_approval(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        obj = ledger.get_object("MASS-1")
        corrupted_measurements = dict(obj.coordinates_or_measurements)
        corrupted_measurements["end_pt"] = [100.0, 0.0]  # no longer matches length=6.0
        corrupted = replace(obj, coordinates_or_measurements=corrupted_measurements)
        ledger._objects["MASS-1"] = corrupted
        with pytest.raises(ValueError, match="inconsistent"):
            approve_corrected_geometry(
                ledger, object_id="MASS-1", approved_by="Estimator",
                current_revision_hash=corrupted.revision_hash,
            )


class TestApprovalHappyPathAndPersistenceRoundTrip:
    def test_approve_after_correction_sets_firm_and_persists_round_trip(self):
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0), length_m=6.0)
        live_ledger = _ledger_with_wall(wall)
        corr_outcome = _correct_length(live_ledger, "MASS-1", 9.0)
        result = approve_corrected_geometry(
            live_ledger, object_id="MASS-1", approved_by="Lead Estimator Bryce",
            current_revision_hash=corr_outcome.event.new_revision_hash,
            approved_at="2026-09-08T00:00:00+00:00",
        )
        live_obj = live_ledger.get_object("MASS-1")
        assert live_obj.authority_status == AuthorityStatus.FIRM.value
        assert live_obj.approved_by == "Lead Estimator Bryce"

        # Simulate a full restart: fresh ledger, fresh hydration of the same
        # genesis wall, replaying the persisted correction then the
        # persisted approval — exactly the D.11F/D.11G reload path.
        replay_ledger = _ledger_with_wall(wall)
        corr_row = correction_event_to_row(1, corr_outcome.event)
        replay_persisted_corrections(replay_ledger, [wall], [corr_row])
        approval_row = approval_result_to_row(1, "wall", result)
        warnings = replay_persisted_approvals(replay_ledger, [approval_row])

        assert warnings == []
        replayed_obj = replay_ledger.get_object("MASS-1")
        assert replayed_obj.authority_status == AuthorityStatus.FIRM.value
        assert replayed_obj.approved_by == "Lead Estimator Bryce"
        assert replayed_obj.approved_at == "2026-09-08T00:00:00+00:00"
        assert replayed_obj.revision_hash == live_obj.revision_hash == corr_outcome.event.new_revision_hash


class TestApprovalInvalidatedByLaterCorrection:
    def test_replay_does_not_restore_approval_superseded_by_a_later_correction(self):
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0), length_m=6.0)
        live_ledger = _ledger_with_wall(wall)
        corr1 = _correct_length(live_ledger, "MASS-1", 9.0, correction_id="CORR-1")
        result = approve_corrected_geometry(
            live_ledger, object_id="MASS-1", approved_by="Bryce",
            current_revision_hash=corr1.event.new_revision_hash,
        )
        # A second correction lands after the approval — invalidating it
        # live, via apply_correction()'s own unchanged invariant.
        corr2 = _correct_length(live_ledger, "MASS-1", 12.0, correction_id="CORR-2")
        assert live_ledger.get_object("MASS-1").authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert live_ledger.get_object("MASS-1").approved_by is None

        # Replay from scratch: both corrections, then the now-superseded approval.
        replay_ledger = _ledger_with_wall(wall)
        rows = [
            correction_event_to_row(1, corr1.event),
            correction_event_to_row(1, corr2.event),
        ]
        replay_persisted_corrections(replay_ledger, [wall], rows)
        approval_row = approval_result_to_row(1, "wall", result)
        warnings = replay_persisted_approvals(replay_ledger, [approval_row])

        assert warnings == []  # correctly and silently not restored — not an error
        replayed_obj = replay_ledger.get_object("MASS-1")
        assert replayed_obj.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert replayed_obj.approved_by is None
        assert replayed_obj.revision_hash == corr2.event.new_revision_hash


class TestApprovalReplayIntegrity:
    def test_orphaned_object_is_warned_and_skipped(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        approval_row = {
            "object_id": "MASS-DOES-NOT-EXIST", "revision_hash": "whatever",
            "approved_by": "Bryce", "approved_at": "2026-01-01T00:00:00+00:00",
        }
        warnings = replay_persisted_approvals(ledger, [approval_row])
        assert len(warnings) == 1
        assert "no longer exists" in warnings[0].reason

    def test_latest_of_multiple_approval_rows_wins(self):
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0), length_m=6.0)
        ledger = _ledger_with_wall(wall)
        genesis_hash = ledger.get_object("MASS-1").revision_hash
        row_old = {
            "object_id": "MASS-1", "revision_hash": "SOME-OLD-HASH-NO-LONGER-CURRENT",
            "approved_by": "Old Approver", "approved_at": "2020-01-01T00:00:00+00:00",
        }
        row_new = {
            "object_id": "MASS-1", "revision_hash": genesis_hash,
            "approved_by": "Current Approver", "approved_at": "2026-01-01T00:00:00+00:00",
        }
        warnings = replay_persisted_approvals(ledger, [row_old, row_new])
        assert warnings == []
        obj = ledger.get_object("MASS-1")
        assert obj.approved_by == "Current Approver"

    def test_approval_replay_failure_is_surfaced_as_a_warning_not_a_crash(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(EditableGeometryObject(
            object_id="MASS-UNTRACEABLE", object_type=EditableObjectType.WALL.value,
            source_page=None, source_sheet=None,
            coordinates_or_measurements={"length": 5.0, "height": 2.7},
            authority_status=AuthorityStatus.REVIEW_REQUIRED.value, revision_hash="GENESIS-X",
        ))
        approval_row = {
            "object_id": "MASS-UNTRACEABLE", "revision_hash": "GENESIS-X",
            "approved_by": "Bryce", "approved_at": "2026-01-01T00:00:00+00:00",
        }
        warnings = replay_persisted_approvals(ledger, [approval_row])
        assert len(warnings) == 1
        assert "failed to replay" in warnings[0].reason


class TestApprovalReplayIsIdempotent:
    def test_replaying_the_same_approval_twice_produces_the_same_state(self):
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0), length_m=6.0)
        live_ledger = _ledger_with_wall(wall)
        corr_outcome = _correct_length(live_ledger, "MASS-1", 9.0)
        result = approve_corrected_geometry(
            live_ledger, object_id="MASS-1", approved_by="Bryce",
            current_revision_hash=corr_outcome.event.new_revision_hash,
            approved_at="2026-09-08T00:00:00+00:00",
        )
        corr_row = correction_event_to_row(1, corr_outcome.event)
        approval_row = approval_result_to_row(1, "wall", result)

        # Replay once.
        ledger_a = _ledger_with_wall(wall)
        replay_persisted_corrections(ledger_a, [wall], [corr_row])
        warnings_a = replay_persisted_approvals(ledger_a, [approval_row])
        obj_a = ledger_a.get_object("MASS-1")

        # Replay the exact same persisted rows again, from another fresh ledger —
        # simulating a second server restart against the same DB state.
        ledger_b = _ledger_with_wall(wall)
        replay_persisted_corrections(ledger_b, [wall], [corr_row])
        warnings_b = replay_persisted_approvals(ledger_b, [approval_row])
        obj_b = ledger_b.get_object("MASS-1")

        assert warnings_a == warnings_b == []
        assert obj_a.revision_hash == obj_b.revision_hash
        assert obj_a.authority_status == obj_b.authority_status == AuthorityStatus.FIRM.value
        assert obj_a.approved_by == obj_b.approved_by == "Bryce"
        assert obj_a.approved_at == obj_b.approved_at == "2026-09-08T00:00:00+00:00"

    def test_replaying_the_same_approval_row_twice_in_one_call_is_a_no_op(self):
        # A duplicate row for the same object in a single replay call (e.g. a
        # read returning the same persisted row twice) must not change the
        # outcome — "latest wins" collapses duplicates to the same result.
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0), length_m=6.0)
        ledger = _ledger_with_wall(wall)
        genesis_hash = ledger.get_object("MASS-1").revision_hash
        row = {
            "object_id": "MASS-1", "revision_hash": genesis_hash,
            "approved_by": "Bryce", "approved_at": "2026-01-01T00:00:00+00:00",
        }
        warnings = replay_persisted_approvals(ledger, [row, row])
        assert warnings == []
        obj = ledger.get_object("MASS-1")
        assert obj.approved_by == "Bryce"
        assert obj.authority_status == AuthorityStatus.FIRM.value


class TestOriginalSourceGeometryRemainsTraceable:
    def test_approval_never_touches_source_trace_fields(self):
        wall = _wall(source_page_no=3, source_sheet_label="WD-11")
        ledger = _ledger_with_wall(wall)
        obj_before = ledger.get_object("MASS-1")
        assert obj_before.source_page == 3
        assert obj_before.source_sheet == "WD-11"
        assert obj_before.original_geometry_ref == "MASS-1"

        outcome = _correct_length(ledger, "MASS-1", 9.0)
        approve_corrected_geometry(
            ledger, object_id="MASS-1", approved_by="Bryce",
            current_revision_hash=outcome.event.new_revision_hash,
        )
        obj_after = ledger.get_object("MASS-1")

        # Correction and approval change measurements/authority — never the
        # object's own source trace, which is the one thing that must stay
        # traceable back to the originating drawing regardless of how many
        # times the geometry itself is corrected or approved.
        assert obj_after.source_page == 3
        assert obj_after.source_sheet == "WD-11"
        assert obj_after.original_geometry_ref == "MASS-1"
        assert obj_after.geometry_ref == "MASS-1"
