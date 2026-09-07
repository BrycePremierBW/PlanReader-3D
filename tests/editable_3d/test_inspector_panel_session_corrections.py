"""tests/editable_3d/test_inspector_panel_session_corrections.py — PR D.11E test suite.

pb_editable_3d_inspector_panel's session-only correction machinery
(_apply_session_corrections, _build_baseline_rows, _resync_length_geometry) is
the one mutation path this panel has. These tests prove the acceptance
criteria directly: a correction changes wall geometry, bumps the revision,
records a correction event, stales the old dependent quantity, produces a
current-but-non-publishable new quantity, and never grants approval —
correction stays correction, never becomes approval.
"""
from __future__ import annotations

import streamlit as st

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import Editable3DCorrectionLedger
from pb_editable_3d_model import WallHeightAuthority, WallModel
from pb_editable_3d_model_bridge import wall_model_to_editable_geometry_object
from pb_editable_3d_inspector_panel import (
    _SESSION_CORRECTIONS_KEY,
    _apply_session_corrections,
    _build_baseline_rows,
    _resync_length_geometry,
)


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


def _set_session_correction(wall_id: str, field: str, new_value: float, reason: str = "Site remeasure") -> None:
    st.session_state[_SESSION_CORRECTIONS_KEY] = {
        wall_id: {
            "field": field, "new_value": new_value, "reason": reason,
            "actor": "Test Estimator", "correction_id": f"CORR-SESSION-{wall_id}",
        }
    }


def _clear_session_correction() -> None:
    st.session_state.pop(_SESSION_CORRECTIONS_KEY, None)


class TestBuildBaselineRows:
    def test_baseline_rows_use_the_walls_real_current_values(self):
        wall = _wall(length_m=6.0, height_m=2.7, gross_area_m2=16.2, net_area_m2=16.2)
        rows = _build_baseline_rows(wall, ["wall_length", "wall_gross_area", "wall_net_area"])
        by_id = {r.quantity_id: r for r in rows}
        assert by_id["MASS-1-wall_length-SESSION"].value == 6.0
        assert by_id["MASS-1-wall_gross_area-SESSION"].value == 16.2
        assert by_id["MASS-1-wall_net_area-SESSION"].value == 16.2

    def test_baseline_rows_are_model_derived_and_not_approved(self):
        wall = _wall()
        rows = _build_baseline_rows(wall, ["wall_length"])
        assert rows[0].approved_by is None
        assert rows[0].is_publishable is False

    def test_unknown_target_is_skipped_not_guessed(self):
        wall = _wall()
        rows = _build_baseline_rows(wall, ["manual_review_required"])
        assert rows == []


class TestResyncLengthGeometry:
    def test_end_point_moves_along_the_original_direction_to_the_new_length(self):
        original = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0))
        corrected = _wall(length_m=8.0)
        _resync_length_geometry(original, corrected)
        assert corrected.start_pt == (0.0, 0.0)
        assert corrected.end_pt == (8.0, 0.0)

    def test_diagonal_wall_keeps_its_real_direction(self):
        original = _wall(start_pt=(0.0, 0.0), end_pt=(3.0, 4.0))  # length 5, real 3-4-5 direction
        corrected = _wall(length_m=10.0)
        _resync_length_geometry(original, corrected)
        assert corrected.start_pt == (0.0, 0.0)
        assert abs(corrected.end_pt[0] - 6.0) < 1e-9  # 10 * (3/5)
        assert abs(corrected.end_pt[1] - 8.0) < 1e-9  # 10 * (4/5)

    def test_degenerate_original_segment_is_left_untouched(self):
        original = _wall(start_pt=(2.0, 2.0), end_pt=(2.0, 2.0))
        corrected = _wall(length_m=10.0, start_pt=(2.0, 2.0), end_pt=(2.0, 2.0))
        _resync_length_geometry(original, corrected)
        assert corrected.end_pt == (2.0, 2.0)  # no direction to extend along — left alone


