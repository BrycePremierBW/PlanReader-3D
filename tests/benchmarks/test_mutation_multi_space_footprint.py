"""tests/benchmarks/test_mutation_multi_space_footprint.py

Mutation test suite for Phase F.11: Multi-Space / Verandah Footprint Geometry.

Enforces:
1. rectangle + 2m verandah adds exact evidenced area
2. change verandah to 3m => exact corresponding change
3. remove verandah => quantity decreases
4. L-shaped footprint uses polygon area, not bounding rectangle
5. internal courtyard/void subtracts correctly
6. shared internal edge is not double-counted as external perimeter
7. missing verandah width remains unresolved rather than guessed
"""
import pytest
from pb_multi_space_footprint_geometry import (
    FootprintGeometryResult,
    FootprintStatus,
    MultiSpaceFootprintBuilder,
    MultiSpaceFootprintEngine,
    SpaceComponent,
    SpaceType,
    compute_polygon_area,
    compute_polygon_perimeter,
)


def test_mutation_1_rectangle_plus_verandah_adds_exact_evidenced_area():
    """Mutation 1: Rectangle 10x6 + 2m verandah adds exactly 20 m2 of evidenced area."""
    builder = MultiSpaceFootprintBuilder()
    builder.add_main_room(length_m=10.0, width_m=6.0, label="Main Classroom")
    builder.add_verandah(length_m=10.0, width_m=2.0, adjacency="front", label="Front Verandah")
    result = builder.build()

    assert result.status == FootprintStatus.CONFIRMED.value
    assert result.component_areas["main_space_1"] == 60.0  # 10 * 6
    assert result.component_areas["verandah_2"] == 20.0    # 10 * 2
    assert result.gross_floor_area_m2 == 80.0             # 60 + 20
    assert result.dpm_area_m2 == 80.0
    assert result.mesh_area_m2 == 80.0


def test_mutation_2_change_verandah_to_3m_yields_exact_corresponding_change():
    """Mutation 2: Changing verandah width to 3m produces exact corresponding delta."""
    # Baseline with 2m verandah
    b_2m = MultiSpaceFootprintBuilder()
    b_2m.add_main_room(length_m=10.0, width_m=6.0)
    b_2m.add_verandah(length_m=10.0, width_m=2.0, adjacency="front")
    res_2m = b_2m.build()

    # Mutated with 3m verandah
    b_3m = MultiSpaceFootprintBuilder()
    b_3m.add_main_room(length_m=10.0, width_m=6.0)
    b_3m.add_verandah(length_m=10.0, width_m=3.0, adjacency="front")
    res_3m = b_3m.build()

    assert res_2m.gross_floor_area_m2 == 80.0
    assert res_3m.gross_floor_area_m2 == 90.0
    assert res_3m.gross_floor_area_m2 - res_2m.gross_floor_area_m2 == 10.0  # exactly 10m * 1m delta


def test_mutation_3_remove_verandah_decreases_quantity():
    """Mutation 3: Removing verandah decreases floor quantity to main room area only."""
    b_with_v = MultiSpaceFootprintBuilder()
    b_with_v.add_main_room(length_m=12.0, width_m=8.0)
    b_with_v.add_verandah(length_m=12.0, width_m=2.5, adjacency="front")
    res_with_v = b_with_v.build()

    b_no_v = MultiSpaceFootprintBuilder()
    b_no_v.add_main_room(length_m=12.0, width_m=8.0)
    res_no_v = b_no_v.build()

    assert res_with_v.gross_floor_area_m2 == 126.0  # 96 + 30
    assert res_no_v.gross_floor_area_m2 == 96.0     # 96
    assert res_no_v.gross_floor_area_m2 < res_with_v.gross_floor_area_m2


def test_mutation_4_l_shaped_footprint_uses_polygon_area_not_bounding_rectangle():
    """Mutation 4: L-shaped footprint uses exact shoelace polygon area, not bounding box."""
    # L-shape: 10m x 8m bounding envelope with a 4m x 4m cut-out in the top right
    # Vertices: (0,0) -> (10,0) -> (10,4) -> (6,4) -> (6,8) -> (0,8)
    l_shape_poly = [
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 4.0),
        (6.0, 4.0),
        (6.0, 8.0),
        (0.0, 8.0),
    ]

    expected_polygon_area = 10.0 * 8.0 - (4.0 * 4.0)  # 80 - 16 = 64.0 m2
    bounding_box_area = 10.0 * 8.0                   # 80.0 m2

    builder = MultiSpaceFootprintBuilder()
    builder.add_polygon_space(
        polygon=l_shape_poly,
        space_type=SpaceType.MAIN_BUILDING.value,
        label="L-shaped classroom block",
    )
    result = builder.build()

    assert result.gross_floor_area_m2 == expected_polygon_area
    assert result.gross_floor_area_m2 == 64.0
    assert result.gross_floor_area_m2 != bounding_box_area


def test_mutation_5_internal_courtyard_void_subtracts_correctly():
    """Mutation 5: Internal courtyard/void subtracts deterministically from floor, DPM, and mesh."""
    # Main building envelope: 16m x 12m = 192 m2
    # Internal courtyard void: 6m x 4m = 24 m2
    builder = MultiSpaceFootprintBuilder()
    builder.add_main_room(length_m=16.0, width_m=12.0, label="Enclosed Building")
    builder.add_courtyard_void(length_m=6.0, width_m=4.0, origin=(5.0, 4.0), label="Central Courtyard")
    result = builder.build()

    expected_net_area = 192.0 - 24.0  # 168.0 m2
    assert result.gross_floor_area_m2 == expected_net_area
    assert result.dpm_area_m2 == expected_net_area
    assert result.mesh_area_m2 == expected_net_area
    assert result.component_areas["void_2"] == 24.0  # Void component records 24.0 m2
    assert result.metadata["total_void_area_m2"] == 24.0


def test_mutation_6_shared_internal_edge_is_not_double_counted_as_external_perimeter():
    """Mutation 6: Shared edge between room and verandah is not double-counted as external perimeter."""
    # Main room: 10m x 6m -> perimeter 32m
    # Front verandah: 10m x 2m along front -> perimeter 24m
    # They share a 10m wall segment along (0,0) -> (10,0)
    builder = MultiSpaceFootprintBuilder()
    builder.add_main_room(length_m=10.0, width_m=6.0)
    builder.add_verandah(length_m=10.0, width_m=2.0, adjacency="front")
    result = builder.build()

    assert result.shared_edge_length_m == 10.0
    # Combined external perimeter = 2*(10 + 6 + 2) = 36m
    # If double counted, it would be 32 + 24 = 56m
    assert result.external_perimeter_m == 36.0
    assert result.external_perimeter_m != 56.0


def test_mutation_7_missing_verandah_width_remains_unresolved_rather_than_guessed():
    """Mutation 7: Missing verandah width remains unresolved with status partial_missing_components."""
    builder = MultiSpaceFootprintBuilder()
    builder.add_main_room(length_m=10.0, width_m=6.0, label="Classroom")
    # Verandah evidenced by label/annotation, but width is missing (None)
    builder.add_verandah(length_m=10.0, width_m=None, label="Unfigured Verandah")
    result = builder.build()

    assert result.status == FootprintStatus.PARTIAL_MISSING_COMPONENTS.value
    assert len(result.missing_components) == 1
    assert "width" in result.missing_components[0]
    # No guessed width (e.g. 1.8m or 2.0m) was applied
    assert result.component_areas["verandah_2"] == 0.0
    assert result.gross_floor_area_m2 == 60.0  # Only evidenced main room area
