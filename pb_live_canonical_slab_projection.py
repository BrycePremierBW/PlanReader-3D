"""Canonical slab projection from the existing source-bound slab resolver.

This module does not detect slabs, bind annotations, derive boundaries, infer
thickness, or compute area. It preserves an already-RESOLVED ResolvedSlabEntity
as a reusable semantic object after re-checking that the exact authoritative
CandidateBoundary used by the resolver still matches its provenance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Mapping, Optional, Sequence

from pb_migration_contracts import stable_contract_id
from pb_slab_classification_geometry import (
    CandidateBoundary,
    ResolvedSlabEntity,
    SlabResolutionState,
    validate_boundary_polygon,
)


LIVE_CANONICAL_SLAB_SCHEMA_VERSION = "1.1.0"
LIVE_CANONICAL_SLAB_RESOLVED = "live_canonical_slab_resolved"
LIVE_CANONICAL_SLAB_UNAVAILABLE = "live_canonical_slab_unavailable"
LIVE_CANONICAL_SLAB_BOUNDARY_MISMATCH = "live_canonical_slab_boundary_mismatch"
LIVE_CANONICAL_SLAB_LINEAGE_UNAVAILABLE = "live_canonical_slab_lineage_unavailable"


@dataclass(frozen=True)
class LiveCanonicalSlabObject:
    canonical_slab_id: str
    physical_slab_id: str
    slab_id: str
    slab_type: str
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    source_page: int
    boundary_id: str
    polygon_m: tuple[tuple[float, float], ...]
    area_m2: float
    thickness_m: float
    reinforcement: tuple[Mapping[str, object], ...]
    provenance: Mapping[str, object]
    geometry_complete: bool = True
    thickness_complete: bool = True
    coordinate_space: str = "metres"
    schema_version: str = LIVE_CANONICAL_SLAB_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "canonical_slab_id": self.canonical_slab_id,
            "physical_slab_id": self.physical_slab_id,
            "slab_id": self.slab_id,
            "slab_type": self.slab_type,
            "document_id": self.document_id,
            "revision_id": self.revision_id,
            "source_sha256": self.source_sha256,
            "snapshot_id": self.snapshot_id,
            "source_page": self.source_page,
            "boundary_id": self.boundary_id,
            "polygon_m": [list(point) for point in self.polygon_m],
            "area_m2": self.area_m2,
            "thickness_m": self.thickness_m,
            "reinforcement": [dict(item) for item in self.reinforcement],
            "provenance": dict(self.provenance),
            "geometry_complete": self.geometry_complete,
            "thickness_complete": self.thickness_complete,
            "coordinate_space": self.coordinate_space,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class LiveCanonicalSlabProjection:
    object: Optional[LiveCanonicalSlabObject]
    reason_codes: tuple[str, ...]


def _canonical_polygon_identity(
    polygon: Sequence[Sequence[float]],
) -> tuple[tuple[float, float], ...]:
    """Canonicalize metric polygon geometry for physical identity only.

    Stored boundary ordering is preserved on the canonical object. Identity is
    invariant to start vertex and winding, with six-decimal metric precision.
    """
    points = tuple(
        (round(float(point[0]), 6), round(float(point[1]), 6))
        for point in polygon
    )
    if len(points) < 3:
        return ()
    variants: list[tuple[tuple[float, float], ...]] = []
    for start in range(len(points)):
        variants.append(
            tuple(points[(start + offset) % len(points)] for offset in range(len(points)))
        )
        variants.append(
            tuple(points[(start - offset) % len(points)] for offset in range(len(points)))
        )
    return min(variants)


def _verified_metric_slab_polygon_area(
    polygon: Sequence[Sequence[float]] | None,
) -> float | None:
    """Area from genuine metric boundary vertices, never from PDF page points.

    The original slab resolver has already authenticated metre units. This
    re-check prevents imported/replayed area claims from diverging from their
    source-owned metric footprint before the quantity boundary is reached.
    """
    if type(polygon) not in (tuple, list) or not validate_boundary_polygon(polygon):
        return None
    points = tuple((float(point[0]), float(point[1])) for point in polygon)
    twice_area = math.fsum(
        x0 * y1 - x1 * y0
        for (x0, y0), (x1, y1) in zip(points, (*points[1:], points[0]))
    )
    area = abs(twice_area) / 2.0
    return area if math.isfinite(area) and area > 0.0 else None


def project_resolved_slab_entity(
    *,
    slab: ResolvedSlabEntity,
    boundary: CandidateBoundary,
    document_id: str = "",
    revision_id: str = "",
    source_sha256: str = "",
    snapshot_id: str = "",
) -> LiveCanonicalSlabProjection:
    """Preserve one already-resolved slab without strengthening its authority."""

    if type(slab) is not ResolvedSlabEntity or type(boundary) is not CandidateBoundary:
        raise TypeError("slab and boundary must use the existing slab resolver contracts")

    lineage = tuple(
        str(value or "").strip()
        for value in (document_id, revision_id, source_sha256, snapshot_id)
    )
    if (
        not all(lineage)
        or len(lineage[2]) != 64
        or any(ch not in "0123456789abcdefABCDEF" for ch in lineage[2])
    ):
        return LiveCanonicalSlabProjection(
            object=None,
            reason_codes=(LIVE_CANONICAL_SLAB_LINEAGE_UNAVAILABLE,),
        )

    if (
        slab.resolution_state != SlabResolutionState.RESOLVED.value
        or slab.area_m2 is None
        or slab.thickness_mm is None
        or slab.boundary_polygon is None
    ):
        return LiveCanonicalSlabProjection(
            object=None,
            reason_codes=(LIVE_CANONICAL_SLAB_UNAVAILABLE,),
        )

    provenance = dict(slab.provenance or {})
    provenance_boundary_id = str(provenance.get("boundary_id") or "").strip()
    # These are real metre-space polygons. Source-reported area alone is not
    # sufficient when the same source receipt can be replayed with changed
    # coordinates or a stale value.
    metric_area = _verified_metric_slab_polygon_area(boundary.polygon)
    if (
        type(boundary.area_m2) is bool
        or type(slab.area_m2) is bool
        or metric_area is None
        or not math.isclose(
            metric_area, float(boundary.area_m2), rel_tol=1e-9, abs_tol=1e-6
        )
    ):
        return LiveCanonicalSlabProjection(
            object=None,
            reason_codes=(LIVE_CANONICAL_SLAB_BOUNDARY_MISMATCH,),
        )
    if (
        not provenance_boundary_id
        or provenance_boundary_id != str(boundary.boundary_id)
        or not boundary.units_authoritative
        or not validate_boundary_polygon(boundary.polygon)
        or not math.isfinite(float(boundary.area_m2))
        or float(boundary.area_m2) <= 0.0
        or not math.isclose(
            float(boundary.area_m2),
            float(slab.area_m2),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        or tuple(tuple(float(v) for v in point) for point in boundary.polygon)
        != tuple(tuple(float(v) for v in point) for point in slab.boundary_polygon)
    ):
        return LiveCanonicalSlabProjection(
            object=None,
            reason_codes=(LIVE_CANONICAL_SLAB_BOUNDARY_MISMATCH,),
        )

    thickness_mm = float(slab.thickness_mm)
    if not math.isfinite(thickness_mm) or thickness_mm <= 0.0:
        return LiveCanonicalSlabProjection(
            object=None,
            reason_codes=(LIVE_CANONICAL_SLAB_UNAVAILABLE,),
        )

    source_page_raw = provenance.get("annotation_source_page", boundary.source_page)
    try:
        source_page = int(source_page_raw)
    except (TypeError, ValueError):
        return LiveCanonicalSlabProjection(
            object=None,
            reason_codes=(LIVE_CANONICAL_SLAB_UNAVAILABLE,),
        )

    physical_polygon = _canonical_polygon_identity(slab.boundary_polygon)
    if not physical_polygon:
        return LiveCanonicalSlabProjection(
            object=None,
            reason_codes=(LIVE_CANONICAL_SLAB_BOUNDARY_MISMATCH,),
        )
    physical_slab_id = stable_contract_id(
        "physical_slab",
        {
            "document_id": lineage[0],
            "source_page": source_page,
            "polygon_m": physical_polygon,
        },
        digest_chars=32,
    )

    canonical = LiveCanonicalSlabObject(
        canonical_slab_id=physical_slab_id,
        physical_slab_id=physical_slab_id,
        slab_id=str(slab.slab_id),
        slab_type=str(slab.slab_type),
        document_id=lineage[0],
        revision_id=lineage[1],
        source_sha256=lineage[2].lower(),
        snapshot_id=lineage[3],
        source_page=source_page,
        boundary_id=str(boundary.boundary_id),
        polygon_m=tuple(
            (float(point[0]), float(point[1])) for point in slab.boundary_polygon
        ),
        area_m2=float(slab.area_m2),
        thickness_m=thickness_mm / 1000.0,
        reinforcement=tuple(asdict(item) for item in slab.reinforcement),
        provenance=provenance,
    )
    return LiveCanonicalSlabProjection(
        object=canonical,
        reason_codes=(LIVE_CANONICAL_SLAB_RESOLVED,),
    )


__all__ = [
    "LIVE_CANONICAL_SLAB_BOUNDARY_MISMATCH",
    "LIVE_CANONICAL_SLAB_LINEAGE_UNAVAILABLE",
    "LIVE_CANONICAL_SLAB_RESOLVED",
    "LIVE_CANONICAL_SLAB_SCHEMA_VERSION",
    "LIVE_CANONICAL_SLAB_UNAVAILABLE",
    "LiveCanonicalSlabObject",
    "LiveCanonicalSlabProjection",
    "project_resolved_slab_entity",
]
