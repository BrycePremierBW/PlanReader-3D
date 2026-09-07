"""tests/editable_3d/test_workspace_hydration.py — PR D.11B test suite.

pb_editable_3d_workspace_hydration.hydrate_masses_to_wall_models() converts real
`model_masses`/`model_openings` SQLite rows (plain dicts here, matching what
sqlite3.Row -> dict produces) into WallModel instances. These tests prove the
adapter is fail-closed: it never fabricates a dimension, never trusts a numeric
height alone as evidence a height is known, never grants FIRM authority on its
own, and skips (rather than guesses) geometry it can't safely convert.
"""
from __future__ import annotations

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_model import WallHeightAuthority
from pb_editable_3d_workspace_hydration import hydrate_masses_to_wall_models


def _mass(**overrides):
    row = {
        "id": 1, "workspace_id": 1, "label": "North wall", "level_name": "Ground",
        "x": 0.0, "y": 0.0, "z": 0.0, "width": 6.0, "depth": 0.2, "height": 2.7,
        "finish": "", "source_reference": "WD-04", "confidence": "Measured", "notes": "",
    }
    row.update(overrides)
    return row


def _opening(**overrides):
    row = {
        "id": 1, "workspace_id": 1, "mass_id": 1, "label": "Door", "opening_type": "door",
        "face": "Front", "offset_x": 1.0, "offset_z": 0.0, "width": 0.9, "height": 2.1,
        "count": 1, "notes": "", "source_reference": "WD-04",
    }
    row.update(overrides)
    return row


class TestHeightAuthorityMapping:
    def test_measured_confidence_maps_to_user_entered(self):
        result = hydrate_masses_to_wall_models([_mass(confidence="Measured")], [])
        assert len(result.walls) == 1
        wall = result.walls[0]
        assert wall.height_authority == WallHeightAuthority.USER_ENTERED.value
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value

    def test_verified_confidence_maps_to_user_approved(self):
        result = hydrate_masses_to_wall_models([_mass(confidence="Verified")], [])
        assert result.walls[0].height_authority == WallHeightAuthority.USER_APPROVED.value

    def test_derived_confidence_maps_to_model_estimated(self):
        result = hydrate_masses_to_wall_models([_mass(confidence="Derived")], [])
        assert result.walls[0].height_authority == WallHeightAuthority.MODEL_ESTIMATED.value

    def test_assumed_confidence_is_treated_as_unknown_height_and_blocked(self):
        # "Assumed" is the app's own label for a guessed dimension — it must never
        # be trusted as a real height, even though a numeric value is present.
        result = hydrate_masses_to_wall_models([_mass(confidence="Assumed", height=2.7)], [])
        wall = result.walls[0]
        assert wall.height_authority == WallHeightAuthority.UNKNOWN_HEIGHT.value
        assert wall.authority_status == AuthorityStatus.BLOCKED.value
        assert wall.gross_area_m2 == 0.0
        assert wall.net_area_m2 == 0.0

    def test_to_review_confidence_is_also_unknown_height(self):
        result = hydrate_masses_to_wall_models([_mass(confidence="To review")], [])
        assert result.walls[0].height_authority == WallHeightAuthority.UNKNOWN_HEIGHT.value

    def test_missing_confidence_defaults_to_unknown_height(self):
        result = hydrate_masses_to_wall_models([_mass(confidence="")], [])
        assert result.walls[0].height_authority == WallHeightAuthority.UNKNOWN_HEIGHT.value

    def test_unrecognized_confidence_label_defaults_to_unknown_height(self):
        result = hydrate_masses_to_wall_models([_mass(confidence="Guesstimate")], [])
        assert result.walls[0].height_authority == WallHeightAuthority.UNKNOWN_HEIGHT.value


