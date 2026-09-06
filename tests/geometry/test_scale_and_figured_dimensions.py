"""tests/geometry/test_scale_and_figured_dimensions.py — Tests for scale calibration and figured dimension precedence."""
import math
import pytest

from pb_geometry_takeoff_model import AuthorityStatus, ScaleCalibration, reconcile_figured_and_scaled


def test_scale_calibration_usability():
    # Usable calibrated scale
    calib = ScaleCalibration(
        page_no=5,
        ratio_str="1:100",
        px_per_m=28.35,
        method="GRAPHIC_SCALE_BAR",
        is_verified=True,
        confidence=0.98,
    )
    assert calib.is_usable_for_firm_measurement() is True

    # Unverified scale is not usable for firm
    unverified = ScaleCalibration(
        page_no=5,
        ratio_str="1:100",
        px_per_m=28.35,
        method="OCR_TEXT",
        is_verified=False,
        confidence=0.70,
    )
    assert unverified.is_usable_for_firm_measurement() is False

    # Zero or negative px_per_m is not usable
    zero_px = ScaleCalibration(
        page_no=5,
        ratio_str="1:100",
        px_per_m=0.0,
        method="OCR_TEXT",
        is_verified=True,
        confidence=0.9,
    )
    assert zero_px.is_usable_for_firm_measurement() is False

    # Infinite or NaN px_per_m is not usable
    nan_px = ScaleCalibration(
        page_no=5,
        ratio_str="1:100",
        px_per_m=math.nan,
        method="OCR_TEXT",
        is_verified=True,
        confidence=0.9,
    )
    assert nan_px.is_usable_for_firm_measurement() is False


def test_figured_dimension_precedence_matching_scaled():
    # Figured dimension 4500mm, scaled 4520mm (20mm delta, 0.44% < 5%)
    length_m, status, delta_mm, notes = reconcile_figured_and_scaled(
        figured_mm=4500.0,
        scaled_mm=4520.0,
    )
    assert length_m == 4.5
    assert status == AuthorityStatus.FIRM.value
    assert delta_mm == 20.0
    assert "precedence" in notes.lower()


def test_figured_dimension_precedence_divergent_scaled():
    # Figured dimension 4500mm, scaled 4900mm (400mm delta, 8.89% > 5%)
    length_m, status, delta_mm, notes = reconcile_figured_and_scaled(
        figured_mm=4500.0,
        scaled_mm=4900.0,
    )
    assert length_m == 4.5
    assert status == AuthorityStatus.REVIEW_REQUIRED.value
    assert delta_mm == 400.0
    assert "warning" in notes.lower()


def test_figured_dimension_without_scaled():
    length_m, status, delta_mm, notes = reconcile_figured_and_scaled(
        figured_mm=6200.0,
        scaled_mm=None,
    )
    assert length_m == 6.2
    assert status == AuthorityStatus.FIRM.value
    assert delta_mm is None


def test_scaled_only_becomes_provisional():
    length_m, status, delta_mm, notes = reconcile_figured_and_scaled(
        figured_mm=None,
        scaled_mm=3800.0,
    )
    assert length_m == 3.8
    assert status == AuthorityStatus.PROVISIONAL.value
    assert delta_mm is None
    assert "provisional" in notes.lower()


def test_neither_dimension_provided_raises():
    with pytest.raises(ValueError, match="Neither figured dimension nor scaled geometry"):
        reconcile_figured_and_scaled(figured_mm=None, scaled_mm=None)

    with pytest.raises(ValueError, match="Neither figured dimension nor scaled geometry"):
        reconcile_figured_and_scaled(figured_mm=0.0, scaled_mm=0.0)

    with pytest.raises(ValueError, match="Neither figured dimension nor scaled geometry"):
        reconcile_figured_and_scaled(figured_mm=-100.0, scaled_mm=-50.0)