class TestApplySessionCorrectionsAcceptanceCriteria:
    def teardown_method(self):
        _clear_session_correction()

    def test_no_stored_corrections_returns_walls_unchanged(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        _clear_session_correction()
        walls, rows = _apply_session_corrections(ledger, [wall])
        assert walls == [wall]
        assert rows == {}

    def test_length_correction_changes_wall_geometry_in_the_returned_walls(self):
        wall = _wall(length_m=6.0, end_pt=(6.0, 0.0))
        ledger = _ledger_with_wall(wall)
        _set_session_correction("MASS-1", "length", 8.0)
        walls, _rows = _apply_session_corrections(ledger, [wall])
        corrected = next(w for w in walls if w.wall_id == "MASS-1")
        assert corrected.length_m == 8.0
        assert corrected.end_pt == (8.0, 0.0)  # 3D scene reflects the new length, not just the number

    def test_correction_bumps_the_revision_hash(self):
        wall = _wall()
        original_hash = wall_model_to_editable_geometry_object(wall).revision_hash
        ledger = _ledger_with_wall(wall)
        _set_session_correction("MASS-1", "length", 7.0)
        _apply_session_corrections(ledger, [wall])
        assert ledger.get_object("MASS-1").revision_hash != original_hash

    def test_correction_is_recorded_as_a_real_ledger_event(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        _set_session_correction("MASS-1", "length", 7.0, reason="Site remeasure confirmed")
        _apply_session_corrections(ledger, [wall])
        events = ledger.events_for_object("MASS-1")
        assert len(events) == 1
        assert events[0].field == "length"
        assert events[0].new_value == 7.0
        assert events[0].reason == "Site remeasure confirmed"

    def test_correction_lands_review_required_never_approved(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        _set_session_correction("MASS-1", "length", 7.0)
        _apply_session_corrections(ledger, [wall])
        obj = ledger.get_object("MASS-1")
        assert obj.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert obj.approved_by is None
        assert obj.approved_at is None

    def test_old_dependent_quantity_becomes_visibly_stale(self):
        wall = _wall(length_m=6.0, gross_area_m2=16.2, net_area_m2=16.2)
        ledger = _ledger_with_wall(wall)
        _set_session_correction("MASS-1", "length", 7.0)
        walls, rows = _apply_session_corrections(ledger, [wall])
        obj = ledger.get_object("MASS-1")
        old_gross_id = "MASS-1-wall_gross_area-SESSION"
        assert old_gross_id in obj.dependent_quantity_ids  # visible in the UI, not just computed
        old_row = rows[old_gross_id]
        assert old_row.is_publishable is False
        assert "stale_after_geometry_correction" in old_row.blocking_reasons

    def test_recalculated_quantity_is_current_but_not_publishable(self):
        wall = _wall(length_m=6.0, gross_area_m2=16.2, net_area_m2=16.2)
        ledger = _ledger_with_wall(wall)
        baseline_ids = {"MASS-1-wall_length-SESSION", "MASS-1-wall_gross_area-SESSION", "MASS-1-wall_net_area-SESSION"}
        _set_session_correction("MASS-1", "length", 7.0)
        walls, rows = _apply_session_corrections(ledger, [wall])
        obj = ledger.get_object("MASS-1")
        new_ids = [qid for qid in obj.dependent_quantity_ids if qid not in baseline_ids]
        assert new_ids, "expected at least one newly-linked current quantity id"
        for qid in new_ids:
            new_row = rows[qid]
            assert "stale_after_geometry_correction" not in new_row.blocking_reasons
            assert new_row.is_publishable is False  # current, but never auto-approved — no approval control exists

    def test_height_correction_on_a_trusted_wall_recalculates_area(self):
        wall = _wall(height_m=2.7, height_authority=WallHeightAuthority.USER_ENTERED.value)
        ledger = _ledger_with_wall(wall)
        _set_session_correction("MASS-1", "height", 3.0)
        walls, _rows = _apply_session_corrections(ledger, [wall])
        corrected = next(w for w in walls if w.wall_id == "MASS-1")
        assert corrected.height_m == 3.0
        assert corrected.gross_area_m2 == 6.0 * 3.0

    def test_height_correction_never_unblocks_an_unknown_height_wall_on_its_own(self):
        # No new authority logic: typing a number doesn't retroactively make
        # the height *source* trusted — only a real authority declaration
        # would, and this panel deliberately doesn't add one.
        wall = _wall(height_m=0.0, height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value)
        ledger = _ledger_with_wall(wall)
        _set_session_correction("MASS-1", "height", 3.0)
        walls, _rows = _apply_session_corrections(ledger, [wall])
        corrected = next(w for w in walls if w.wall_id == "MASS-1")
        assert corrected.authority_status == AuthorityStatus.BLOCKED.value
        assert corrected.gross_area_m2 == 0.0

    def test_correction_for_a_wall_id_no_longer_in_the_live_hydration_is_dropped_silently(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        _set_session_correction("MASS-DOES-NOT-EXIST", "length", 7.0)
        walls, rows = _apply_session_corrections(ledger, [wall])
        assert walls == [wall]
        assert rows == {}

    def test_invalid_correction_value_fails_closed_without_crashing(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        _set_session_correction("MASS-1", "length", -5.0)  # negative: rejected by create_correction_event
        walls, rows = _apply_session_corrections(ledger, [wall])
        # No crash; the wall is simply not corrected.
        corrected = next(w for w in walls if w.wall_id == "MASS-1")
        assert corrected.length_m == wall.length_m
