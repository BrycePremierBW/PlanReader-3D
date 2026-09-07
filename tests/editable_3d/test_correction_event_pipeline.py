"""tests/editable_3d/test_correction_event_pipeline.py — Tests for user correction events and quantity recalculation."""
import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_model import (
    BuildingModel,
    CorrectionAction,
    CorrectionEvent,
    LevelModel,
    OpeningModel,
    WallHeightAuthority,
    WallModel,
    apply_correction_event,
)


@pytest.fixture
def sample_building():
    wall = WallModel(
        wall_id="W_101",
        level_id="L_01",
        start_pt=(0.0, 0.0),
        end_pt=(6.0, 0.0),
        length_m=6.0,
        height_m=2.7,
        height_authority=WallHeightAuthority.MODEL_ESTIMATED.value,
        authority_status=AuthorityStatus.PROVISIONAL.value,
        source_page_no=1,
        source_sheet_label="WD-01",
    )
    level = LevelModel(
        level_id="L_01",
        name="Ground Floor",
        elevation_m=0.0,
        ceiling_height_m=2.7,
        walls=[wall],
    )
    bldg = BuildingModel(
        building_id="BLDG_01",
        name="Test Building",
        levels=[level],
    )
    bldg.compute_building_revision_hash()
    return bldg


def test_change_wall_height_recalculates_quantities_and_updates_authority(sample_building):
    bldg = sample_building
    old_bldg_hash = bldg.revision_hash
    old_wall = bldg.levels[0].walls[0]
    old_wall_hash = old_wall.revision_hash

    assert old_wall.gross_area_m2 == 16.2
    assert old_wall.authority_status == AuthorityStatus.PROVISIONAL.value

    # Create change height correction event: 2.7m -> 3.0m
    event = CorrectionEvent(
        correction_id="corr_01",
        object_id="W_101",
        object_type="wall",
        action=CorrectionAction.CHANGE_HEIGHT.value,
        field_name="height_m",
        old_value=2.7,
        new_value=3.0,
        reason="Aligned with structural section S-01",
        actor="Bryce Curran",
    )

    updated_bldg, recals = apply_correction_event(bldg, event)
    wall = updated_bldg.levels[0].walls[0]

    # Gross area recalculated: 6.0 * 3.0 = 18.0
    assert wall.height_m == 3.0
    assert wall.gross_area_m2 == 18.0
    assert wall.net_area_m2 == 18.0

    # A correction is not an approval: it must require review, not auto-approve.
    assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
    assert wall.approved_by is None
    assert wall.approved_at is None
    assert wall.height_authority == WallHeightAuthority.USER_ENTERED.value

    # Revision hashes mutated
    assert wall.revision_hash != old_wall_hash
    assert updated_bldg.revision_hash != old_bldg_hash

    # Preflight invalidated flag set
    assert len(recals) == 1
    assert recals[0].is_preflight_invalidated is True
    assert recals[0].new_gross_m2 == 18.0


def test_add_opening_recalculates_net_wall_area(sample_building):
    bldg = sample_building
    wall = bldg.levels[0].walls[0]

    assert wall.gross_area_m2 == 16.2
    assert wall.net_area_m2 == 16.2

    # Add door opening (0.9m x 2.1m = 1.89 m2 > 0.5 m2 AS 4041 threshold)
    event = CorrectionEvent(
        correction_id="corr_02",
        object_id="W_101",
        object_type="wall",
        action=CorrectionAction.ADD_OPENING.value,
        field_name="openings",
        old_value=None,
        new_value={
            "opening_id": "D_ENTRY",
            "opening_type": "door",
            "width_m": 0.9,
            "height_m": 2.1,
            "area_m2": 1.89,
            "deducts": True,
        },
        reason="Added entry door from door schedule",
        actor="Bryce Curran",
    )

    updated_bldg, recals = apply_correction_event(bldg, event)
    updated_wall = updated_bldg.levels[0].walls[0]

    assert len(updated_wall.openings) == 1
    assert updated_wall.gross_area_m2 == 16.2
    assert updated_wall.net_area_m2 == 14.31  # 16.2 - 1.89
    assert recals[0].new_net_m2 == 14.31


def test_approve_and_reject_quantity(sample_building):
    bldg = sample_building
    wall = bldg.levels[0].walls[0]

    # 1. Approve quantity
    ev_app = CorrectionEvent(
        correction_id="corr_03",
        object_id="W_101",
        object_type="wall",
        action=CorrectionAction.APPROVE_QUANTITY.value,
        field_name="authority_status",
        old_value="provisional",
        new_value="firm",
        reason="Verified against architectural elevation",
        actor="Bryce Curran",
    )
    bldg, _ = apply_correction_event(bldg, ev_app)
    assert wall.authority_status == AuthorityStatus.FIRM.value
    assert wall.approved_by == "Bryce Curran"

    # 2. Reject quantity
    ev_rej = CorrectionEvent(
        correction_id="corr_04",
        object_id="W_101",
        object_type="wall",
        action=CorrectionAction.REJECT_QUANTITY.value,
        field_name="authority_status",
        old_value="firm",
        new_value="review_required",
        reason="Conflicting revision detected",
        actor="Bryce Curran",
    )
    bldg, _ = apply_correction_event(bldg, ev_rej)
    assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
    assert wall.approved_by is None
