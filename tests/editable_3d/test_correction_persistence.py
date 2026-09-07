"""tests/editable_3d/test_correction_persistence.py — PR D.11F test suite.

pb_editable_3d_correction_persistence is the pure serialize/replay layer that
lets a correction survive a reload — these tests prove round-trip
serialization is lossless, that replay reproduces the exact same corrected
geometry through the real Editable3DCorrectionLedger.apply_correction()
pipeline, that the replay-determinism check (ledger.replay()) genuinely
holds, and that a stale-genesis or orphaned-object scenario is surfaced as a
warning rather than silently dropped or crashing the panel.
"""
from __future__ import annotations

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import (
    CorrectionSource,
    Editable3DCorrectionEvent,
    Editable3DCorrectionLedger,
)
from pb_editable_3d_model import WallHeightAuthority, WallModel
from pb_editable_3d_model_bridge import wall_model_to_editable_geometry_object
from pb_editable_3d_correction_persistence import (
    ReplayWarning,
    _resync_length_geometry,
    correction_event_to_row,
    object_state_row,
    replay_persisted_corrections,
    row_to_correction_event,
    verify_object_state_consistency,
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


def _event(**overrides) -> Editable3DCorrectionEvent:
    kwargs = dict(
        correction_id="CORR-1", object_id="MASS-1", object_type="wall",
        field="length", old_value=6.0, new_value=7.5,
        reason="Site remeasure", actor="Estimator",
        created_at="2026-01-01T00:00:00+00:00", source=CorrectionSource.EDITOR_3D.value,
        previous_revision_hash="GENESIS-1", new_revision_hash="ABC123",
    )
    kwargs.update(overrides)
    return Editable3DCorrectionEvent(**kwargs)


class TestSerializationRoundTrip:
    def test_event_survives_a_full_round_trip(self):
        event = _event()
        row = correction_event_to_row(workspace_id=42, event=event)
        restored = row_to_correction_event(row)
        assert restored == event

    def test_row_carries_the_workspace_id(self):
        row = correction_event_to_row(workspace_id=42, event=_event())
        assert row["workspace_id"] == 42

    def test_none_old_value_round_trips_as_none(self):
        event = _event(old_value=None)
        row = correction_event_to_row(workspace_id=1, event=event)
        restored = row_to_correction_event(row)
        assert restored.old_value is None

    def test_object_state_row_captures_real_object_fields(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        obj = ledger.get_object("MASS-1")
        row = object_state_row(workspace_id=7, obj=obj)
        assert row["workspace_id"] == 7
        assert row["object_id"] == "MASS-1"
        assert row["revision_hash"] == obj.revision_hash
        assert row["authority_status"] == obj.authority_status
        assert row["correction_ids_json"] == "[]"


class TestResyncLengthGeometry:
    def test_end_point_moves_along_the_original_direction_to_the_new_length(self):
        original = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0))
        corrected = _wall(length_m=8.0)
        _resync_length_geometry(original, corrected)
        assert corrected.start_pt == (0.0, 0.0)
        assert corrected.end_pt == (8.0, 0.0)

    def test_diagonal_wall_keeps_its_real_direction(self):
        original = _wall(start_pt=(0.0, 0.0), end_pt=(3.0, 4.0))  # real 3-4-5 direction
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