class TestMalformedOrMissingHeightAlwaysFailsClosed:
    def test_missing_height_forces_unknown_height_even_with_measured_confidence(self):
        result = hydrate_masses_to_wall_models([_mass(confidence="Measured", height=None)], [])
        wall = result.walls[0]
        assert wall.height_authority == WallHeightAuthority.UNKNOWN_HEIGHT.value
        assert wall.authority_status == AuthorityStatus.BLOCKED.value
        assert wall.height_m == 0.0

    def test_negative_height_forces_unknown_height_even_with_verified_confidence(self):
        result = hydrate_masses_to_wall_models([_mass(confidence="Verified", height=-1.0)], [])
        wall = result.walls[0]
        assert wall.height_authority == WallHeightAuthority.UNKNOWN_HEIGHT.value
        assert wall.authority_status == AuthorityStatus.BLOCKED.value

    def test_non_numeric_height_forces_unknown_height(self):
        result = hydrate_masses_to_wall_models([_mass(confidence="Measured", height="not-a-number")], [])
        assert result.walls[0].height_authority == WallHeightAuthority.UNKNOWN_HEIGHT.value


class TestHydrationNeverGrantsApproval:
    def test_no_confidence_label_ever_produces_firm_authority(self):
        for confidence in ("Measured", "Verified", "Derived", "Assumed", "To review", "", "Guesstimate"):
            result = hydrate_masses_to_wall_models([_mass(confidence=confidence)], [])
            wall = result.walls[0]
            assert wall.authority_status != AuthorityStatus.FIRM.value
            assert wall.approved_by is None
            assert wall.approved_at is None


class TestMalformedGeometryIsSkippedNotFabricated:
    def test_mass_with_zero_width_and_depth_is_skipped(self):
        result = hydrate_masses_to_wall_models([_mass(width=0.0, depth=0.0)], [])
        assert result.walls == []
        assert len(result.skipped) == 1
        assert result.skipped[0].kind == "mass"
        assert result.skipped[0].source_id == 1

    def test_mass_with_missing_width_and_depth_is_skipped(self):
        result = hydrate_masses_to_wall_models([_mass(width=None, depth=None)], [])
        assert result.walls == []
        assert len(result.skipped) == 1

    def test_mass_with_non_numeric_width_and_depth_is_skipped(self):
        result = hydrate_masses_to_wall_models([_mass(width="wide", depth="deep")], [])
        assert result.walls == []

    def test_mass_with_only_width_valid_still_hydrates_using_width_as_length(self):
        result = hydrate_masses_to_wall_models([_mass(width=5.0, depth=None)], [])
        assert len(result.walls) == 1
        assert result.walls[0].length_m == 5.0

    def test_opening_with_negative_width_is_skipped_but_wall_still_hydrates(self):
        result = hydrate_masses_to_wall_models(
            [_mass()], [_opening(width=-0.9)],
        )
        assert len(result.walls) == 1
        assert result.walls[0].openings == []
        opening_skips = [s for s in result.skipped if s.kind == "opening"]
        assert len(opening_skips) == 1

    def test_opening_with_non_numeric_height_is_skipped(self):
        result = hydrate_masses_to_wall_models([_mass()], [_opening(height="tall")])
        assert result.walls[0].openings == []


class TestLengthAndGeometryDerivation:
    def test_length_is_the_longer_of_width_and_depth(self):
        result = hydrate_masses_to_wall_models([_mass(width=6.0, depth=0.2)], [])
        assert result.walls[0].length_m == 6.0

        result2 = hydrate_masses_to_wall_models([_mass(width=0.2, depth=8.0)], [])
        assert result2.walls[0].length_m == 8.0

    def test_start_and_end_points_run_along_the_longer_edge(self):
        result = hydrate_masses_to_wall_models([_mass(x=1.0, y=2.0, width=6.0, depth=0.2)], [])
        wall = result.walls[0]
        assert wall.start_pt == (1.0, 2.0)
        assert wall.end_pt == (7.0, 2.0)

        result2 = hydrate_masses_to_wall_models([_mass(x=1.0, y=2.0, width=0.2, depth=8.0)], [])
        wall2 = result2.walls[0]
        assert wall2.start_pt == (1.0, 2.0)
        assert wall2.end_pt == (1.0, 10.0)

    def test_wall_id_is_deterministic_from_mass_id(self):
        result = hydrate_masses_to_wall_models([_mass(id=42)], [])
        assert result.walls[0].wall_id == "MASS-42"

    def test_source_sheet_label_preserved_from_source_reference(self):
        result = hydrate_masses_to_wall_models([_mass(source_reference="WD-07")], [])
        assert result.walls[0].source_sheet_label == "WD-07"

    def test_empty_source_reference_yields_empty_source_sheet_label(self):
        result = hydrate_masses_to_wall_models([_mass(source_reference="")], [])
        assert result.walls[0].source_sheet_label == ""

    def test_scale_ratio_is_always_unknown_not_a_guessed_default(self):
        result = hydrate_masses_to_wall_models([_mass()], [])
        assert result.walls[0].scale_ratio == "unknown"

    def test_level_name_becomes_level_id(self):
        result = hydrate_masses_to_wall_models([_mass(level_name="Level 1")], [])
        assert result.walls[0].level_id == "Level 1"


