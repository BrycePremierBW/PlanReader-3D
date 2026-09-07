"""tests/editable_3d/test_raked_wall_area_engine.py — PR D.7 test suite.

D.5 added a guard preventing a raked/stair wall from silently trusting the flat
rectangular formula. This suite proves the real fix: a raked wall with both
endpoint heights documented gets a genuine trapezoid area calculation and is
governed by height_authority normally — no longer force-downgraded, because the
formula now actually matches the geometry. A raked wall with only a single height
(no endpoint data) still gets the D.5 guard, unchanged. Stair walls are untouched.
"""
from __future__ import annotations

import math

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_model import WallHeightAuthority, WallModel


def _wall(**overrides):
    defaults = dict(
        wall_id="W_RAKE",
        level_id="L_01",
        start_pt=(0.0, 0.0),
        end_pt=(6.0, 0.0),
        length_m=6.0,
        height_m=3.0,  # fallback single height, used only if no endpoint pair
        height_authority=WallHeightAuthority.DOCUMENTED_CEILING_HEIGHT.value,
        wall_type="raked",
        authority_status=AuthorityStatus.FIRM.value,
    )
    defaults.update(overrides)
    return WallModel(**defaults)


class TestTrapezoidFormulaWithBothEndpointHeights:
    def test_raked_wall_with_endpoint_heights_uses_trapezoid_area(self):
        wall = _wall(height_start_m=2.4, height_end_m=3.6)
        # area = length * (h1 + h2) / 2 = 6.0 * (2.4 + 3.6) / 2 = 18.0
        assert wall.gross_area_m2 == pytest.approx(18.0)

    def test_raked_wall_with_equal_endpoints_matches_flat_formula(self):
        wall = _wall(height_start_m=3.0, height_end_m=3.0, height_m=3.0)
        assert wall.gross_area_m2 == pytest.approx(6.0 * 3.0)

    def test_trapezoid_deducts_openings_via_existing_as4041_logic(self):
        from pb_editable_3d_model import OpeningModel

        wall = _wall(
            height_start_m=2.4, height_end_m=3.6,
            openings=[OpeningModel(
                opening_id="D1", wall_id="W_RAKE", opening_type="door",
                width_m=0.9, height_m=2.1, area_m2=1.89, deducts=True,
            )],
        )
        assert wall.gross_area_m2 == pytest.approx(18.0)
        assert wall.net_area_m2 == pytest.approx(18.0 - 1.89)


class TestRealFormulaIsGovernedNormallyByHeightAuthority:
    def test_raked_wall_with_documented_endpoints_can_be_firm(self):
        wall = _wall(
            height_start_m=2.4, height_end_m=3.6,
            height_authority=WallHeightAuthority.DOCUMENTED_CEILING_HEIGHT.value,
            authority_status=AuthorityStatus.FIRM.value,
        )
        # A real trapezoid calculation from documented heights is no longer
        # suspicious just because wall_type=="raked" — the D.5 guard no longer
        # applies here.
        assert wall.authority_status == AuthorityStatus.FIRM.value

    def test_raked_wall_with_model_estimated_endpoints_is_still_provisional(self):
        wall = _wall(
            height_start_m=2.4, height_end_m=3.6,
            height_authority=WallHeightAuthority.MODEL_ESTIMATED.value,
            authority_status=AuthorityStatus.FIRM.value,
        )
        # height_authority's own rules (D.5) still apply on top of the formula fix.
        assert wall.authority_status == AuthorityStatus.PROVISIONAL.value


class TestFallbackToFlatFormulaAndGuardWithoutEndpointHeights:
    def test_raked_wall_without_endpoint_heights_still_uses_flat_formula_and_guard(self):
        wall = _wall(height_start_m=None, height_end_m=None, height_m=3.5, authority_status=AuthorityStatus.FIRM.value)
        assert wall.gross_area_m2 == pytest.approx(6.0 * 3.5)
        # No real endpoint data -> still just an approximation -> D.5 guard applies.
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value

    def test_raked_wall_with_only_one_endpoint_height_falls_back_to_guarded_flat_formula(self):
        wall = _wall(height_start_m=2.4, height_end_m=None, height_m=3.0, authority_status=AuthorityStatus.FIRM.value)
        assert wall.gross_area_m2 == pytest.approx(6.0 * 3.0)
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value

    @pytest.mark.parametrize("bad_end", [math.nan, math.inf, -math.inf, 0.0, -1.0])
    def test_malformed_endpoint_height_falls_back_to_guarded_flat_formula(self, bad_end):
        wall = _wall(height_start_m=2.4, height_end_m=bad_end, height_m=3.0, authority_status=AuthorityStatus.FIRM.value)
        assert wall.gross_area_m2 == pytest.approx(6.0 * 3.0)
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value

    def test_approval_still_promotes_the_guarded_flat_formula_case(self):
        wall = _wall(
            height_start_m=None, height_end_m=None, height_m=3.5,
            authority_status=AuthorityStatus.FIRM.value, approved_by="Lead Estimator Bryce",
        )
        assert wall.authority_status == AuthorityStatus.FIRM.value


class TestStairWallsAreUnaffected:
    def test_stair_wall_still_always_uses_the_guard_regardless_of_endpoint_fields(self):
        wall = _wall(
            wall_id="W_STAIR", wall_type="stair", height_start_m=2.4, height_end_m=3.6,
            authority_status=AuthorityStatus.FIRM.value,
        )
        # No formula exists for stair walls yet — the D.5 guard still applies even
        # if endpoint-height-shaped fields happen to be populated.
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value

    def test_standard_wall_type_ignores_endpoint_height_fields(self):
        wall = _wall(
            wall_id="W_STD", wall_type="standard", height_start_m=2.4, height_end_m=3.6,
            height_m=3.0, authority_status=AuthorityStatus.FIRM.value,
        )
        # A standard (non-raked) wall must keep using height_m via the normal flat
        # formula — endpoint fields are only meaningful for wall_type=="raked".
        assert wall.gross_area_m2 == pytest.approx(6.0 * 3.0)
        assert wall.authority_status == AuthorityStatus.FIRM.value
