"""tests/editable_3d/test_2d_to_3d_data_model.py — Tests for 2D-to-3D hierarchical data model."""
import json
import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_model import (
    BuildingModel,
    FinishModel,
    LevelModel,
    OpeningModel,
    RoofModel,
    RoomModel,
    SoffitModel,
    SurfaceModel,
    UnitModel,
    WallHeightAuthority,
    WallModel,
)


def test_complete_2d_to_3d_hierarchy_serialization():
    opening = OpeningModel(
        opening_id="OP_D01",
        wall_id="W_01",
        opening_type="door",
        width_m=0.9,
        height_m=2.1,
        area_m2=1.89,
        deducts=True,
        source_page_no=5,
        source_sheet_label="WD-02",
        approval_status=AuthorityStatus.FIRM.value,
    )
    surface = SurfaceModel(
        surface_id="SF_01",
        wall_id="W_01",
        face="internal",
        substrate="Plasterboard",
        finish_tag="PB01",
        area_m2=14.31,
        authority_status=AuthorityStatus.FIRM.value,
        approved_by="Bryce Curran",
    )
    wall = WallModel(
        wall_id="W_01",
        level_id="L_01",
        start_pt=(0.0, 0.0),
        end_pt=(6.0, 0.0),
        length_m=6.0,
        height_m=2.7,
        height_authority=WallHeightAuthority.DOCUMENTED_CEILING_HEIGHT.value,
        openings=[opening],
        surfaces=[surface],
        source_page_no=5,
        source_sheet_label="WD-02",
        scale_ratio="1:100",
        authority_status=AuthorityStatus.FIRM.value,
        approved_by="Bryce Curran",
    )
    room = RoomModel(
        room_id="RM_01",
        level_id="L_01",
        name="Living Room",
        floor_area_m2=24.5,
        perimeter_m=20.0,
        wall_ids=["W_01"],
        finish_tag="PB01",
        source_page_no=5,
        source_sheet_label="WD-02",
        authority_status=AuthorityStatus.FIRM.value,
    )
    unit = UnitModel(
        unit_id="U_01",
        unit_number="Townhouse 1",
        level_id="L_01",
        gfa_m2=75.0,
        room_ids=["RM_01"],
    )
    soffit = SoffitModel(
        soffit_id="SOF_01",
        level_id="L_01",
        location="Front Porch",
        area_m2=4.5,
        finish_tag="EC02",
    )
    level = LevelModel(
        level_id="L_01",
        name="Ground Floor",
        elevation_m=0.0,
        ceiling_height_m=2.7,
        units=[unit],
        rooms=[room],
        walls=[wall],
        soffits=[soffit],
        boundary_polygon=[(0, 0), (10, 0), (10, 8), (0, 8)],
        source_sheet_label="WD-02",
    )
    roof = RoofModel(
        roof_id="RF_01",
        roof_type="Gable",
        pitch_deg=22.5,
        area_m2=85.0,
        finish_tag="COLORBOND",
    )
    building = BuildingModel(
        building_id="BLDG_01",
        name="60-62 School Rd Townhouses",
        levels=[level],
        roofs=[roof],
        source_sheet="WD-01",
    )

    d = building.to_dict()
    assert d["building_id"] == "BLDG_01"
    assert len(d["levels"]) == 1
    assert len(d["levels"][0]["walls"]) == 1
    assert d["levels"][0]["walls"][0]["gross_area_m2"] == 16.2
    assert d["levels"][0]["walls"][0]["net_area_m2"] == 14.31  # 16.2 - 1.89 door deduction

    # JSON round trip
    json_str = json.dumps(d)
    assert json.loads(json_str) == d


def test_wall_traceability_links():
    wall = WallModel(
        wall_id="W_02",
        level_id="L_01",
        start_pt=(0.0, 0.0),
        end_pt=(5.0, 0.0),
        length_m=5.0,
        height_m=2.7,
        height_authority=WallHeightAuthority.DOCUMENTED_CEILING_HEIGHT.value,
        source_page_no=3,
        source_sheet_label="WD-03",
        scale_ratio="1:50",
    )
    assert wall.source_page_no == 3
    assert wall.source_sheet_label == "WD-03"
    assert wall.scale_ratio == "1:50"
    assert len(wall.revision_hash) > 0
