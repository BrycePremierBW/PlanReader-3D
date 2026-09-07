"""tests/editable_3d/test_inspector_panel_persisted_corrections.py — PR D.11F test suite.

pb_editable_3d_inspector_panel's own correction-adjacent helpers —
_build_baseline_rows() (real, currently-hydrated quantity values, unchanged
from D.11E) and _build_dependent_quantity_rows() (new in D.11F: combines
baseline rows with the real persisted correction history to produce the
stale-old/current-new pair the acceptance criteria require, now driven by
real DB-shaped event rows instead of session state).
"""
from __future__ import annotations

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import Editable3DCorrectionLedger
from pb_editable_3d_model import WallHeightAuthority, WallModel
from pb_editable_3d_model_bridge import wall_model_to_editable_geometry_object
from pb_editable_3d_correction_persistence import correction_event_to_row, replay_persisted_corrections
from pb_editable_3d_inspector_panel import _build_baseline_rows, _build_dependent_quantity_rows


def _wall(**overrides) -> WallModel:
    kwargs = dict(
        wall_id="MASS-1", level_id="Ground", start_pt=(0.0, 0.0), end_pt=(6.0, 0.0),
        length_m=6.0, height_m=2.7, height_authority=WallHeightAuthority.USER_ENTERED.value,
        wall_type="standard", source_page_no=0, source_sheet_label="WD-04",
        scale_ratio="unknown", authority_status=AuthorityStatus.REVIEW_REQUIRED.value,
    )
    kwargs.update(overrides)
    return WallModel(**kwargs)


def _event_row(workspace_id=1, **overrides):
    from pb_editable_3d_correction_model import CorrectionSource, Editable3DCorrectionEvent
    kwargs = dict(
        correction_id="CORR-1", object_id="MASS-1", object_type="wall",
        field="length", old_value=6.0, new_value=7.5,
        reason="Site remeasure", actor="Estimator",
        created_at="2026-01-01T00:00:00+00:00", source=CorrectionSource.EDITOR_3D.value,
        previous_revision_hash=None, new_revision_hash="ABC",
    )
    kwargs.update(overrides)
    return correction_event_to_row(workspace_id, Editable3DCorrectionEvent(**kwargs))


class TestBuildBaselineRows:
    def test_baseline_rows_use_the_walls_real_current_values(self):
        wall = _wall(length_m=6.0, height_m=2.7, gross_area_m2=16.2, net_area_m2=16.2)
        rows = _build_baseline_rows(wall, ["wall_length", "wall_gross_area", "wall_net_area"])
        by_id = {r.quantity_id: r for r in rows}
        assert by_id["MASS-1-wall_length-BASELINE"].value == 6.0
        assert by_id["MASS-1-wall_gross_area-BASELINE"].value == 16.2
        assert by_id["MASS-1-wall_net_area-BASELINE"].value == 16.2

    def test_baseline_rows_are_model_derived_and_not_approved(self):
        rows = _build_baseline_rows(_wall(), ["wall_length"])
        assert rows[0].approved_by is None
        assert rows[0].is_publishable is False

    def test_unknown_target_is_skipped_not_guessed(self):
        rows = _build_baseline_rows(_wall(), ["manual_review_required"])
        assert rows == []


class TestBuildDependentQuantityRows:
    def _ledger_after_replay(self, wall, event_rows):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(wall_model_to_editable_geometry_object(wall))
        genesis_hash = ledger.get_object("MASS-1").revision_hash
        # Backfill previous_revision_hash on the first event so replay doesn't
        # trip the (unrelated) stale-genesis warning path in this test.
        event_rows[0]["previous_revision_hash"] = genesis_hash
        replay_persisted_corrections(ledger, [wall], event_rows)
        return ledger

    def test_old_quantity_is_visible_and_stale_after_replay(self):
        wall = _wall(length_m=6.0, gross_area_m2=16.2, net_area_m2=16.2)
        event_rows = [_event_row()]
        ledger = self._ledger_after_replay(wall, event_rows)
        rows = _build_dependent_quantity_rows(ledger, {"MASS-1": wall}, event_rows)
        old_row = rows["MASS-1-wall_length-BASELINE"]
        assert old_row.value == 6.0
        assert old_row.is_publishable is False
        assert "stale_after_geometry_correction" in old_row.blocking_reasons

    def test_current_quantity_is_visible_and_not_stale(self):
        wall = _wall(length_m=6.0, gross_area_m2=16.2, net_area_m2=16.2)
        event_rows = [_event_row()]
        ledger = self._ledger_after_replay(wall, event_rows)
        rows = _build_dependent_quantity_rows(ledger, {"MASS-1": wall}, event_rows)
        obj = ledger.get_object("MASS-1")
        current_ids = [qid for qid in obj.dependent_quantity_ids if qid not in
                       {"MASS-1-wall_length-BASELINE", "MASS-1-wall_gross_area-BASELINE", "MASS-1-wall_net_area-BASELINE"}]
        assert current_ids
        for qid in current_ids:
            row = rows[qid]
            assert "stale_after_geometry_correction" not in row.blocking_reasons
            assert row.is_publishable is False  # current, but never auto-approved

    def test_gross_area_recalculates_correctly_for_the_final_corrected_length(self):
        wall = _wall(length_m=6.0, height_m=2.7, gross_area_m2=16.2, net_area_m2=16.2)
        event_rows = [_event_row(new_value=7.5)]
        ledger = self._ledger_after_replay(wall, event_rows)
        rows = _build_dependent_quantity_rows(ledger, {"MASS-1": wall}, event_rows)
        # The real recalculated gross area (7.5 x 2.7) appears somewhere among
        # the produced rows — not a fabricated or stale value.
        assert any(abs(r.value - 20.25) < 1e-9 for r in rows.values())

    def test_object_with_no_persisted_corrections_produces_no_rows(self):
        wall = _wall()
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(wall_model_to_editable_geometry_object(wall))
        rows = _build_dependent_quantity_rows(ledger, {"MASS-1": wall}, [])
        assert rows == {}
