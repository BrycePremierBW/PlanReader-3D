"""tests/editable_3d/test_inspector_panel_persisted_approvals.py — PR D.11G test suite.

pb_editable_3d_inspector_panel._build_dependent_quantity_rows() promotes an
object's current (post-correction) dependent quantity row to publishable
once the object itself carries a live approval (obj.approved_by set) — via
approve_takeoff_output_row() (D.1, unchanged), reusing the exact promotion
path the D.11A demo scenario already proved for WALL-DEMO-2. The old
baseline row is never touched by approval and stays exactly as stale/
non-publishable as D.11F already left it. A later correction clears the
object's approved_by (apply_correction()'s own unchanged invariant), so the
next current row is built un-promoted — blocked again, with no separate
invalidation logic needed here.
"""
from __future__ import annotations

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import CorrectionSource, Editable3DCorrectionLedger, approve_corrected_geometry
from pb_editable_3d_correction_persistence import correction_event_to_row
from pb_editable_3d_model import WallHeightAuthority, WallModel
from pb_editable_3d_model_bridge import wall_model_to_editable_geometry_object
from pb_editable_3d_inspector_panel import _build_dependent_quantity_rows


def _wall(**overrides) -> WallModel:
    kwargs = dict(
        wall_id="MASS-1", level_id="Ground", start_pt=(0.0, 0.0), end_pt=(6.0, 0.0),
        length_m=6.0, height_m=2.7, height_authority=WallHeightAuthority.USER_ENTERED.value,
        wall_type="standard", source_page_no=0, source_sheet_label="WD-04",
        scale_ratio="unknown", authority_status=AuthorityStatus.REVIEW_REQUIRED.value,
        gross_area_m2=16.2, net_area_m2=16.2,
    )
    kwargs.update(overrides)
    return WallModel(**kwargs)


def _correct_length(ledger, object_id, new_value, correction_id="CORR-1"):
    return ledger.apply_correction(
        correction_id=correction_id, object_id=object_id, field="length",
        new_value=new_value, reason="Site remeasure", actor="Estimator",
        source=CorrectionSource.EDITOR_3D.value,
    )


def _ledger_with_wall(wall: WallModel) -> Editable3DCorrectionLedger:
    ledger = Editable3DCorrectionLedger()
    ledger.register_object(wall_model_to_editable_geometry_object(wall))
    return ledger


class TestApprovedObjectPromotesCurrentQuantity:
    def test_current_quantity_becomes_publishable_once_approved(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        outcome = _correct_length(ledger, "MASS-1", 9.0)
        approve_corrected_geometry(
            ledger, object_id="MASS-1", approved_by="Lead Estimator Bryce",
            current_revision_hash=outcome.event.new_revision_hash,
        )
        event_rows = [correction_event_to_row(1, outcome.event)]
        rows = _build_dependent_quantity_rows(ledger, {"MASS-1": wall}, event_rows)

        obj_after = ledger.get_object("MASS-1")
        baseline_ids = {"MASS-1-wall_length-BASELINE", "MASS-1-wall_gross_area-BASELINE", "MASS-1-wall_net_area-BASELINE"}
        current_ids = [qid for qid in obj_after.dependent_quantity_ids if qid not in baseline_ids]
        assert current_ids
        for qid in current_ids:
            row = rows[qid]
            assert row.is_publishable is True
            assert row.approved_by == "Lead Estimator Bryce"
            assert row.authority_status == AuthorityStatus.USER_APPROVED.value

    def test_old_baseline_quantity_stays_non_publishable_after_approval(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        outcome = _correct_length(ledger, "MASS-1", 9.0)
        approve_corrected_geometry(
            ledger, object_id="MASS-1", approved_by="Bryce",
            current_revision_hash=outcome.event.new_revision_hash,
        )
        event_rows = [correction_event_to_row(1, outcome.event)]
        rows = _build_dependent_quantity_rows(ledger, {"MASS-1": wall}, event_rows)

        old_row = rows["MASS-1-wall_length-BASELINE"]
        assert old_row.value == 6.0
        assert old_row.is_publishable is False
        assert "stale_after_geometry_correction" in old_row.blocking_reasons

    def test_unapproved_current_quantity_stays_non_publishable(self):
        # No approval call at all — the exact D.11F behavior must be
        # unaffected for an object that has only been corrected.
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        outcome = _correct_length(ledger, "MASS-1", 9.0)
        event_rows = [correction_event_to_row(1, outcome.event)]
        rows = _build_dependent_quantity_rows(ledger, {"MASS-1": wall}, event_rows)

        obj_after = ledger.get_object("MASS-1")
        baseline_ids = {"MASS-1-wall_length-BASELINE", "MASS-1-wall_gross_area-BASELINE", "MASS-1-wall_net_area-BASELINE"}
        current_ids = [qid for qid in obj_after.dependent_quantity_ids if qid not in baseline_ids]
        for qid in current_ids:
            assert rows[qid].is_publishable is False

    def test_subsequent_correction_invalidates_approval_and_new_quantity_is_blocked_again(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        outcome1 = _correct_length(ledger, "MASS-1", 9.0, correction_id="CORR-1")
        approve_corrected_geometry(
            ledger, object_id="MASS-1", approved_by="Bryce",
            current_revision_hash=outcome1.event.new_revision_hash,
        )
        # A second correction supersedes the approval — no new approval call.
        outcome2 = _correct_length(ledger, "MASS-1", 12.0, correction_id="CORR-2")
        assert ledger.get_object("MASS-1").approved_by is None

        event_rows = [
            correction_event_to_row(1, outcome1.event),
            correction_event_to_row(1, outcome2.event),
        ]
        rows = _build_dependent_quantity_rows(ledger, {"MASS-1": wall}, event_rows)

        obj_after = ledger.get_object("MASS-1")
        baseline_ids = {"MASS-1-wall_length-BASELINE", "MASS-1-wall_gross_area-BASELINE", "MASS-1-wall_net_area-BASELINE"}
        current_ids = [qid for qid in obj_after.dependent_quantity_ids if qid not in baseline_ids]
        assert current_ids
        for qid in current_ids:
            row = rows[qid]
            assert row.is_publishable is False
            assert row.authority_status != AuthorityStatus.USER_APPROVED.value