class TestReplayReproducesCorrectedGeometry:
    def test_no_persisted_events_leaves_walls_unchanged(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        walls, warnings = replay_persisted_corrections(ledger, [wall], [])
        assert walls == [wall]
        assert warnings == []

    def test_single_length_correction_replays_correctly(self):
        wall = _wall(length_m=6.0, end_pt=(6.0, 0.0))
        ledger = _ledger_with_wall(wall)
        genesis_hash = ledger.get_object("MASS-1").revision_hash
        row = correction_event_to_row(1, _event(
            field="length", new_value=7.5, previous_revision_hash=genesis_hash,
        ))
        walls, warnings = replay_persisted_corrections(ledger, [wall], [row])
        assert warnings == []
        corrected = next(w for w in walls if w.wall_id == "MASS-1")
        assert corrected.length_m == 7.5
        assert corrected.end_pt == (7.5, 0.0)  # geometry resync applies on replay too

    def test_multiple_sequential_events_all_apply_in_order(self):
        wall = _wall(length_m=6.0, height_m=2.7)
        ledger = _ledger_with_wall(wall)
        genesis_hash = ledger.get_object("MASS-1").revision_hash
        row1 = correction_event_to_row(1, _event(
            correction_id="CORR-1", field="length", old_value=6.0, new_value=8.0,
            previous_revision_hash=genesis_hash, new_revision_hash="HASH-AFTER-1",
        ))
        row2 = correction_event_to_row(1, _event(
            correction_id="CORR-2", field="height", old_value=2.7, new_value=3.0,
            previous_revision_hash="HASH-AFTER-1", new_revision_hash="HASH-AFTER-2",
        ))
        walls, warnings = replay_persisted_corrections(ledger, [wall], [row1, row2])
        assert warnings == []
        corrected = next(w for w in walls if w.wall_id == "MASS-1")
        assert corrected.length_m == 8.0
        assert corrected.height_m == 3.0
        obj = ledger.get_object("MASS-1")
        assert obj.correction_ids == ["CORR-1", "CORR-2"]

    def test_replayed_revision_hash_matches_ledger_replay_independently(self):
        # This is the literal acceptance criterion: replay must deterministically
        # reproduce the current corrected geometry's revision hash.
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        genesis_hash = ledger.get_object("MASS-1").revision_hash
        row = correction_event_to_row(1, _event(previous_revision_hash=genesis_hash))
        replay_persisted_corrections(ledger, [wall], [row])
        obj = ledger.get_object("MASS-1")
        independently_replayed = ledger.replay("MASS-1", genesis_hash=genesis_hash)
        assert independently_replayed == obj.revision_hash

    def test_height_correction_never_unblocks_an_unknown_height_wall(self):
        wall = _wall(height_m=0.0, height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value)
        ledger = _ledger_with_wall(wall)
        genesis_hash = ledger.get_object("MASS-1").revision_hash
        row = correction_event_to_row(1, _event(
            field="height", old_value=0.0, new_value=3.0, previous_revision_hash=genesis_hash,
        ))
        walls, _warnings = replay_persisted_corrections(ledger, [wall], [row])
        corrected = next(w for w in walls if w.wall_id == "MASS-1")
        assert corrected.authority_status == AuthorityStatus.BLOCKED.value
        assert corrected.gross_area_m2 == 0.0


class TestIntegrityWarnings:
    def test_stale_genesis_hash_produces_a_warning_but_still_replays(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        row = correction_event_to_row(1, _event(previous_revision_hash="A-HASH-THAT-NO-LONGER-MATCHES"))
        walls, warnings = replay_persisted_corrections(ledger, [wall], [row])
        assert len(warnings) == 1
        assert "changed since these corrections" in warnings[0].reason
        # Still replayed — a correction is never silently dropped.
        corrected = next(w for w in walls if w.wall_id == "MASS-1")
        assert corrected.length_m == 7.5

    def test_orphaned_object_id_is_warned_and_skipped_not_crashed(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        row = correction_event_to_row(1, _event(object_id="MASS-DOES-NOT-EXIST"))
        walls, warnings = replay_persisted_corrections(ledger, [wall], [row])
        assert walls == [wall]
        assert len(warnings) == 1
        assert "no longer exists" in warnings[0].reason

    def test_invalid_persisted_value_fails_closed_with_a_warning(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        genesis_hash = ledger.get_object("MASS-1").revision_hash
        row = correction_event_to_row(1, _event(
            new_value=-5.0, previous_revision_hash=genesis_hash,  # rejected by create_correction_event
        ))
        walls, warnings = replay_persisted_corrections(ledger, [wall], [row])
        assert len(warnings) == 1
        assert "failed to replay" in warnings[0].reason
        corrected = next(w for w in walls if w.wall_id == "MASS-1")
        assert corrected.length_m == wall.length_m  # untouched


class TestObjectStateConsistencyCheck:
    def test_matching_snapshot_produces_no_warning(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        genesis_hash = ledger.get_object("MASS-1").revision_hash
        row = correction_event_to_row(1, _event(previous_revision_hash=genesis_hash))
        replay_persisted_corrections(ledger, [wall], [row])
        obj = ledger.get_object("MASS-1")
        state_row = object_state_row(1, obj)
        warnings = verify_object_state_consistency(ledger, [state_row])
        assert warnings == []

    def test_drifted_snapshot_is_flagged(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        genesis_hash = ledger.get_object("MASS-1").revision_hash
        row = correction_event_to_row(1, _event(previous_revision_hash=genesis_hash))
        replay_persisted_corrections(ledger, [wall], [row])
        stale_state_row = {"object_id": "MASS-1", "revision_hash": "SOME-OLD-HASH-THAT-DOES-NOT-MATCH"}
        warnings = verify_object_state_consistency(ledger, [stale_state_row])
        assert len(warnings) == 1
        assert "drifted out of sync" in warnings[0].reason

    def test_snapshot_for_an_object_not_in_the_ledger_is_ignored(self):
        wall = _wall()
        ledger = _ledger_with_wall(wall)
        state_row = {"object_id": "MASS-DOES-NOT-EXIST", "revision_hash": "whatever"}
        warnings = verify_object_state_consistency(ledger, [state_row])
        assert warnings == []
