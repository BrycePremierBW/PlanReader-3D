"""pb_multi_space_footprint_geometry.py — Multi-Space / Verandah Footprint Geometry Engine.

Constructs floor, substructure, and perimeter takeoff quantities from multiple
evidenced polygons and spaces instead of assuming a single rectangular building envelope.

Supports:
- Main room/building footprint
- Verandahs (front, rear, side, or wrap-around)
- Attached ancillary spaces
- Recesses and stepped layouts
- L-shaped / compound polygons
- Internal voids and courtyards

Enforces strict fail-closed contract:
- If verandah or ancillary space is labeled on drawing but dimensions are missing:
  do not invent or guess any dimension. Return partial/provisional geometry with
  explicit missing components.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Enums & Data Contracts
# ---------------------------------------------------------------------------

class SpaceType(str, Enum):
    MAIN_BUILDING = "main_building"
    VERANDAH = "verandah"
    ANCILLARY = "ancillary"
    RECESS = "recess"
    COURTYARD_VOID = "courtyard_void"
    UNSPECIFIED = "unspecified"


class FootprintStatus(str, Enum):
    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"
    PARTIAL_MISSING_COMPONENTS = "partial_missing_components"


@dataclass
class SpaceComponent:
    """Individual architectural space or polygon within a building footprint."""
    space_id: str
    space_type: str  # from SpaceType
    label: str
    polygon: List[Tuple[float, float]] = field(default_factory=list)
    width_m: Optional[float] = None
    length_m: Optional[float] = None
    area_m2: float = 0.0
    perimeter_m: float = 0.0
    is_void: bool = False
    has_evidenced_dimensions: bool = True
    missing_dimensions: List[str] = field(default_factory=list)
    spatial_adjacency: Optional[str] = None
    confidence: float = 1.0
    source_page: Optional[int] = None
    bounding_box: Optional[List[float]] = None

    def __post_init__(self) -> None:
        if self.polygon and len(self.polygon) >= 3:
            calc_area = compute_polygon_area(self.polygon)
            calc_perim = compute_polygon_perimeter(self.polygon)
            if self.area_m2 == 0.0:
                self.area_m2 = round(calc_area, 2)
            if self.perimeter_m == 0.0:
                self.perimeter_m = round(calc_perim, 2)
        elif self.has_evidenced_dimensions and self.width_m is not None and self.length_m is not None:
            if self.area_m2 == 0.0:
                self.area_m2 = round(self.length_m * self.width_m, 2)
            if self.perimeter_m == 0.0:
                self.perimeter_m = round(2.0 * (self.length_m + self.width_m), 2)


@dataclass
class EdgeSegment:
    """Directed edge segment belonging to one or more spaces."""
    start: Tuple[float, float]
    end: Tuple[float, float]
    length_m: float
    is_shared: bool
    is_external: bool
    space_ids: List[str] = field(default_factory=list)


@dataclass
class FootprintGeometryResult:
    """Comprehensive geometric result for a multi-space compound footprint."""
    components: List[SpaceComponent]
    component_areas: Dict[str, float]
    union_area_m2: float
    gross_floor_area_m2: float
    dpm_area_m2: float
    mesh_area_m2: float
    external_perimeter_m: float
    shared_edge_length_m: float
    dpc_length_m: float
    union_polygon: Optional[List[Tuple[float, float]]] = None
    status: str = FootprintStatus.CONFIRMED.value
    missing_components: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core Polygon Geometry Algorithms
# ---------------------------------------------------------------------------

def compute_polygon_area(points: Sequence[Tuple[float, float]]) -> float:
    """Calculate 2D Shoelace area of a simple polygon in coordinate units."""
    if len(points) < 3:
        return 0.0
    n = len(points)
    twice_area = 0.0
    for i in range(n):
        j = (i + 1) % n
        twice_area += points[i][0] * points[j][1] - points[j][0] * points[i][1]
    return abs(twice_area) / 2.0


def compute_polygon_perimeter(points: Sequence[Tuple[float, float]]) -> float:
    """Calculate perimeter length of a polygon."""
    if len(points) < 2:
        return 0.0
    n = len(points)
    perim = 0.0
    for i in range(n):
        j = (i + 1) % n
        dx = points[j][0] - points[i][0]
        dy = points[j][1] - points[i][1]
        perim += math.hypot(dx, dy)
    return perim


def compute_collinear_segment_overlap(
    seg1: Tuple[Tuple[float, float], Tuple[float, float]],
    seg2: Tuple[Tuple[float, float], Tuple[float, float]],
    tol: float = 1e-3,
) -> float:
    """Compute overlap length between two collinear 2D line segments."""
    p1, p2 = seg1
    p3, p4 = seg2

    dx1 = p2[0] - p1[0]
    dy1 = p2[1] - p1[1]
    len1 = math.hypot(dx1, dy1)
    if len1 < tol:
        return 0.0

    ux = dx1 / len1
    uy = dy1 / len1

    # Perpendicular distance of p3 and p4 from line through p1->p2
    dist3 = abs(-uy * (p3[0] - p1[0]) + ux * (p3[1] - p1[1]))
    dist4 = abs(-uy * (p4[0] - p1[0]) + ux * (p4[1] - p1[1]))
    if dist3 > tol or dist4 > tol:
        return 0.0

    # Project p3 and p4 onto line p1->p2
    t3 = ux * (p3[0] - p1[0]) + uy * (p3[1] - p1[1])
    t4 = ux * (p4[0] - p1[0]) + uy * (p4[1] - p1[1])

    seg2_min = min(t3, t4)
    seg2_max = max(t3, t4)

    overlap_min = max(0.0, seg2_min)
    overlap_max = min(len1, seg2_max)

    if overlap_max > overlap_min + tol:
        return overlap_max - overlap_min
    return 0.0


# ---------------------------------------------------------------------------
# Multi-Space Footprint Engine & Builder
# ---------------------------------------------------------------------------

class MultiSpaceFootprintEngine:
    """Calculates compound footprint metrics from multiple spaces."""

    @classmethod
    def evaluate(cls, components: List[SpaceComponent]) -> FootprintGeometryResult:
        component_areas: Dict[str, float] = {}
        missing_components: List[str] = []
        is_partial = False
        is_provisional = False

        solid_components: List[SpaceComponent] = []
        void_components: List[SpaceComponent] = []

        for comp in components:
            if not comp.has_evidenced_dimensions or comp.missing_dimensions:
                is_partial = True
                missing_desc = f"{comp.label} (missing: {', '.join(comp.missing_dimensions)})"
                missing_components.append(missing_desc)
                component_areas[comp.space_id] = 0.0
                continue

            component_areas[comp.space_id] = comp.area_m2
            if comp.confidence < 0.85:
                is_provisional = True

            if comp.is_void or comp.space_type == SpaceType.COURTYARD_VOID.value:
                void_components.append(comp)
            else:
                solid_components.append(comp)

        # Gross & Net floor area calculations
        total_solid_area = sum(c.area_m2 for c in solid_components)
        total_void_area = sum(c.area_m2 for c in void_components)
        net_floor_area = max(0.0, total_solid_area - total_void_area)

        # Detect shared internal edges between solid spaces
        shared_edge_length = 0.0
        n_solid = len(solid_components)

        for i in range(n_solid):
            c1 = solid_components[i]
            if not c1.polygon or len(c1.polygon) < 3:
                continue
            for j in range(i + 1, n_solid):
                c2 = solid_components[j]
                if not c2.polygon or len(c2.polygon) < 3:
                    continue

                for e1_idx in range(len(c1.polygon)):
                    e1 = (c1.polygon[e1_idx], c1.polygon[(e1_idx + 1) % len(c1.polygon)])
                    for e2_idx in range(len(c2.polygon)):
                        e2 = (c2.polygon[e2_idx], c2.polygon[(e2_idx + 1) % len(c2.polygon)])
                        overlap = compute_collinear_segment_overlap(e1, e2)
                        if overlap > 1e-3:
                            shared_edge_length += overlap

        # External perimeter of solid envelope = sum(solid_perimeters) - 2 * shared_edge_length
        sum_solid_perim = sum(c.perimeter_m for c in solid_components)
        external_perimeter = max(0.0, sum_solid_perim - 2.0 * shared_edge_length)

        # DPC length: equals external perimeter unless evidenced internal load-bearing walls exist
        dpc_length = external_perimeter

        status = FootprintStatus.CONFIRMED.value
        if is_partial:
            status = FootprintStatus.PARTIAL_MISSING_COMPONENTS.value
        elif is_provisional:
            status = FootprintStatus.PROVISIONAL.value

        return FootprintGeometryResult(
            components=components,
            component_areas=component_areas,
            union_area_m2=round(net_floor_area, 2),
            gross_floor_area_m2=round(net_floor_area, 2),
            dpm_area_m2=round(net_floor_area, 2),
            mesh_area_m2=round(net_floor_area, 2),
            external_perimeter_m=round(external_perimeter, 2),
            shared_edge_length_m=round(shared_edge_length, 2),
            dpc_length_m=round(dpc_length, 2),
            status=status,
            missing_components=missing_components,
            metadata={
                "total_solid_area_m2": round(total_solid_area, 2),
                "total_void_area_m2": round(total_void_area, 2),
                "num_solid_spaces": len(solid_components),
                "num_voids": len(void_components),
            },
        )


class MultiSpaceFootprintBuilder:
    """Builder for assembling architectural footprints from room/verandah components."""

    def __init__(self) -> None:
        self.components: List[SpaceComponent] = []

    def add_main_room(
        self,
        length_m: float,
        width_m: float,
        origin: Tuple[float, float] = (0.0, 0.0),
        label: str = "Main Room",
        source_page: Optional[int] = None,
        confidence: float = 1.0,
    ) -> "MultiSpaceFootprintBuilder":
        """Add primary rectangular room/building space."""
        x0, y0 = origin
        poly = [
            (x0, y0),
            (x0 + length_m, y0),
            (x0 + length_m, y0 + width_m),
            (x0, y0 + width_m),
        ]
        self.components.append(
            SpaceComponent(
                space_id=f"main_space_{len(self.components) + 1}",
                space_type=SpaceType.MAIN_BUILDING.value,
                label=label,
                polygon=poly,
                width_m=width_m,
                length_m=length_m,
                source_page=source_page,
                confidence=confidence,
            )
        )
        return self

    def add_verandah(
        self,
        length_m: Optional[float],
        width_m: Optional[float],
        adjacency: str = "front",
        reference_space_idx: int = 0,
        label: str = "Verandah",
        source_page: Optional[int] = None,
        confidence: float = 0.90,
    ) -> "MultiSpaceFootprintBuilder":
        """Add an adjacent verandah space with fail-closed missing dimension protection."""
        if width_m is None or width_m <= 0 or length_m is None or length_m <= 0:
            # Dimension is missing — FAIL CLOSED, do not guess
            missing: List[str] = []
            if width_m is None or width_m <= 0:
                missing.append("width")
            if length_m is None or length_m <= 0:
                missing.append("length")

            self.components.append(
                SpaceComponent(
                    space_id=f"verandah_{len(self.components) + 1}",
                    space_type=SpaceType.VERANDAH.value,
                    label=label,
                    polygon=[],
                    width_m=width_m,
                    length_m=length_m,
                    has_evidenced_dimensions=False,
                    missing_dimensions=missing,
                    spatial_adjacency=adjacency,
                    source_page=source_page,
                    confidence=confidence,
                )
            )
            return self

        # Place verandah adjacent to reference space if polygon exists
        poly: List[Tuple[float, float]] = []
        if 0 <= reference_space_idx < len(self.components):
            ref = self.components[reference_space_idx]
            if ref.polygon and len(ref.polygon) == 4:
                # Assuming axis-aligned rectangle [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                x0 = min(p[0] for p in ref.polygon)
                x1 = max(p[0] for p in ref.polygon)
                y0 = min(p[1] for p in ref.polygon)
                y1 = max(p[1] for p in ref.polygon)

                if adjacency in ("front", "south"):
                    poly = [(x0, y0 - width_m), (x0 + length_m, y0 - width_m), (x0 + length_m, y0), (x0, y0)]
                elif adjacency in ("rear", "north"):
                    poly = [(x0, y1), (x0 + length_m, y1), (x0 + length_m, y1 + width_m), (x0, y1 + width_m)]
                elif adjacency in ("left", "west"):
                    poly = [(x0 - width_m, y0), (x0, y0), (x0, y0 + length_m), (x0 - width_m, y0 + length_m)]
                elif adjacency in ("right", "east"):
                    poly = [(x1, y0), (x1 + width_m, y0), (x1 + width_m, y0 + length_m), (x1, y0 + length_m)]

        if not poly:
            # Fallback local placement
            poly = [(0.0, 0.0), (length_m, 0.0), (length_m, width_m), (0.0, width_m)]

        self.components.append(
            SpaceComponent(
                space_id=f"verandah_{len(self.components) + 1}",
                space_type=SpaceType.VERANDAH.value,
                label=label,
                polygon=poly,
                width_m=width_m,
                length_m=length_m,
                spatial_adjacency=adjacency,
                source_page=source_page,
                confidence=confidence,
            )
        )
        return self

    def add_polygon_space(
        self,
        polygon: List[Tuple[float, float]],
        space_type: str = SpaceType.MAIN_BUILDING.value,
        label: str = "Polygon Space",
        is_void: bool = False,
        source_page: Optional[int] = None,
        confidence: float = 1.0,
    ) -> "MultiSpaceFootprintBuilder":
        """Add arbitrary polygon space (e.g. L-shaped, courtyard void, or recess)."""
        self.components.append(
            SpaceComponent(
                space_id=f"space_{len(self.components) + 1}",
                space_type=space_type,
                label=label,
                polygon=polygon,
                is_void=is_void,
                source_page=source_page,
                confidence=confidence,
            )
        )
        return self

    def add_courtyard_void(
        self,
        length_m: float,
        width_m: float,
        origin: Tuple[float, float] = (0.0, 0.0),
        label: str = "Internal Courtyard Void",
        source_page: Optional[int] = None,
    ) -> "MultiSpaceFootprintBuilder":
        """Add an internal courtyard void to be subtracted from floor/bed quantities."""
        x0, y0 = origin
        poly = [
            (x0, y0),
            (x0 + length_m, y0),
            (x0 + length_m, y0 + width_m),
            (x0, y0 + width_m),
        ]
        self.components.append(
            SpaceComponent(
                space_id=f"void_{len(self.components) + 1}",
                space_type=SpaceType.COURTYARD_VOID.value,
                label=label,
                polygon=poly,
                width_m=width_m,
                length_m=length_m,
                is_void=True,
                source_page=source_page,
            )
        )
        return self

    def build(self) -> FootprintGeometryResult:
        """Evaluate and return complete compound footprint result."""
        return MultiSpaceFootprintEngine.evaluate(self.components)
