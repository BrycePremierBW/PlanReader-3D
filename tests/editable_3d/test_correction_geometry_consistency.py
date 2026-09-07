"""tests/editable_3d/test_correction_geometry_consistency.py — PR D.11F.1 test suite.

Editable3DCorrectionLedger.apply_correction() previously updated a wall's
`length` measurement without ever touching its `start_pt`/`end_pt` — so the
ledger's own canonical object could report a corrected length right next to
a stale, pre-correction endpoint. A downstream, best-effort copy built only
for the 3D viewer papered over this for display purposes, but the
authoritative object itself — the one D.11F persists and later replays —
stayed inconsistent. These tests prove that gap is closed: a length
correction now recomputes end_pt, along the wall's real preserved direction,
as part of applying the correction itself — live or replayed, identically —
and a correction whose direction genuinely cannot be determined is rejected
outright rather than applied half-consistently.
"""
from __future__ import annotations

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import CorrectionSource, Editable3DCorrectionLedger
from pb_editable_3d_correction_persistence import correction_event_to_row, replay_persisted_corrections
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


class TestLengthCorrectionUpdatesEndPoint:
    def test_length_change_updates_end_pt(self):
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0), length_m=6.0)
        ledger = _ledger_with_wall(wall)
        outcome = _correct_length(ledger, "MASS-1", 9.0)
        assert outcome.ok
        obj = ledger.get_object("MASS-1")
        assert obj.coordinates_or_measurements["length"] == 9.0
        assert obj.coordinates_or_measurements["end_pt"] == [9.0, 0.0]

    def test_direction_remains_unchanged(self):
        # A real 3-4-5 direction, not axis-aligned — any accidental
        # axis-snapping in the resync math would show up here.
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(3.0, 4.0), length_m=5.0)
        ledger = _ledger_with_wall(wall)
        outcome = _correct_length(ledger, "MASS-1", 10.0)
        assert outcome.ok
        obj = ledger.get_object("MASS-1")
        assert obj.coordinates_or_measurements["start_pt"] == [0.0, 0.0]
        end_pt = obj.coordinates_or_measurements["end_pt"]
        assert abs(end_pt[0] - 6.0) < 1e-9  # 10 * (3/5)
        assert abs(end_pt[1] - 8.0) < 1e-9  # 10 * (4/5)


class TestReplayReproducesCanonicalGeometry:
    def test_restart_replay_gives_identical_end_pt(self):
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0), length_m=6.0)

        live_ledger = _ledger_with_wall(wall)
        outcome = _correct_length(live_ledger, "MASS-1", 9.0)
        live_obj = live_ledger.get_object("MASS-1")

        # Simulate a server restart: a fresh ledger, a fresh hydration of the
        # same genesis wall, replaying the one persisted event from scratch —
        # exactly the D.11F reload path, not the live-correction path.
        replay_ledger = _ledger_with_wall(wall)
        row = correction_event_to_row(1, outcome.event)
        walls, warnings = replay_persisted_corrections(replay_ledger, [wall], [row])

        assert warnings == []
        replayed_obj = replay_ledger.get_object("MASS-1")
        assert replayed_obj.coordinates_or_measurements["end_pt"] == live_obj.coordinates_or_measurements["end_pt"]
        assert replayed_obj.revision_hash == live_obj.revision_hash
        corrected_wall = next(w for w in walls if w.wall_id == "MASS-1")
        assert corrected_wall.end_pt == (9.0, 0.0)

    def test_revision_hash_is_deterministic(self):
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0), length_m=6.0)
        ledger_a = _ledger_with_wall(wall)
        ledger_b = _ledger_with_wall(wall)
        outcome_a = _correct_length(ledger_a, "MASS-1", 9.0)
        outcome_b = _correct_length(ledger_b, "MASS-1", 9.0)
        assert outcome_a.event.new_revision_hash == outcome_b.event.new_revision_hash
        assert ledger_a.get_object("MASS-1").revision_hash == ledger_b.get_object("MASS-1").revision_hash


