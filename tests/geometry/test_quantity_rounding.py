"""tests/geometry/test_quantity_rounding.py — Tests for quantity rounding and measurement record invariants."""
import math
import pytest

from pb_geometry_takeoff_model import (
    AuthorityStatus,
    Ceiling,
    ElevationSurface,
    ExclusionZone,
    FloorArea,
    MeasurementAuthorityType,
    MeasurementRecord,
    PlanPage,
    Room,
    ScaleCalibration,
    Soffit,
    Surface,
    WallSegment,
    calculate_wall_takeoff,
    reconcile_figured_and_scaled,
)


def test_measurement_record_validation():
    # Valid record
    rec = MeasurementRecord(
        value=124.5678,
        unit="m2",
        source_type=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        confidence=0.95,
        sheet="A101",
        page=3,
        scale="1:100",
        geometry_ref="wall-w1-gross",
        authority_status=AuthorityStatus.FIRM.value,
    )
    d = rec.to_dict()
    assert d["value"] == 124.5678
    assert d["unit"] == "m2"
    assert d["authority_status"] == "firm"

    # Confidence must be in [0.0, 1.0]
    with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
        MeasurementRecord(
            value=10.0,
            unit="m",
            source_type=MeasurementAuthorityType.PDF_SCALED.value,
            confidence=1.2,
            sheet="A101",
            page=1,
            scale="1:100",
            geometry_ref="ref",
            authority_status=AuthorityStatus.PROVISIONAL.value,
        )

    with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
        MeasurementRecord(
            value=10.0,
            unit="m",
            source_type=MeasurementAuthorityType.PDF_SCALED.value,
            confidence=-0.1,
            sheet="A101",
            page=1,
            scale="1:100",
            geometry_ref="ref",
            authority_status=AuthorityStatus.PROVISIONAL.value,
        )

    # Value must be finite
    with pytest.raises(ValueError, match="Measurement value must be finite"):
        MeasurementRecord(
            value=math.nan,
            unit="m",
            source_type=MeasurementAuthorityType.PDF_SCALED.value,
            confidence=0.5,
            sheet="A101",
            page=1,
            scale="1:100",
            geometry_ref="ref",
            authority_status=AuthorityStatus.PROVISIONAL.value,
        )

    with pytest.raises(ValueError, match="Measurement value must be finite"):
        MeasurementRecord(
            value=math.inf,
            unit="m",
            source_type=MeasurementAuthorityType.PDF_SCALED.value,
            confidence=0.5,
            sheet="A101",
            page=1,
            scale="1:100",
            geometry_ref="ref",
            authority_status=AuthorityStatus.PROVISIONAL.value,
        )


def test_rounding_precision_invariants():
    # Test that floating point rounding remains stable at 4 decimal places
    gross, deductions, net = calculate_wall_takeoff(
        length_m=3.33333333,
        height_m=2.7,
    )
    # 3.33333333 * 2.7 = 8.999999991 -> rounded to 9.0
    assert gross == 9.0
    assert deductions == 0.0
    assert net == 9.0

    length_m, status, delta_mm, _ = reconcile_figured_and_scaled(
        figured_mm=3333.3333,
        scaled_mm=3340.5555,
    )
    assert length_m == 3.3333
    assert delta_mm == 7.22


def test_domain_dataclasses_instantiation():
    calib = ScaleCalibration(
        page_no=1,
        ratio_str="1:100",
        px_per_m=28.35,
        method="KNOWN_CALIBRATED",
        is_verified=True,
        confidence=1.0,
    )
    page = PlanPage(
        page_id=1,
        page_no=1,
        sheet_label="WD-01",
        canonical_role="FLOOR_PLAN",
        scale_calibration=calib,
    )
    assert page.sheet_label == "WD-01"

    room = Room(
        room_id="RM_01",
        room_name="Master Bed",
        floor_area_m2=16.5,
        perimeter_m=16.4,
        ceiling_height_m=2.7,
    )
    assert room.floor_area_m2 == 16.5

    surf = Surface(
        surface_id="SF_01",
        surface_type="internal_wall",
        substrate="Plasterboard",
        finish_tag="PB01",
        gross_area_m2=44.28,
        deduction_area_m2=3.78,
        net_area_m2=40.5,
    )
    assert surf.net_area_m2 == 40.5

    ceiling = Ceiling(
        ceiling_id="CL_01",
        room_name="Living",
        area_m2=32.0,
        void_deductions_m2=2.0,
        net_area_m2=30.0,
        rcp_sheet="WD-04",
    )
    assert ceiling.net_area_m2 == 30.0

    floor = FloorArea(
        floor_id="FL_01",
        level_name="Ground Floor",
        gfa_m2=120.5,
        internal_area_m2=105.0,
    )
    assert floor.gfa_m2 == 120.5

    elev = ElevationSurface(
        elevation_id="EL_01",
        facade_side="North",
        block="Block A",
        finish_tag="EC01",
        gross_area_m2=150.0,
        deduction_area_m2=35.0,
        net_area_m2=115.0,
    )
    assert elev.net_area_m2 == 115.0

    soffit = Soffit(
        soffit_id="SOF_01",
        location="Balcony",
        area_m2=12.5,
        finish_tag="EC02",
    )
    assert soffit.area_m2 == 12.5

    excl = ExclusionZone(
        exclusion_id="EX_01",
        reason="Lift shaft void",
        coordinates=[(0, 0), (2, 0), (2, 2), (0, 2)],
    )
    assert len(excl.coordinates) == 4


def test_wall_segment_dimension_invariants():
    with pytest.raises(ValueError, match="Wall dimensions cannot be negative"):
        WallSegment(wall_id="W01", length_m=-5.0, height_m=2.7, gross_area_m2=13.5, net_area_m2=13.5)

    with pytest.raises(ValueError, match="Wall dimensions cannot be negative"):
        WallSegment(wall_id="W01", length_m=5.0, height_m=-2.7, gross_area_m2=13.5, net_area_m2=13.5)

    with pytest.raises(ValueError, match="Wall dimensions must be finite"):
        WallSegment(wall_id="W01", length_m=math.nan, height_m=2.7, gross_area_m2=13.5, net_area_m2=13.5)
