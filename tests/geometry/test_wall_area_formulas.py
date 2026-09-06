"""tests/geometry/test_wall_area_formulas.py — Tests for core wall area takeoff formulas."""
import math
import pytest

from pb_geometry_takeoff_model import Opening, calculate_wall_takeoff


def test_basic_wall_takeoff_no_openings():
    gross, deductions, net = calculate_wall_takeoff(length_m=5.0, height_m=2.7)
    assert gross == 13.5
    assert deductions == 0.0
    assert net == 13.5


def test_wall_takeoff_deduction_above_threshold():
    # 0.9m x 2.1m = 1.89 m2 > 0.5 m2 -> deducted
    door = Opening(
        opening_id="D01",
        opening_type="door",
        width_m=0.9,
        height_m=2.1,
        area_m2=1.89,
    )
    gross, deductions, net = calculate_wall_takeoff(
        length_m=6.0,
        height_m=2.7,
        openings=[door],
    )
    assert gross == 16.2
    assert deductions == 1.89
    assert net == 14.31


def test_wall_takeoff_deduction_below_threshold_as4041():
    # 0.5m x 0.8m = 0.4 m2 <= 0.5 m2 -> NOT deducted under AS 4041
    small_vent = Opening(
        opening_id="V01",
        opening_type="void",
        width_m=0.5,
        height_m=0.8,
        area_m2=0.4,
    )
    gross, deductions, net = calculate_wall_takeoff(
        length_m=4.0,
        height_m=2.7,
        openings=[small_vent],
        standard="AS4041",
    )
    assert gross == 10.8
    assert deductions == 0.0
    assert net == 10.8


def test_wall_takeoff_deduction_below_threshold_non_as4041():
    # If standard is not AS4041, opening of 0.4 m2 is deducted
    small_vent = Opening(
        opening_id="V01",
        opening_type="void",
        width_m=0.5,
        height_m=0.8,
        area_m2=0.4,
    )
    gross, deductions, net = calculate_wall_takeoff(
        length_m=4.0,
        height_m=2.7,
        openings=[small_vent],
        standard="CUSTOM",
    )
    assert gross == 10.8
    assert deductions == 0.4
    assert net == 10.4


def test_wall_takeoff_multiple_openings():
    door = Opening(
        opening_id="D01",
        opening_type="door",
        width_m=0.9,
        height_m=2.1,
        area_m2=1.89,
    )
    window = Opening(
        opening_id="W01",
        opening_type="window",
        width_m=1.8,
        height_m=1.2,
        area_m2=2.16,
    )
    small_opening = Opening(
        opening_id="V01",
        opening_type="void",
        width_m=0.5,
        height_m=0.5,
        area_m2=0.25,
    )
    gross, deductions, net = calculate_wall_takeoff(
        length_m=10.0,
        height_m=3.0,
        openings=[door, window, small_opening],
    )
    assert gross == 30.0
    # small_opening (0.25 <= 0.5) is ignored; 1.89 + 2.16 = 4.05
    assert deductions == 4.05
    assert net == 25.95


def test_wall_takeoff_deductions_exceed_gross_raises_error():
    huge_opening = Opening(
        opening_id="VOID01",
        opening_type="void",
        width_m=10.0,
        height_m=3.0,
        area_m2=30.0,
    )
    # Gross is 5.0 * 2.0 = 10.0 m2, opening is 30.0 m2
    with pytest.raises(ValueError, match="exceed gross wall area"):
        calculate_wall_takeoff(
            length_m=5.0,
            height_m=2.0,
            openings=[huge_opening],
        )


def test_wall_takeoff_negative_and_zero_dimensions_rejected():
    with pytest.raises(ValueError, match="strictly positive"):
        calculate_wall_takeoff(length_m=0.0, height_m=2.7)

    with pytest.raises(ValueError, match="strictly positive"):
        calculate_wall_takeoff(length_m=-5.0, height_m=2.7)

    with pytest.raises(ValueError, match="strictly positive"):
        calculate_wall_takeoff(length_m=5.0, height_m=0.0)

    with pytest.raises(ValueError, match="strictly positive"):
        calculate_wall_takeoff(length_m=5.0, height_m=-2.7)


def test_wall_takeoff_non_finite_dimensions_rejected():
    with pytest.raises(ValueError, match="finite numbers"):
        calculate_wall_takeoff(length_m=math.nan, height_m=2.7)

    with pytest.raises(ValueError, match="finite numbers"):
        calculate_wall_takeoff(length_m=5.0, height_m=math.inf)
