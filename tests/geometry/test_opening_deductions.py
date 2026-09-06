"""tests/geometry/test_opening_deductions.py — Tests for door, window, and void opening deductions."""
import math
import pytest

from pb_geometry_takeoff_model import Door, Opening, WallSegment, Window, calculate_wall_takeoff


def test_opening_validation_non_negative():
    with pytest.raises(ValueError, match="cannot be negative"):
        Opening(opening_id="D01", opening_type="door", width_m=-0.9, height_m=2.1, area_m2=1.89)

    with pytest.raises(ValueError, match="cannot be negative"):
        Opening(opening_id="D01", opening_type="door", width_m=0.9, height_m=-2.1, area_m2=1.89)

    with pytest.raises(ValueError, match="cannot be negative"):
        Opening(opening_id="D01", opening_type="door", width_m=0.9, height_m=2.1, area_m2=-1.89)


def test_opening_validation_finite():
    with pytest.raises(ValueError, match="finite numbers"):
        Opening(opening_id="D01", opening_type="door", width_m=math.nan, height_m=2.1, area_m2=1.89)

    with pytest.raises(ValueError, match="finite numbers"):
        Opening(opening_id="D01", opening_type="door", width_m=0.9, height_m=math.inf, area_m2=1.89)


def test_opening_deducts_flag_false():
    # If deducts=False, it should not be deducted even if area > 0.5 m2
    opening = Opening(
        opening_id="D01",
        opening_type="door",
        width_m=0.9,
        height_m=2.1,
        area_m2=1.89,
        deducts=False,
    )
    gross, deductions, net = calculate_wall_takeoff(
        length_m=5.0,
        height_m=2.7,
        openings=[opening],
    )
    assert deductions == 0.0
    assert net == gross


def test_door_and_window_domain_objects():
    door_op = Opening(opening_id="OP_D01", opening_type="door", width_m=0.82, height_m=2.04, area_m2=1.6728)
    door = Door(opening=door_op, door_code="D01", paint_treatment="2_COAT_GLOSS", is_entry=True, is_excluded=False)

    assert door.area_m2 == 1.6728
    assert door.is_entry is True
    assert door.is_excluded is False

    win_op = Opening(opening_id="OP_W01", opening_type="window", width_m=1.2, height_m=1.0, area_m2=1.2)
    window = Window(opening=win_op, window_code="W01", glazing_type="double_glazed", is_obscure=True)

    assert window.area_m2 == 1.2
    assert window.glazing_type == "double_glazed"
    assert window.is_obscure is True


def test_wall_segment_with_openings():
    op1 = Opening(opening_id="D01", opening_type="door", width_m=0.9, height_m=2.1, area_m2=1.89)
    op2 = Opening(opening_id="W01", opening_type="window", width_m=1.8, height_m=1.2, area_m2=2.16)

    gross, deductions, net = calculate_wall_takeoff(length_m=8.0, height_m=2.7, openings=[op1, op2])

    wall = WallSegment(
        wall_id="WALL_01",
        length_m=8.0,
        height_m=2.7,
        gross_area_m2=gross,
        net_area_m2=net,
        openings=[op1, op2],
    )

    assert wall.gross_area_m2 == 21.6
    assert wall.net_area_m2 == 17.55
    assert len(wall.openings) == 2


def test_garage_door_large_opening_deduction():
    garage_opening = Opening(
        opening_id="GD01",
        opening_type="door",
        width_m=4.8,
        height_m=2.4,
        area_m2=11.52,
    )
    gross, deductions, net = calculate_wall_takeoff(
        length_m=6.0,
        height_m=2.7,
        openings=[garage_opening],
    )
    assert gross == 16.2
    assert deductions == 11.52
    assert round(net, 2) == 4.68
