"""tests/editable_3d/test_massing_model_generation.py — Tests for 3D massing preview generation."""
import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_model import (
    LevelModel,
    generate_massing_model_from_levels,
)


def test_massing_model_generation():
    # 2 levels: Ground (0.0m - 2.7m), First Floor (2.7m - 5.4m)
    # 10m x 8m rectangle = 80 m2, perimeter = 36m
    poly = [(0, 0), (10, 0), (10, 8), (0, 8)]

    lvl1 = LevelModel(
        level_id="L_01",
        name="Ground Floor",
        elevation_m=0.0,
        ceiling_height_m=2.7,
        boundary_polygon=poly,
    )
    lvl2 = LevelModel(
        level_id="L_02",
        name="First Floor",
        elevation_m=2.7,
        ceiling_height_m=2.7,
        boundary_polygon=poly,
    )

    massing = generate_massing_model_from_levels([lvl1, lvl2])

    assert massing["massing_levels_count"] == 2
    assert massing["is_generated_preview"] is True
    assert massing["authority_status"] == AuthorityStatus.PROVISIONAL.value

    # Floor area 80 m2 per level * 2.7m height = 216 m3 volume each -> 432 m3 total
    assert massing["total_volume_m3"] == 432.0

    # Facade per level = 36m * 2.7m = 97.2 m2 -> 194.4 m2 total
    assert massing["total_facade_m2"] == 194.4

    # Mesh details
    mesh1 = massing["meshes"][0]
    assert mesh1["level_name"] == "Ground Floor"
    assert mesh1["base_elevation_m"] == 0.0
    assert mesh1["top_elevation_m"] == 2.7
    assert mesh1["floor_area_m2"] == 80.0
    assert mesh1["is_generated_massing"] is True
    assert mesh1["is_source_render_sheet"] is False


def test_massing_model_empty_or_degraded_polygons():
    lvl = LevelModel(
        level_id="L_EMPTY",
        name="Empty Level",
        elevation_m=0.0,
        ceiling_height_m=2.7,
        boundary_polygon=[(0, 0), (5, 5)],  # < 3 points
    )
    massing = generate_massing_model_from_levels([lvl])
    assert massing["massing_levels_count"] == 0
    assert massing["total_volume_m3"] == 0.0
