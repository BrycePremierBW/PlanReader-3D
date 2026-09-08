"""Component-aware floor-finish geometry derived only from drawing evidence.

A compound footprint may mix enclosed rooms with open verandahs.  The structural
footprint for slab/DPM/mesh follows the evidenced outer component geometry, while
an internal floor finish inside an enclosed rectangular room is measured to the
clear wall faces when a wall thickness is independently corroborated.

This module contains no benchmark identities, expected quantities, project names,
or convenience thicknesses.  Missing, ambiguous, unsupported, or partial geometry
fails closed by returning ``None``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, Optional

from pb_multi_space_footprint_geometry import (
    FootprintGeometryResult,
    FootprintStatus,
    SpaceType,
)


@dataclass(frozen=True)
class ComponentFloorFinishResult:
    """Traceable finish-area result for one enclosed main space plus verandahs."""

    structural_footprint_area_m2: float
    floor_finish_area_m2: float
    wall_thickness_m: float
    main_component_id: str
    main_outer_length_m: float
    main_outer_width_m: float
    main_clear_length_m: float
    main_clear_width_m: float
    main_clear_area_m2: float
    open_verandah_area_m2: float
    component_finish_areas_m2: Dict[str, float] = field(default_factory=dict)


def derive_component_aware_floor_finish_area(
    footprint: FootprintGeometryResult,
    wall_thickness_m: Optional[float],
) -> Optional[ComponentFloorFinishResult]:
    """Resolve a compound floor-finish area without changing structural area.

    Supported evidence shape:
    - footprint is fully confirmed with no missing components or voids;
    - exactly one evidenced rectangular ``MAIN_BUILDING`` component;
    - every other solid component is an evidenced ``VERANDAH``;
    - wall thickness is independently resolved and physically valid.

    The enclosed main component is converted from outer dimensions to clear-face
    dimensions using ``(L - 2t) * (W - 2t)``.  Verandah components remain at their
    full evidenced area because they are not enclosed by the main room's two
    opposing wall faces.  Ancillary/unspecified components and voids are left
    unresolved rather than assuming their enclosure or finish basis.
    """
    if wall_thickness_m is None or not math.isfinite(wall_thickness_m) or wall_thickness_m <= 0.0:
        return None
    if footprint.status != FootprintStatus.CONFIRMED.value or footprint.missing_components:
        return None
    if footprint.metadata.get("num_voids", 0):
        return None

    main_components = [
        c for c in footprint.components
        if not c.is_void and c.space_type == SpaceType.MAIN_BUILDING.value
    ]
    if len(main_components) != 1:
        return None

    solid_components = [c for c in footprint.components if not c.is_void]
    if any(
        c.space_type not in (SpaceType.MAIN_BUILDING.value, SpaceType.VERANDAH.value)
        for c in solid_components
    ):
        return None
    if any(
        not c.has_evidenced_dimensions or c.missing_dimensions
        for c in solid_components
    ):
        return None

    main = main_components[0]
    if main.length_m is None or main.width_m is None:
        return None
    if not math.isfinite(main.length_m) or not math.isfinite(main.width_m):
        return None
    if main.length_m <= 0.0 or main.width_m <= 0.0:
        return None

    clear_length_m = main.length_m - 2.0 * wall_thickness_m
    clear_width_m = main.width_m - 2.0 * wall_thickness_m
    if clear_length_m <= 0.0 or clear_width_m <= 0.0:
        return None

    component_finish_areas: Dict[str, float] = {}
    main_clear_area = clear_length_m * clear_width_m
    component_finish_areas[main.space_id] = round(main_clear_area, 2)

    verandah_area = 0.0
    for comp in solid_components:
        if comp.space_type != SpaceType.VERANDAH.value:
            continue
        if not math.isfinite(comp.area_m2) or comp.area_m2 < 0.0:
            return None
        verandah_area += comp.area_m2
        component_finish_areas[comp.space_id] = round(comp.area_m2, 2)

    finish_area = main_clear_area + verandah_area
    if not math.isfinite(finish_area) or finish_area <= 0.0:
        return None

    return ComponentFloorFinishResult(
        structural_footprint_area_m2=round(footprint.gross_floor_area_m2, 2),
        floor_finish_area_m2=round(finish_area, 2),
        wall_thickness_m=round(wall_thickness_m, 4),
        main_component_id=main.space_id,
        main_outer_length_m=round(main.length_m, 4),
        main_outer_width_m=round(main.width_m, 4),
        main_clear_length_m=round(clear_length_m, 4),
        main_clear_width_m=round(clear_width_m, 4),
        main_clear_area_m2=round(main_clear_area, 2),
        open_verandah_area_m2=round(verandah_area, 2),
        component_finish_areas_m2=component_finish_areas,
    )
