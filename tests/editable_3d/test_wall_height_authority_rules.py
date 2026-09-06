"""tests/editable_3d/test_wall_height_authority_rules.py — Tests for wall height authority and commercial safety."""
import math
import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_model import (
    WallHeightAuthority,
    WallModel,
)


def test_documented_ceiling_height_is_firm():
    wall = WallModel(
        wall_id="W_01",
        level_id="L_01",
        start_pt=(0.0, 0.0),
        end_pt=(4.0, 0.0),
        length_m=4.0,
        height_m=2.7,
        height_authority=WallHeightAuthority.DOCUMENTED_CEILING_HEIGHT.value,
        authority_status=AuthorityStatus.FIRM.value,
        approved_by="Architect Plans",
    )
    assert wall.gross_area_m2 == 10.8
    assert wall.authority_status == AuthorityStatus.FIRM.value


def test_model_estimated_height_is_provisional():
    wall = WallModel(
        wall_id="W_EST",
        level_id="L_01",
        start_pt=(0.0, 0.0),
        end_pt=(5.0, 0.0),
        length_m=5.0,
        height_m=2.7,
        height_authority=WallHeightAuthority.MODEL_ESTIMATED.value,
        authority_status=AuthorityStatus.PROVISIONAL.value,
    )
    assert wall.authority_status == AuthorityStatus.PROVISIONAL.value


def test_raked_and_stair_walls_require_review():
    raked_wall = WallModel(
        wall_id="W_RAKED",
        level_id="L_02",
        start_pt=(0.0, 0.0),
        end_pt=(6.0, 0.0),
        length_m=6.0,
        height_m=3.5,
        height_authority=WallHeightAuthority.RAKED_WALL.value,
        wall_type="raked",
        authority_status=AuthorityStatus.REVIEW_REQUIRED.value,
    )
    assert raked_wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
    assert raked_wall.wall_type == "raked"

    stair_wall = WallModel(
        wall_id="W_STAIR",
        level_id="L_01",
        start_pt=(0.0, 0.0),
        end_pt=(4.5, 0.0),
        length_m=4.5,
        height_m=4.2,
        height_authority=WallHeightAuthority.STAIR_WALL.value,
        wall_type="stair",
        authority_status=AuthorityStatus.REVIEW_REQUIRED.value,
    )
    assert stair_wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value


def test_unknown_or_negative_height_rejected():
    with pytest.raises(ValueError, match="cannot be negative"):
        WallModel(
            wall_id="W_NEG",
            level_id="L_01",
            start_pt=(0.0, 0.0),
            end_pt=(4.0, 0.0),
            length_m=4.0,
            height_m=-2.7,
            height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value,
        )

    with pytest.raises(ValueError, match="must be finite"):
        WallModel(
            wall_id="W_NAN",
            level_id="L_01",
            start_pt=(0.0, 0.0),
            end_pt=(4.0, 0.0),
            length_m=4.0,
            height_m=math.nan,
            height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value,
        )