class TestOpeningPositionPreservedNotFabricated:
    def test_offset_x_and_z_are_preserved_from_real_recorded_values(self):
        result = hydrate_masses_to_wall_models([_mass()], [_opening(offset_x=2.5, offset_z=0.0)])
        opening = result.walls[0].openings[0]
        assert opening.offset_x_m == 2.5
        assert opening.offset_z_m == 0.0

    def test_missing_offsets_are_none_not_a_guessed_zero(self):
        result = hydrate_masses_to_wall_models([_mass()], [_opening(offset_x=None, offset_z=None)])
        opening = result.walls[0].openings[0]
        assert opening.offset_x_m is None
        assert opening.offset_z_m is None

    def test_non_numeric_offsets_are_none(self):
        result = hydrate_masses_to_wall_models([_mass()], [_opening(offset_x="far", offset_z="high")])
        opening = result.walls[0].openings[0]
        assert opening.offset_x_m is None
        assert opening.offset_z_m is None


class TestOpeningsHydration:
    def test_valid_opening_area_is_width_times_height_times_count(self):
        result = hydrate_masses_to_wall_models([_mass()], [_opening(width=1.0, height=2.0, count=3)])
        openings = result.walls[0].openings
        assert len(openings) == 1
        assert openings[0].area_m2 == 6.0
        assert openings[0].deducts is True

    def test_missing_count_defaults_to_a_single_repeat(self):
        result = hydrate_masses_to_wall_models([_mass()], [_opening(width=1.0, height=2.0, count=None)])
        assert result.walls[0].openings[0].area_m2 == 2.0

    def test_openings_are_grouped_by_mass_id_and_do_not_leak_across_walls(self):
        result = hydrate_masses_to_wall_models(
            [_mass(id=1), _mass(id=2)],
            [_opening(id=1, mass_id=1), _opening(id=2, mass_id=2)],
        )
        wall1 = next(w for w in result.walls if w.wall_id == "MASS-1")
        wall2 = next(w for w in result.walls if w.wall_id == "MASS-2")
        assert len(wall1.openings) == 1
        assert len(wall2.openings) == 1
        assert wall1.openings[0].opening_id != wall2.openings[0].opening_id


class TestDeterminism:
    def test_hydrating_the_same_rows_twice_produces_identical_walls(self):
        mass_rows = [_mass(id=1), _mass(id=2, confidence="Assumed")]
        opening_rows = [_opening(id=1, mass_id=1)]
        result_a = hydrate_masses_to_wall_models(mass_rows, opening_rows)
        result_b = hydrate_masses_to_wall_models(mass_rows, opening_rows)
        for wa, wb in zip(result_a.walls, result_b.walls):
            assert wa.wall_id == wb.wall_id
            assert wa.length_m == wb.length_m
            assert wa.height_m == wb.height_m
            assert wa.authority_status == wb.authority_status
            assert wa.revision_hash == wb.revision_hash


class TestMultipleMasses:
    def test_multiple_masses_each_hydrate_independently(self):
        result = hydrate_masses_to_wall_models(
            [_mass(id=1, confidence="Measured"), _mass(id=2, confidence="Assumed")], [],
        )
        assert len(result.walls) == 2
        wall1 = next(w for w in result.walls if w.wall_id == "MASS-1")
        wall2 = next(w for w in result.walls if w.wall_id == "MASS-2")
        assert wall1.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert wall2.authority_status == AuthorityStatus.BLOCKED.value