class TestStaleRevisionUnaffected:
    def test_stale_old_revision_remains_stale(self):
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0), length_m=6.0)
        ledger = _ledger_with_wall(wall)
        genesis_obj = ledger.get_object("MASS-1")
        genesis_hash = genesis_obj.revision_hash
        genesis_end_pt = list(genesis_obj.coordinates_or_measurements["end_pt"])

        _correct_length(ledger, "MASS-1", 9.0)

        # The object snapshot captured before the correction must never
        # mutate in place — apply_correction() replaces the ledger's live
        # entry with a new dataclass instance, it never writes through an
        # already-returned reference. The old revision stays exactly as it
        # was, distinguishable from the new one.
        assert genesis_obj.revision_hash == genesis_hash
        assert genesis_obj.coordinates_or_measurements["end_pt"] == genesis_end_pt
        assert ledger.get_object("MASS-1").revision_hash != genesis_hash


class TestMalformedOrZeroDirectionFailsClosed:
    def test_zero_length_existing_segment_fails_closed(self):
        # A genuinely degenerate segment: start_pt and end_pt coincide even
        # though the object still carries a positive scalar length (so the
        # genesis revision hash is populated and this test isolates the
        # geometry-resync failure rather than an unrelated missing-hash one).
        wall = _wall(start_pt=(2.0, 2.0), end_pt=(2.0, 2.0), length_m=6.0)
        ledger = _ledger_with_wall(wall)
        outcome = _correct_length(ledger, "MASS-1", 10.0)
        assert not outcome.ok
        assert any("direction" in r for r in outcome.blocking_reasons)
        # Rejected outright: the scalar length must not have been applied
        # either, so the object never ends up partially corrected.
        obj = ledger.get_object("MASS-1")
        assert obj.coordinates_or_measurements["length"] == 6.0
        assert obj.coordinates_or_measurements["end_pt"] == [2.0, 2.0]

    def test_malformed_start_pt_fails_closed(self):
        ledger = Editable3DCorrectionLedger()
        obj = wall_model_to_editable_geometry_object(_wall())
        obj.coordinates_or_measurements["start_pt"] = "not-a-point"
        ledger.register_object(obj)
        outcome = _correct_length(ledger, "MASS-1", 10.0)
        assert not outcome.ok
        assert any("not valid" in r for r in outcome.blocking_reasons)
        assert ledger.get_object("MASS-1").coordinates_or_measurements["length"] == 6.0

    def test_object_with_no_endpoint_geometry_is_unaffected(self):
        # An object with no start_pt/end_pt at all (e.g. a non-linear shape)
        # has nothing to resync — a length correction proceeds normally.
        ledger = Editable3DCorrectionLedger()
        obj = wall_model_to_editable_geometry_object(_wall())
        obj.coordinates_or_measurements.pop("start_pt")
        obj.coordinates_or_measurements.pop("end_pt")
        ledger.register_object(obj)
        outcome = _correct_length(ledger, "MASS-1", 12.0)
        assert outcome.ok
        assert ledger.get_object("MASS-1").coordinates_or_measurements["length"] == 12.0


class TestHeightCorrectionLeavesEndpointsAlone:
    def test_correcting_height_does_not_alter_xy_endpoints(self):
        wall = _wall(start_pt=(0.0, 0.0), end_pt=(6.0, 0.0), length_m=6.0, height_m=2.7)
        ledger = _ledger_with_wall(wall)
        outcome = ledger.apply_correction(
            correction_id="CORR-H", object_id="MASS-1", field="height",
            new_value=3.2, reason="Site remeasure", actor="Estimator",
            source=CorrectionSource.EDITOR_3D.value,
        )
        assert outcome.ok
        obj = ledger.get_object("MASS-1")
        assert obj.coordinates_or_measurements["height"] == 3.2
        assert obj.coordinates_or_measurements["start_pt"] == [0.0, 0.0]
        assert obj.coordinates_or_measurements["end_pt"] == [6.0, 0.0]
