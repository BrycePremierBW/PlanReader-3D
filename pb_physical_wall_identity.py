"""Shadow physical-wall candidate identity + publication equivalence.

``canonical_wall_candidate_id_v2`` is CANDIDATE IDENTITY only. It intentionally
preserves U1 provenance, so the same physical path with duplicated native
primitive IDs receives different V2 IDs. Quantity publication therefore must
not treat ``different V2 ID ⇒ different physical wall``.

Equivalence classification applies only to pairs that could plausibly be the
same physical wall (``physical_wall_pair_is_identity_candidate``). Two
candidates with no shared primitive, no duplicate path, no geometric contact,
and no plausible shared wall body are not identity competitors: they carry NO
equivalence relation and each publishes on its own. Treating "no possibility of
SAME" as ambiguity would let unrelated walls link into one contest and suppress
every representative in the scope.

Physical equivalence is a separate fail-closed classification:

- SAME_PHYSICAL_WALL — positive proof (same path + same U1 ancestry, or
  ancestor/descendant coverage identity)
- DISTINCT_PHYSICAL_WALLS — positive proof only (different viewport;
  authoritative different levels; same ancestry with proven disjoint spans)
- AMBIGUOUS_PHYSICAL_EQUIVALENCE — neither proven (including identical path
  with different primitive IDs and no explicit duplication proof; different
  path with independent provenance)

Geometry equality alone is never enough when provenance differs.
No confidence, nearest, first, or epsilon merge.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence

from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_contracts import WallCandidate
from pb_wall_room_topology_junction_classifier import (
    DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG,
)
from pb_wall_room_topology_stage_a import DEFAULT_GAP_SNAP_TOLERANCE_PT
from pb_wall_room_topology_wall_identity_v2 import (
    _chain_source_primitive_ids,
    _path_from_edges,
    canonical_path_fingerprint,
    canonical_wall_candidate_id_v2_from_components,
)

PHYSICAL_WALL_IDENTITY_SCHEMA_VERSION = "1.0.0"
PHYSICAL_WALL_IDENTITY_METHOD = "physical_wall_identity_v2_sidecar"
PHYSICAL_WALL_EQUIVALENCE_SCHEMA_VERSION = "1.2.0"


class PhysicalEquivalenceClass(str, Enum):
    SAME_PHYSICAL_WALL = "same_physical_wall"
    DISTINCT_PHYSICAL_WALLS = "distinct_physical_walls"
    AMBIGUOUS_PHYSICAL_EQUIVALENCE = "ambiguous_physical_equivalence"


@dataclass(frozen=True)
class PhysicalWallIdentity:
    """Immutable shadow candidate identity for one assembled wall."""

    wall_candidate_id: str
    viewport_id: str
    candidate_identity_id: Optional[str]
    path_fingerprint: Optional[tuple[tuple[float, float], ...]]
    source_primitive_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    status: EvidenceResolutionStatus
    blocking_reasons: tuple[str, ...] = ()
    comparison_mode: str = "v2_path"
    level_id: Optional[str] = None
    schema_version: str = PHYSICAL_WALL_IDENTITY_SCHEMA_VERSION

    @property
    def physical_identity_id(self) -> Optional[str]:
        """Back-compat alias: candidate V2 id, not publication equivalence."""
        return self.candidate_identity_id

    @property
    def usable(self) -> bool:
        return (
            self.status == EvidenceResolutionStatus.CORROBORATED
            and self.candidate_identity_id is not None
            and self.path_fingerprint is not None
            and not self.blocking_reasons
        )


@dataclass(frozen=True)
class CandidatePairAudit:
    """Diagnostic census of which pairs entered equivalence classification.

    Provenance only. Nothing here feeds an authority decision, and there is
    no caller-controlled flag that can alter classification.
    """

    total_pairs: int = 0
    considered_pairs: int = 0
    excluded_pairs: int = 0
    exclusion_reason_counts: Mapping[str, int] = field(default_factory=dict)
    trusted_override_pairs_restored: int = 0
    trusted_override_pairs_rejected: int = 0
    trusted_override_rejection_reason_counts: Mapping[str, int] = field(
        default_factory=dict
    )
    verified_points_per_mm: Optional[float] = None
    candidate_wall_body_band_pt: Optional[float] = None


@dataclass(frozen=True)
class PhysicalWallEquivalenceResolution:
    """Fail-closed publication equivalence over competing wall candidates."""

    scope_viewport_id: str
    representative_wall_ids: tuple[str, ...]
    abstained_wall_ids: tuple[str, ...]
    equivalence_groups: tuple[tuple[str, ...], ...]
    ambiguous_wall_ids: tuple[str, ...]
    same_wall_ids: tuple[str, ...]
    pair_classifications: tuple[tuple[str, str, str], ...]
    blocking_reasons_by_wall_id: Mapping[str, tuple[str, ...]]
    schema_version: str = PHYSICAL_WALL_EQUIVALENCE_SCHEMA_VERSION
    candidate_pair_audit: "CandidatePairAudit" = field(
        default_factory=lambda: CandidatePairAudit()
    )

    def blockers_for(self, wall_candidate_id: str) -> tuple[str, ...]:
        return tuple(self.blocking_reasons_by_wall_id.get(wall_candidate_id, ()))


def _wall_edge_ids(wall: WallCandidate) -> tuple[str, ...]:
    ids = list(wall.face_a_segment_ids)
    if wall.face_b_segment_ids:
        ids.extend(wall.face_b_segment_ids)
    return tuple(dict.fromkeys(ids))


def _edges_have_coordinates(
    edge_ids: Sequence[str],
    edges_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    for edge_id in edge_ids:
        edge = edges_by_id.get(edge_id) or {}
        try:
            float(edge["x1"])
            float(edge["y1"])
            float(edge["x2"])
            float(edge["y2"])
        except (KeyError, TypeError, ValueError):
            return False
    return True


def _simple_path_walkable(
    edge_ids: Sequence[str],
    edges_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    if len(edge_ids) <= 1:
        return True
    raw_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for edge_id in edge_ids:
        edge = edges_by_id.get(edge_id) or {}
        try:
            raw_segments.append(
                (
                    (float(edge["x1"]), float(edge["y1"])),
                    (float(edge["x2"]), float(edge["y2"])),
                )
            )
        except (KeyError, TypeError, ValueError):
            return False
    adjacency: dict[tuple[float, float], list[int]] = {}
    for idx, (a, b) in enumerate(raw_segments):
        key_a = (round(a[0], 6), round(a[1], 6))
        key_b = (round(b[0], 6), round(b[1], 6))
        adjacency.setdefault(key_a, []).append(idx)
        adjacency.setdefault(key_b, []).append(idx)
    endpoints = [point for point, incident in adjacency.items() if len(incident) == 1]
    return len(endpoints) == 2


def _abstain(
    *,
    wall: WallCandidate,
    edge_ids: tuple[str, ...],
    source_primitive_ids: tuple[str, ...],
    reasons: tuple[str, ...],
    path_fingerprint: Optional[tuple[tuple[float, float], ...]] = None,
) -> PhysicalWallIdentity:
    return PhysicalWallIdentity(
        wall_candidate_id=wall.candidate_id,
        viewport_id=wall.viewport_id,
        candidate_identity_id=None,
        path_fingerprint=path_fingerprint,
        source_primitive_ids=source_primitive_ids,
        edge_ids=edge_ids,
        status=EvidenceResolutionStatus.ABSTAINED,
        blocking_reasons=reasons,
        comparison_mode="abstained",
        level_id=str(wall.level_id or "").strip() or None,
    )


def resolve_physical_wall_identity(
    *,
    wall: WallCandidate,
    edge_ids: Optional[Sequence[str]] = None,
    edges_by_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> PhysicalWallIdentity:
    """Resolve one shadow candidate identity where V2 prerequisites exist."""
    resolved_edge_ids = tuple(edge_ids) if edge_ids is not None else _wall_edge_ids(wall)
    lineage = _chain_source_primitive_ids(resolved_edge_ids, edges_by_id or {})
    if not resolved_edge_ids or edges_by_id is None:
        return _abstain(
            wall=wall,
            edge_ids=resolved_edge_ids,
            source_primitive_ids=lineage,
            reasons=("physical_identity_path_inputs_unavailable",),
        )
    missing = tuple(edge_id for edge_id in resolved_edge_ids if edge_id not in edges_by_id)
    if missing:
        return _abstain(
            wall=wall,
            edge_ids=resolved_edge_ids,
            source_primitive_ids=lineage,
            reasons=("physical_identity_edge_missing",),
        )
    if not _edges_have_coordinates(resolved_edge_ids, edges_by_id):
        return _abstain(
            wall=wall,
            edge_ids=resolved_edge_ids,
            source_primitive_ids=lineage,
            reasons=("physical_identity_edge_geometry_unavailable",),
        )
    if len(wall.centerline_pts) < 2:
        return _abstain(
            wall=wall,
            edge_ids=resolved_edge_ids,
            source_primitive_ids=lineage,
            reasons=("physical_identity_centerline_unresolved",),
        )
    p1 = wall.centerline_pts[0]
    p2 = wall.centerline_pts[-1]
    reconstructed = _path_from_edges(resolved_edge_ids, edges_by_id, p1, p2)
    if len(resolved_edge_ids) > 1 and not _simple_path_walkable(resolved_edge_ids, edges_by_id):
        path = tuple(wall.centerline_pts)
        comparison_mode = "centerline_path_with_lineage"
    else:
        path = reconstructed
        comparison_mode = "v2_path"
    path_fingerprint = canonical_path_fingerprint(path)
    candidate_id = canonical_wall_candidate_id_v2_from_components(
        wall.viewport_id,
        canonical_path_fingerprint(reconstructed),
        lineage,
    )
    return PhysicalWallIdentity(
        wall_candidate_id=wall.candidate_id,
        viewport_id=wall.viewport_id,
        candidate_identity_id=candidate_id,
        path_fingerprint=path_fingerprint,
        source_primitive_ids=lineage,
        edge_ids=resolved_edge_ids,
        status=EvidenceResolutionStatus.CORROBORATED,
        comparison_mode=comparison_mode,
        level_id=str(wall.level_id or "").strip() or None,
    )


class DuplicateW4CandidateAddress(ValueError):
    """Two original W4 rows cannot own one keyed physical-identity address."""


def collect_physical_wall_identities(
    walls: Sequence[WallCandidate],
    graph: Mapping[str, Any],
) -> dict[str, PhysicalWallIdentity]:
    """Build sidecar candidate identities at the W4/graph layer.

    Different W4 candidates may share an approximate path fingerprint. Never
    turn that collision into an arbitrary last-writer physical identity.
    """
    candidate_ids = [wall.candidate_id for wall in walls]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise DuplicateW4CandidateAddress(
            "duplicate W4 candidate id before physical identity collection"
        )
    edges_by_id = {
        str(edge["id"]): edge
        for edge in (graph.get("edges") or [])
        if edge.get("id") and not edge.get("_removed")
    }
    return {
        wall.candidate_id: resolve_physical_wall_identity(
            wall=wall,
            edge_ids=_wall_edge_ids(wall),
            edges_by_id=edges_by_id,
        )
        for wall in walls
    }


# Candidate-gate tolerance policy.
#
# These are reused from the repository's existing geometry authorities rather
# than invented here, so the candidate gate answers real PDF geometric
# relationships at the same resolution as the producers that feed it.
#
# - lateral/contact and overlap: Stage-A gap snap tolerance
# - orientation: W3 junction-classifier collinear angle tolerance
_EQUIVALENCE_LATERAL_TOL_PT = DEFAULT_GAP_SNAP_TOLERANCE_PT
_EQUIVALENCE_ANGLE_TOL_DEG = DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG

# Degenerate-length guard only. Never used as a geometric relationship test.
_EQUIVALENCE_DEGENERATE_TOL = 1e-9

# Conservative maximum plausible wall-body separation, in millimetres.
#
# The candidate gate must err toward INCLUDING a possible same-wall pair:
# wrong exclusion can publish two faces of one wall and double-count, while
# wrong inclusion only causes safe abstention.  This therefore covers an
# unusually thick wall body plus both finishes, not a typical partition.
MAX_PLAUSIBLE_WALL_BODY_MM = 700.0

# There is intentionally NO unscaled source-space separation cutoff.
# A point distance cannot be converted to a physical wall thickness without
# authoritative scale.  Using a fixed source-space band could publish the two
# faces of a 450-600mm wall on a larger-scale detail.  Therefore parallel,
# longitudinally-overlapping pairs stay in contest until producer-owned scale
# is corroborated; orientation/no-overlap filtering still removes unrelated
# pairs without needing physical units.
# Exclusion reason codes (diagnostic/provenance only).
PAIR_EXCLUDED_ORIENTATION_INCOMPATIBLE = "pair_excluded_orientation_incompatible"
PAIR_EXCLUDED_NO_LONGITUDINAL_OVERLAP = "pair_excluded_no_longitudinal_overlap"
PAIR_EXCLUDED_SEPARATION_BEYOND_BAND = "pair_excluded_separation_beyond_wall_body_band"


@dataclass(frozen=True)
class _PhysicalWallPairFeatures:
    primitive_set: frozenset[str]
    path: tuple[tuple[float, float], ...]
    segments: tuple[tuple[float, float, float, float], ...]
    segment_units: tuple[Optional[tuple[float, float]], ...]
    axis_interval: Optional[tuple[str, float, float]]
    level_id: str
    single_segment_unit: Optional[tuple[float, float]]
    single_segment_bbox: Optional[tuple[float, float, float, float]]


def _physical_wall_pair_features(
    identity: PhysicalWallIdentity,
) -> _PhysicalWallPairFeatures:
    path = tuple(identity.path_fingerprint or ())
    segments = _segments(path)
    segment_units = tuple(_unit(segment) for segment in segments)
    single = segments[0] if len(segments) == 1 else None
    return _PhysicalWallPairFeatures(
        primitive_set=frozenset(identity.source_primitive_ids),
        path=path,
        segments=segments,
        segment_units=segment_units,
        axis_interval=_axis_interval(path),
        level_id=str(identity.level_id or "").strip(),
        single_segment_unit=None if single is None else segment_units[0],
        single_segment_bbox=(
            None
            if single is None
            else (
                min(single[0], single[2]),
                min(single[1], single[3]),
                max(single[0], single[2]),
                max(single[1], single[3]),
            )
        ),
    )


def max_plausible_wall_body_separation_pt(
    points_per_mm: Optional[float] = None,
) -> Optional[float]:
    """Scale-backed maximum separation for a plausible shared wall body.

    No source-space fallback is returned. Without producer-owned physical
    scale, absolute PDF-point separation cannot safely prove that two
    overlapping parallel paths are different physical walls.
    """
    if (
        points_per_mm is not None
        and math.isfinite(points_per_mm)
        and points_per_mm > 0.0
    ):
        return MAX_PLAUSIBLE_WALL_BODY_MM * float(points_per_mm)
    return None


def _point_segment_distance(
    px: float, py: float, seg: tuple[float, float, float, float]
) -> float:
    ax, ay, bx, by = seg
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= _EQUIVALENCE_DEGENERATE_TOL:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _segments_meet_within(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    tolerance: float,
) -> bool:
    """True when two segments cross or come within ``tolerance``.

    Contact is evaluated at the repository's snap tolerance, so drafting
    noise and split vertices do not change whether two candidate paths are
    considered to meet.  Proximity here only admits a pair to comparison; it
    never asserts that the pair is the same wall.
    """
    ax, ay, bx, by = left
    cx, cy, dx, dy = right

    # Conservative broad phase: if the axis-aligned segment bounds remain
    # disjoint even after expanding by the exact existing contact tolerance,
    # the segments cannot cross or come within that tolerance. Non-finite
    # inputs deliberately fall through to the historical predicate.
    finite_values = (ax, ay, bx, by, cx, cy, dx, dy, tolerance)
    if all(math.isfinite(value) for value in finite_values):
        if (
            max(ax, bx) + tolerance < min(cx, dx)
            or max(cx, dx) + tolerance < min(ax, bx)
            or max(ay, by) + tolerance < min(cy, dy)
            or max(cy, dy) + tolerance < min(ay, by)
        ):
            return False

    def orient(x1, y1, x2, y2, x3, y3):
        return (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)

    o1 = orient(ax, ay, bx, by, cx, cy)
    o2 = orient(ax, ay, bx, by, dx, dy)
    o3 = orient(cx, cy, dx, dy, ax, ay)
    o4 = orient(cx, cy, dx, dy, bx, by)
    if ((o1 > 0.0) != (o2 > 0.0)) and ((o3 > 0.0) != (o4 > 0.0)):
        return True

    return min(
        _point_segment_distance(cx, cy, left),
        _point_segment_distance(dx, dy, left),
        _point_segment_distance(ax, ay, right),
        _point_segment_distance(bx, by, right),
    ) <= tolerance


def _axis_interval(
    path: Sequence[tuple[float, float]],
) -> Optional[tuple[str, float, float]]:
    if len(path) < 2:
        return None
    dx = path[-1][0] - path[0][0]
    dy = path[-1][1] - path[0][1]
    if abs(dx) >= abs(dy):
        xs = [point[0] for point in path]
        return ("h", min(xs), max(xs))
    ys = [point[1] for point in path]
    return ("v", min(ys), max(ys))


def _intervals_overlap(left: tuple[str, float, float], right: tuple[str, float, float]) -> bool:
    if left[0] != right[0]:
        return False
    return not (left[2] <= right[1] or right[2] <= left[1])


def _intervals_disjoint(left: tuple[str, float, float], right: tuple[str, float, float]) -> bool:
    if left[0] != right[0]:
        return True
    return left[2] <= right[1] or right[2] <= left[1]


def _ancestry_equal(left: Sequence[str], right: Sequence[str]) -> bool:
    return bool(left) and set(left) == set(right)


def _ancestry_coverage_identical(left: Sequence[str], right: Sequence[str]) -> bool:
    """Ancestor/descendant reconstruction with identical coverage.

    Non-empty sets where one is a subset of the other and both describe the
    same complete path are treated as the same physical coverage only when
    the sets are equal. Strict subset without equal coverage stays ambiguous
    (no silent contained-subspan merge).
    """
    return _ancestry_equal(left, right)


def _path_bbox(
    path: Sequence[tuple[float, float]],
) -> Optional[tuple[float, float, float, float]]:
    if len(path) < 2:
        return None
    xs = [float(point[0]) for point in path]
    ys = [float(point[1]) for point in path]
    return min(xs), min(ys), max(xs), max(ys)


def _segments(
    path: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float, float, float], ...]:
    points = [(float(p[0]), float(p[1])) for p in path]
    return tuple(
        (a[0], a[1], b[0], b[1])
        for a, b in zip(points, points[1:])
        if math.hypot(b[0] - a[0], b[1] - a[1]) > _EQUIVALENCE_DEGENERATE_TOL
    )


def _unit(seg: tuple[float, float, float, float]) -> Optional[tuple[float, float]]:
    dx, dy = seg[2] - seg[0], seg[3] - seg[1]
    length = math.hypot(dx, dy)
    if length <= _EQUIVALENCE_DEGENERATE_TOL:
        return None
    ux, uy = dx / length, dy / length
    if ux < 0.0 or (ux == 0.0 and uy < 0.0):
        ux, uy = -ux, -uy
    return ux, uy


def _paths_share_both_endpoints(
    left: Sequence[tuple[float, float]],
    right: Sequence[tuple[float, float]],
    tolerance: float,
) -> bool:
    """True when two reconstructed paths have the same endpoint pair.

    Sharing both endpoints is materially different from an ordinary T/L/X
    junction, which shares at most one contact point.  Two paths spanning the
    same endpoint pair but taking different interior routes remain plausible
    competing representations of one physical wall and must fail closed.
    """

    if len(left) < 2 or len(right) < 2:
        return False

    def near(a: tuple[float, float], b: tuple[float, float]) -> bool:
        return math.hypot(
            float(a[0]) - float(b[0]),
            float(a[1]) - float(b[1]),
        ) <= tolerance

    return (
        near(left[0], right[0]) and near(left[-1], right[-1])
    ) or (
        near(left[0], right[-1]) and near(left[-1], right[0])
    )


def _segments_meet_as_same_wall_candidates(
    left_segs: Sequence[tuple[float, float, float, float]],
    right_segs: Sequence[tuple[float, float, float, float]],
    tolerance: float,
) -> bool:
    if not left_segs or not right_segs:
        return False
    for a in left_segs:
        for b in right_segs:
            if (
                _parallel_overlap_separation(
                    a,
                    b,
                    angle_tolerance_deg=_EQUIVALENCE_ANGLE_TOL_DEG,
                )
                is None
            ):
                continue
            if _segments_meet_within(a, b, tolerance):
                return True
    return False


def _paths_meet_as_same_wall_candidates(
    left: Sequence[tuple[float, float]],
    right: Sequence[tuple[float, float]],
    tolerance: float,
) -> bool:
    """True only for orientation-compatible contact.

    T/L/X junctions are real wall-network contacts but are not plausible
    duplicate faces/representations of one physical wall. Contact therefore
    enters the equivalence contest only when at least one touching segment
    pair is parallel within the repository's collinear-angle tolerance.
    """
    return _segments_meet_as_same_wall_candidates(
        _segments(left),
        _segments(right),
        tolerance,
    )


def _parallel_overlap_separation(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    *,
    angle_tolerance_deg: float,
) -> Optional[tuple[float, float]]:
    """Longitudinal overlap and perpendicular separation of a parallel pair.

    Orientation is compared at the W3 collinear angle tolerance, so drafting
    skew does not hide a genuine face pair.  Returns ``None`` when the pair is
    not parallel within tolerance.
    """
    lu, ru = _unit(left), _unit(right)
    if lu is None or ru is None:
        return None
    dot = max(-1.0, min(1.0, abs(lu[0] * ru[0] + lu[1] * ru[1])))
    if math.degrees(math.acos(dot)) > angle_tolerance_deg:
        return None

    axis = lu
    normal = (-axis[1], axis[0])

    def interval(seg):
        values = sorted(
            (
                seg[0] * axis[0] + seg[1] * axis[1],
                seg[2] * axis[0] + seg[3] * axis[1],
            )
        )
        return values[0], values[1]

    liv, riv = interval(left), interval(right)
    overlap = min(liv[1], riv[1]) - max(liv[0], riv[0])

    # Perpendicular offset is measured at the overlapping run rather than at
    # one endpoint, so a slightly skewed face pair is still measured across
    # the part they actually share.
    mid = (max(liv[0], riv[0]) + min(liv[1], riv[1])) / 2.0

    def offset_at(seg):
        a_long = seg[0] * axis[0] + seg[1] * axis[1]
        b_long = seg[2] * axis[0] + seg[3] * axis[1]
        a_perp = seg[0] * normal[0] + seg[1] * normal[1]
        b_perp = seg[2] * normal[0] + seg[3] * normal[1]
        span = b_long - a_long
        if abs(span) <= _EQUIVALENCE_DEGENERATE_TOL:
            return a_perp
        t = max(0.0, min(1.0, (mid - a_long) / span))
        return a_perp + t * (b_perp - a_perp)

    separation = abs(offset_at(right) - offset_at(left))
    return overlap, separation




def _parallel_longitudinal_overlap_with_units(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    left_unit: Optional[tuple[float, float]],
    right_unit: Optional[tuple[float, float]],
    *,
    angle_tolerance_deg: float,
) -> Optional[float]:
    """Cached-unit form of the no-scale parallel-overlap predicate.

    The resolver derives immutable segment units once per wall identity and
    reuses them across pair comparisons.  The historical acos angle decision
    is intentionally preserved exactly, including tolerance-boundary behavior.
    """
    lu, ru = left_unit, right_unit
    if lu is None or ru is None:
        return None
    dot = max(-1.0, min(1.0, abs(lu[0] * ru[0] + lu[1] * ru[1])))
    if math.degrees(math.acos(dot)) > angle_tolerance_deg:
        return None
    axis = lu
    left_first = left[0] * axis[0] + left[1] * axis[1]
    left_second = left[2] * axis[0] + left[3] * axis[1]
    right_first = right[0] * axis[0] + right[1] * axis[1]
    right_second = right[2] * axis[0] + right[3] * axis[1]
    left_min, left_max = (
        (left_first, left_second)
        if left_first <= left_second
        else (left_second, left_first)
    )
    right_min, right_max = (
        (right_first, right_second)
        if right_first <= right_second
        else (right_second, right_first)
    )
    return min(left_max, right_max) - max(left_min, right_min)


def _parallel_longitudinal_overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    *,
    angle_tolerance_deg: float,
) -> Optional[float]:
    """Return longitudinal overlap for an orientation-compatible segment pair.

    This compatibility wrapper preserves the historical standalone API.  Dense
    resolver paths use the cached-unit form above.
    """
    return _parallel_longitudinal_overlap_with_units(
        left,
        right,
        _unit(left),
        _unit(right),
        angle_tolerance_deg=angle_tolerance_deg,
    )


def _single_segment_pair_identity_candidacy(
    left_features: _PhysicalWallPairFeatures,
    right_features: _PhysicalWallPairFeatures,
    *,
    points_per_mm: Optional[float],
) -> tuple[bool, Optional[str]]:
    """Exact candidacy fast-path for two straight one-segment identities.

    The historical predicate recomputed units, endpoint distances and projected
    intervals for every pair.  On dense CAD sheets that means millions of
    repeated calculations.  This path reuses immutable per-identity direction
    and bounds, but preserves the same orientation/contact/overlap/separation
    decisions and the same exclusion reason codes.
    """
    left = left_features.segments[0]
    right = right_features.segments[0]
    lu = left_features.single_segment_unit
    ru = right_features.single_segment_unit
    if lu is None or ru is None:
        return True, None

    dot = max(-1.0, min(1.0, abs(lu[0] * ru[0] + lu[1] * ru[1])))
    if math.degrees(math.acos(dot)) > _EQUIVALENCE_ANGLE_TOL_DEG:
        return False, PAIR_EXCLUDED_ORIENTATION_INCOMPATIBLE

    axis = lu
    left_values = sorted(
        (
            left[0] * axis[0] + left[1] * axis[1],
            left[2] * axis[0] + left[3] * axis[1],
        )
    )
    right_values = sorted(
        (
            right[0] * axis[0] + right[1] * axis[1],
            right[2] * axis[0] + right[3] * axis[1],
        )
    )
    overlap = min(left_values[1], right_values[1]) - max(
        left_values[0], right_values[0]
    )

    left_bbox = left_features.single_segment_bbox
    right_bbox = right_features.single_segment_bbox
    can_meet = True
    if left_bbox is not None and right_bbox is not None:
        tol = _EQUIVALENCE_LATERAL_TOL_PT
        can_meet = not (
            left_bbox[2] + tol < right_bbox[0]
            or right_bbox[2] + tol < left_bbox[0]
            or left_bbox[3] + tol < right_bbox[1]
            or right_bbox[3] + tol < left_bbox[1]
        )

    band = max_plausible_wall_body_separation_pt(points_per_mm)
    if band is None:
        # Without physical scale, any positive longitudinal overlap already
        # keeps the pair in contest regardless of lateral separation.  Avoid
        # the much more expensive segment-distance calculation unless overlap
        # itself cannot admit the pair and near-contact is the only remaining
        # route to candidacy.
        if overlap > _EQUIVALENCE_LATERAL_TOL_PT:
            return True, None
        if can_meet and _segments_meet_within(
            left, right, _EQUIVALENCE_LATERAL_TOL_PT
        ):
            return True, None
        return False, PAIR_EXCLUDED_NO_LONGITUDINAL_OVERLAP

    if can_meet and _segments_meet_within(
        left, right, _EQUIVALENCE_LATERAL_TOL_PT
    ):
        return True, None
    if overlap <= _EQUIVALENCE_LATERAL_TOL_PT:
        return False, PAIR_EXCLUDED_NO_LONGITUDINAL_OVERLAP

    normal = (-axis[1], axis[0])
    mid = (
        max(left_values[0], right_values[0])
        + min(left_values[1], right_values[1])
    ) / 2.0

    def offset_at(seg):
        a_long = seg[0] * axis[0] + seg[1] * axis[1]
        b_long = seg[2] * axis[0] + seg[3] * axis[1]
        a_perp = seg[0] * normal[0] + seg[1] * normal[1]
        b_perp = seg[2] * normal[0] + seg[3] * normal[1]
        span = b_long - a_long
        if abs(span) <= _EQUIVALENCE_DEGENERATE_TOL:
            return a_perp
        t = max(0.0, min(1.0, (mid - a_long) / span))
        return a_perp + t * (b_perp - a_perp)

    separation = abs(offset_at(right) - offset_at(left))
    if separation <= band:
        return True, None
    return False, PAIR_EXCLUDED_SEPARATION_BEYOND_BAND


def _physical_wall_pair_identity_candidacy_with_features(
    left: PhysicalWallIdentity,
    right: PhysicalWallIdentity,
    left_features: _PhysicalWallPairFeatures,
    right_features: _PhysicalWallPairFeatures,
    *,
    points_per_mm: Optional[float] = None,
) -> tuple[bool, Optional[str]]:
    if not left.usable or not right.usable:
        return True, None
    if not left_features.primitive_set.isdisjoint(right_features.primitive_set):
        return True, None
    if (
        left.path_fingerprint is not None
        and left.path_fingerprint == right.path_fingerprint
    ):
        return True, None

    if left.viewport_id != right.viewport_id or (
        bool(left_features.level_id)
        and bool(right_features.level_id)
        and left_features.level_id != right_features.level_id
    ):
        return True, None

    if len(left_features.path) < 2 or len(right_features.path) < 2:
        return True, None

    if len(left_features.segments) == 1 and len(right_features.segments) == 1:
        # Preserve the legacy both-endpoints safety rule.  Use an axis-aligned
        # prefilter first: Euclidean distance <= tol necessarily implies both
        # coordinate deltas <= tol, so this can only skip impossible matches.
        tol = _EQUIVALENCE_LATERAL_TOL_PT
        lp0, lp1 = left_features.path[0], left_features.path[-1]
        rp0, rp1 = right_features.path[0], right_features.path[-1]
        direct_possible = (
            abs(lp0[0] - rp0[0]) <= tol
            and abs(lp0[1] - rp0[1]) <= tol
            and abs(lp1[0] - rp1[0]) <= tol
            and abs(lp1[1] - rp1[1]) <= tol
        )
        reverse_possible = (
            abs(lp0[0] - rp1[0]) <= tol
            and abs(lp0[1] - rp1[1]) <= tol
            and abs(lp1[0] - rp0[0]) <= tol
            and abs(lp1[1] - rp0[1]) <= tol
        )
        if (direct_possible or reverse_possible) and _paths_share_both_endpoints(
            left_features.path,
            right_features.path,
            tol,
        ):
            return True, None
        return _single_segment_pair_identity_candidacy(
            left_features,
            right_features,
            points_per_mm=points_per_mm,
        )

    if _paths_share_both_endpoints(
        left_features.path,
        right_features.path,
        _EQUIVALENCE_LATERAL_TOL_PT,
    ):
        return True, None

    # The historical implementation made two complete nested segment-pair
    # passes: first to find orientation-compatible contact, then again to
    # derive parallel overlap/separation. Both passes call the same expensive
    # _parallel_overlap_separation predicate. Compute that relation once per
    # segment pair and apply the unchanged contact and overlap gates in one
    # pass. This changes no candidate decision or exclusion reason.
    band = max_plausible_wall_body_separation_pt(points_per_mm)
    saw_parallel = False

    if band is None:
        # No physical scale means perpendicular separation has no authority to
        # exclude a pair.  Longitudinal overlap can therefore decide candidacy
        # before any point-to-segment distance work.  Near-contact remains the
        # exact fallback for parallel segments whose intervals do not overlap.
        for left_index, a in enumerate(left_features.segments):
            left_unit = left_features.segment_units[left_index]
            for right_index, b in enumerate(right_features.segments):
                overlap = _parallel_longitudinal_overlap_with_units(
                    a,
                    b,
                    left_unit,
                    right_features.segment_units[right_index],
                    angle_tolerance_deg=_EQUIVALENCE_ANGLE_TOL_DEG,
                )
                if overlap is None:
                    continue
                saw_parallel = True
                if overlap > _EQUIVALENCE_LATERAL_TOL_PT:
                    return True, None
                if _segments_meet_within(
                    a, b, _EQUIVALENCE_LATERAL_TOL_PT
                ):
                    return True, None
        if not saw_parallel:
            return False, PAIR_EXCLUDED_ORIENTATION_INCOMPATIBLE
        return False, PAIR_EXCLUDED_NO_LONGITUDINAL_OVERLAP

    saw_overlap = False
    for a in left_features.segments:
        for b in right_features.segments:
            relation = _parallel_overlap_separation(
                a, b, angle_tolerance_deg=_EQUIVALENCE_ANGLE_TOL_DEG
            )
            if relation is None:
                continue
            saw_parallel = True
            if _segments_meet_within(a, b, _EQUIVALENCE_LATERAL_TOL_PT):
                return True, None
            overlap, separation = relation
            if overlap <= _EQUIVALENCE_LATERAL_TOL_PT:
                continue
            saw_overlap = True
            if separation <= band:
                return True, None

    if not saw_parallel:
        return False, PAIR_EXCLUDED_ORIENTATION_INCOMPATIBLE
    if not saw_overlap:
        return False, PAIR_EXCLUDED_NO_LONGITUDINAL_OVERLAP
    return False, PAIR_EXCLUDED_SEPARATION_BEYOND_BAND


def physical_wall_pair_identity_candidacy(
    left: PhysicalWallIdentity,
    right: PhysicalWallIdentity,
    *,
    points_per_mm: Optional[float] = None,
) -> tuple[bool, Optional[str]]:
    """Could this pair plausibly represent the same physical wall?

    This public form preserves the historical standalone behavior. The
    resolver uses the same predicate with one immutable feature record per
    candidate so pairwise audits do not repeatedly rebuild sets and segments.
    """
    return _physical_wall_pair_identity_candidacy_with_features(
        left,
        right,
        _physical_wall_pair_features(left),
        _physical_wall_pair_features(right),
        points_per_mm=points_per_mm,
    )

def physical_wall_pair_is_identity_candidate(
    left: PhysicalWallIdentity,
    right: PhysicalWallIdentity,
    *,
    points_per_mm: Optional[float] = None,
) -> bool:
    """Boolean form of :func:`physical_wall_pair_identity_candidacy`."""
    eligible, _reason = physical_wall_pair_identity_candidacy(
        left, right, points_per_mm=points_per_mm
    )
    return eligible


def _classify_physical_wall_pair_with_features(
    left: PhysicalWallIdentity,
    right: PhysicalWallIdentity,
    left_features: _PhysicalWallPairFeatures,
    right_features: _PhysicalWallPairFeatures,
) -> PhysicalEquivalenceClass:
    if not left.usable or not right.usable:
        return PhysicalEquivalenceClass.AMBIGUOUS_PHYSICAL_EQUIVALENCE

    cross_scope = (left.viewport_id != right.viewport_id) or (
        bool(left_features.level_id)
        and bool(right_features.level_id)
        and left_features.level_id != right_features.level_id
    )

    same_path = (
        left.path_fingerprint is not None
        and left.path_fingerprint == right.path_fingerprint
    )
    equal_ancestry = bool(left.source_primitive_ids) and (
        left_features.primitive_set == right_features.primitive_set
    )
    coverage_identical = equal_ancestry
    shared = left_features.primitive_set & right_features.primitive_set

    if same_path and (equal_ancestry or coverage_identical) and not cross_scope:
        return PhysicalEquivalenceClass.SAME_PHYSICAL_WALL

    if same_path and not equal_ancestry:
        return PhysicalEquivalenceClass.AMBIGUOUS_PHYSICAL_EQUIVALENCE

    left_iv = left_features.axis_interval
    right_iv = right_features.axis_interval

    if equal_ancestry and left_iv is not None and right_iv is not None:
        if _intervals_disjoint(left_iv, right_iv):
            return PhysicalEquivalenceClass.DISTINCT_PHYSICAL_WALLS
        return PhysicalEquivalenceClass.AMBIGUOUS_PHYSICAL_EQUIVALENCE

    if shared and left_iv is not None and right_iv is not None:
        if _intervals_overlap(left_iv, right_iv):
            return PhysicalEquivalenceClass.AMBIGUOUS_PHYSICAL_EQUIVALENCE
        return PhysicalEquivalenceClass.DISTINCT_PHYSICAL_WALLS

    return PhysicalEquivalenceClass.AMBIGUOUS_PHYSICAL_EQUIVALENCE


def classify_physical_wall_pair(
    left: PhysicalWallIdentity,
    right: PhysicalWallIdentity,
) -> PhysicalEquivalenceClass:
    """Classify one pair without changing historical semantics."""
    return _classify_physical_wall_pair_with_features(
        left,
        right,
        _physical_wall_pair_features(left),
        _physical_wall_pair_features(right),
    )

def _union_find_groups(pairs: Sequence[tuple[str, str]], members: Sequence[str]) -> list[list[str]]:
    parent = {member: member for member in members}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        root_l, root_r = find(left), find(right)
        if root_l != root_r:
            parent[root_r] = root_l

    for left, right in pairs:
        if left in parent and right in parent:
            union(left, right)
    groups: dict[str, list[str]] = {}
    for member in members:
        groups.setdefault(find(member), []).append(member)
    return [sorted(group) for group in groups.values()]


def _deterministic_representative(wall_ids: Sequence[str]) -> str:
    """Stable representative: lexicographic wall_candidate_id (not confidence/nearest)."""
    return sorted(wall_ids)[0]


def resolve_physical_wall_equivalence(
    identities: Sequence[Optional[PhysicalWallIdentity]],
    *,
    walls_by_id: Optional[Mapping[str, WallCandidate]] = None,
    points_per_mm: Optional[float] = None,
) -> PhysicalWallEquivalenceResolution:
    """Reconcile ALL competing candidates via SAME/DISTINCT/AMBIGUOUS components.

    Pure SAME component → exactly one representative may publish.
    Any AMBIGUOUS edge in a connected component → all members abstain.
    Proven DISTINCT walls publish independently when otherwise usable.
    """
    del walls_by_id  # ownership already baked into each identity; kept for call-site compat
    usable: list[PhysicalWallIdentity] = []
    blockers: dict[str, list[str]] = {}
    viewport_ids: set[str] = set()

    for identity in identities:
        if identity is None:
            continue
        viewport_ids.add(identity.viewport_id)
        if not identity.usable:
            blockers.setdefault(identity.wall_candidate_id, []).extend(
                identity.blocking_reasons or ("physical_wall_identity_abstained",)
            )
            continue
        usable.append(identity)

    scope_viewport = sorted(viewport_ids)[0] if len(viewport_ids) == 1 else "multi"
    member_ids = [identity.wall_candidate_id for identity in usable]
    by_id = {identity.wall_candidate_id: identity for identity in usable}
    features_by_id = {
        identity.wall_candidate_id: _physical_wall_pair_features(identity)
        for identity in usable
    }
    pair_classifications: list[tuple[str, str, str]] = []
    same_links: list[tuple[str, str]] = []
    ambiguous_links: list[tuple[str, str]] = []

    total_pairs = len(usable) * (len(usable) - 1) // 2
    excluded_pairs = 0
    exclusion_reason_counts: dict[str, int] = {}
    verified_points_per_mm = (
        float(points_per_mm)
        if points_per_mm is not None
        and math.isfinite(float(points_per_mm))
        and float(points_per_mm) > 0.0
        else None
    )
    candidate_wall_body_band_pt = max_plausible_wall_body_separation_pt(
        verified_points_per_mm
    )

    def evaluate_pair(left_index: int, right_index: int) -> None:
        nonlocal excluded_pairs
        left = usable[left_index]
        right = usable[right_index]
        left_features = features_by_id[left.wall_candidate_id]
        right_features = features_by_id[right.wall_candidate_id]
        # A pair that could not possibly represent the same physical wall
        # is not an identity competitor and gets no relation at all.
        eligible, exclusion_reason = _physical_wall_pair_identity_candidacy_with_features(
            left,
            right,
            left_features,
            right_features,
            points_per_mm=points_per_mm,
        )
        if not eligible:
            excluded_pairs += 1
            if exclusion_reason:
                exclusion_reason_counts[exclusion_reason] = (
                    exclusion_reason_counts.get(exclusion_reason, 0) + 1
                )
            return
        classification = _classify_physical_wall_pair_with_features(
            left,
            right,
            left_features,
            right_features,
        )
        a, b = sorted((left.wall_candidate_id, right.wall_candidate_id))
        pair_classifications.append((a, b, classification.value))
        if classification == PhysicalEquivalenceClass.SAME_PHYSICAL_WALL:
            same_links.append((a, b))
        elif classification == PhysicalEquivalenceClass.AMBIGUOUS_PHYSICAL_EQUIVALENCE:
            ambiguous_links.append((a, b))

    # Dense CAD pages can contain thousands of one-segment wall identities.
    # The historical resolver executed every N*(N-1)/2 pair predicate even
    # when most pairs were provably orientation-incompatible. For one-segment
    # identities in one homogeneous source scope, orientation is the first
    # exclusion gate after source/path identity. Bucket only the pairs whose
    # directions can fall within the exact angle tolerance; bulk-count all
    # remaining pairs as the same orientation-incompatible audit outcome.
    viewport_set = {identity.viewport_id for identity in usable}
    nonempty_levels = {
        features_by_id[identity.wall_candidate_id].level_id
        for identity in usable
        if features_by_id[identity.wall_candidate_id].level_id
    }
    angle_tol = float(_EQUIVALENCE_ANGLE_TOL_DEG)
    bucket_count_float = 180.0 / angle_tol if angle_tol > 0.0 else 0.0
    bucket_count = int(round(bucket_count_float)) if bucket_count_float else 0
    homogeneous_scope = len(viewport_set) <= 1 and len(nonempty_levels) <= 1
    exact_angle_buckets = (
        bucket_count > 0
        and abs(bucket_count * angle_tol - 180.0) <= 1e-9
    )

    fast_single_indexes: list[int] = []
    slow_indexes: list[int] = []
    angle_bucket_by_index: dict[int, int] = {}
    angle_buckets: dict[int, list[int]] = {}
    direction_key_by_index: dict[int, tuple[float, float]] = {}
    longitudinal_interval_by_index: dict[int, tuple[float, float]] = {}
    slow_orientation_buckets_by_index: dict[int, tuple[int, ...]] = {}
    slow_angle_buckets: dict[int, list[int]] = {}
    unindexed_slow_indexes: list[int] = []
    if homogeneous_scope and exact_angle_buckets:
        for index, identity in enumerate(usable):
            features = features_by_id[identity.wall_candidate_id]
            unit = features.single_segment_unit
            if len(features.segments) != 1 or unit is None:
                slow_indexes.append(index)
                orientation_buckets: set[int] = set()
                for segment in features.segments:
                    segment_unit = _unit(segment)
                    if segment_unit is None:
                        continue
                    segment_angle = (
                        math.degrees(math.atan2(segment_unit[1], segment_unit[0]))
                        % 180.0
                    )
                    orientation_buckets.add(
                        min(
                            bucket_count - 1,
                            int(math.floor(segment_angle / angle_tol)),
                        )
                    )
                if orientation_buckets:
                    ordered_buckets = tuple(sorted(orientation_buckets))
                    slow_orientation_buckets_by_index[index] = ordered_buckets
                    for segment_bucket in ordered_buckets:
                        slow_angle_buckets.setdefault(segment_bucket, []).append(index)
                else:
                    unindexed_slow_indexes.append(index)
                continue
            angle = math.degrees(math.atan2(unit[1], unit[0])) % 180.0
            bucket = min(bucket_count - 1, int(math.floor(angle / angle_tol)))
            fast_single_indexes.append(index)
            angle_bucket_by_index[index] = bucket
            angle_buckets.setdefault(bucket, []).append(index)
            direction_key_by_index[index] = (float(unit[0]), float(unit[1]))
            segment = features.segments[0]
            first_projection = segment[0] * unit[0] + segment[1] * unit[1]
            second_projection = segment[2] * unit[0] + segment[3] * unit[1]
            longitudinal_interval_by_index[index] = (
                min(first_projection, second_projection),
                max(first_projection, second_projection),
            )
    else:
        slow_indexes = list(range(len(usable)))

    if fast_single_indexes:
        fast_set = set(fast_single_indexes)
        forced_by_lower: dict[int, set[int]] = {}

        # Exact-direction single-segment groups can be very large on CAD plans.
        # The historical loop visited every later member only to reject most of
        # them for disjoint longitudinal intervals.  Precompute the exact
        # interval-overlap relation with a sweep so only pairs with gap <= the
        # existing tolerance are enumerated during candidacy.  Audit counts for
        # skipped disjoint pairs are retained separately below.
        same_direction_candidates_by_lower: dict[int, set[int]] = {}
        same_direction_future_count: dict[int, int] = {}
        direction_groups: dict[tuple[float, float], list[int]] = {}
        for index in fast_single_indexes:
            direction_groups.setdefault(direction_key_by_index[index], []).append(index)
        for group in direction_groups.values():
            ordered_by_index = sorted(group)
            group_size = len(ordered_by_index)
            for position, index in enumerate(ordered_by_index):
                same_direction_future_count[index] = group_size - position - 1

            ordered_by_start = sorted(
                group,
                key=lambda index: (
                    longitudinal_interval_by_index[index][0],
                    longitudinal_interval_by_index[index][1],
                    index,
                ),
            )
            active: set[int] = set()
            expiry_heap: list[tuple[float, int]] = []
            for index in ordered_by_start:
                start, end = longitudinal_interval_by_index[index]
                while (
                    expiry_heap
                    and expiry_heap[0][0] + _EQUIVALENCE_LATERAL_TOL_PT < start
                ):
                    _expired_end, expired_index = heapq.heappop(expiry_heap)
                    active.discard(expired_index)
                for prior in active:
                    left_index, right_index = (
                        (prior, index) if prior < index else (index, prior)
                    )
                    same_direction_candidates_by_lower.setdefault(
                        left_index, set()
                    ).add(right_index)
                active.add(index)
                heapq.heappush(expiry_heap, (end, index))

        def force_group(indexes: Sequence[int]) -> None:
            ordered = sorted(set(indexes))
            for pos, left_index in enumerate(ordered):
                if pos + 1 >= len(ordered):
                    continue
                forced_by_lower.setdefault(left_index, set()).update(
                    ordered[pos + 1 :]
                )

        primitive_indexes: dict[str, list[int]] = {}
        path_indexes: dict[tuple[tuple[float, float], ...], list[int]] = {}
        for index, identity in enumerate(usable):
            features = features_by_id[identity.wall_candidate_id]
            for primitive_id in features.primitive_set:
                primitive_indexes.setdefault(str(primitive_id), []).append(index)
            if identity.path_fingerprint is not None:
                path_indexes.setdefault(tuple(identity.path_fingerprint), []).append(index)
        for indexes in primitive_indexes.values():
            if len(indexes) > 1:
                force_group(indexes)
        for indexes in path_indexes.values():
            if len(indexes) > 1:
                force_group(indexes)

        # Different interior routes can still be competing representations when
        # both path endpoints coincide within the existing lateral tolerance.
        # Use an endpoint grid to preserve that exact early-eligibility rule
        # without restoring an all-pairs scan.
        endpoint_cell = max(_EQUIVALENCE_LATERAL_TOL_PT, 1e-9)
        endpoint_bins: dict[tuple[int, int], list[int]] = {}
        for index, identity in enumerate(usable):
            path = features_by_id[identity.wall_candidate_id].path
            if len(path) < 2:
                continue
            first = path[0]
            last = path[-1]
            first_bin = (
                math.floor(first[0] / endpoint_cell),
                math.floor(first[1] / endpoint_cell),
            )
            nearby: set[int] = set()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nearby.update(
                        endpoint_bins.get((first_bin[0] + dx, first_bin[1] + dy), ())
                    )
            for prior in nearby:
                prior_path = features_by_id[usable[prior].wall_candidate_id].path
                if _paths_share_both_endpoints(
                    prior_path,
                    path,
                    _EQUIVALENCE_LATERAL_TOL_PT,
                ):
                    forced_by_lower.setdefault(prior, set()).add(index)
            for endpoint in (first, last):
                endpoint_bin = (
                    math.floor(endpoint[0] / endpoint_cell),
                    math.floor(endpoint[1] / endpoint_cell),
                )
                endpoint_bins.setdefault(endpoint_bin, []).append(index)

        slow_set = set(slow_indexes)
        suffix_fast_count = [0] * (len(usable) + 1)
        suffix_slow_count = [0] * (len(usable) + 1)
        for index in range(len(usable) - 1, -1, -1):
            suffix_fast_count[index] = suffix_fast_count[index + 1] + (
                1 if index in fast_set else 0
            )
            suffix_slow_count[index] = suffix_slow_count[index + 1] + (
                1 if index in slow_set else 0
            )
        unindexed_slow_set = set(unindexed_slow_indexes)
        for left_index in range(len(usable)):
            if left_index in slow_set:
                forced_indexes = forced_by_lower.get(left_index, set())
                if left_index in unindexed_slow_set:
                    candidate_indexes = set(range(left_index + 1, len(usable)))
                else:
                    candidate_indexes: set[int] = set(forced_indexes)
                    for segment_bucket in slow_orientation_buckets_by_index.get(
                        left_index, ()
                    ):
                        for neighbor in (
                            (segment_bucket - 1) % bucket_count,
                            segment_bucket,
                            (segment_bucket + 1) % bucket_count,
                        ):
                            candidate_indexes.update(
                                index
                                for index in angle_buckets.get(neighbor, ())
                                if index > left_index
                            )
                            candidate_indexes.update(
                                index
                                for index in slow_angle_buckets.get(neighbor, ())
                                if index > left_index
                            )
                    candidate_indexes.update(
                        index
                        for index in unindexed_slow_indexes
                        if index > left_index
                    )
                    candidate_indexes.update(forced_indexes)
                    skipped_orientation_pairs = (
                        len(usable) - left_index - 1 - len(candidate_indexes)
                    )
                    if skipped_orientation_pairs > 0:
                        excluded_pairs += skipped_orientation_pairs
                        exclusion_reason_counts[
                            PAIR_EXCLUDED_ORIENTATION_INCOMPATIBLE
                        ] = (
                            exclusion_reason_counts.get(
                                PAIR_EXCLUDED_ORIENTATION_INCOMPATIBLE, 0
                            )
                            + skipped_orientation_pairs
                        )
                for right_index in sorted(candidate_indexes):
                    evaluate_pair(left_index, right_index)
                continue

            candidate_indexes: set[int] = set()
            bucket = angle_bucket_by_index[left_index]
            forced_indexes = forced_by_lower.get(left_index, set())
            left_direction = direction_key_by_index[left_index]

            same_direction_candidates = same_direction_candidates_by_lower.get(
                left_index, set()
            )
            candidate_indexes.update(same_direction_candidates)
            forced_disjoint_same_direction = sum(
                1
                for index in forced_indexes
                if index > left_index
                and index in fast_set
                and direction_key_by_index.get(index) == left_direction
                and index not in same_direction_candidates
            )
            skipped_no_longitudinal = max(
                0,
                same_direction_future_count.get(left_index, 0)
                - len(same_direction_candidates)
                - forced_disjoint_same_direction,
            )

            for neighbor in (
                (bucket - 1) % bucket_count,
                bucket,
                (bucket + 1) % bucket_count,
            ):
                for index in angle_buckets.get(neighbor, ()):
                    if index <= left_index:
                        continue
                    if direction_key_by_index[index] == left_direction:
                        # Exact-direction pairs were handled by the interval
                        # sweep above (plus forced-pair restoration below).
                        continue
                    candidate_indexes.add(index)
            for neighbor in (
                (bucket - 1) % bucket_count,
                bucket,
                (bucket + 1) % bucket_count,
            ):
                candidate_indexes.update(
                    index
                    for index in slow_angle_buckets.get(neighbor, ())
                    if index > left_index
                )
            candidate_indexes.update(
                index
                for index in unindexed_slow_indexes
                if index > left_index
            )
            candidate_indexes.update(forced_indexes)

            # Angle buckets are deliberately a conservative broad phase.  A
            # neighbouring bucket can still differ by more than the exact W3
            # angle tolerance, and historically those pairs reached the full
            # candidacy predicate only to be rejected immediately.  For two
            # cached single-segment identities the exact orientation decision
            # depends only on their already-cached unit vectors, so reject those
            # impossible non-forced pairs here before any overlap / distance
            # calculations.  Forced lineage/path/endpoint pairs must still run
            # through the legacy predicate because those gates precede angle.
            if candidate_indexes:
                exact_angle_candidates: set[int] = set()
                for index in candidate_indexes:
                    if index in forced_indexes or index in slow_set:
                        exact_angle_candidates.add(index)
                        continue
                    right_direction = direction_key_by_index.get(index)
                    if right_direction is None:
                        exact_angle_candidates.add(index)
                        continue
                    dot = max(
                        -1.0,
                        min(
                            1.0,
                            abs(
                                left_direction[0] * right_direction[0]
                                + left_direction[1] * right_direction[1]
                            ),
                        ),
                    )
                    if math.degrees(math.acos(dot)) <= angle_tol:
                        exact_angle_candidates.add(index)
                candidate_indexes = exact_angle_candidates

            if skipped_no_longitudinal > 0:
                excluded_pairs += skipped_no_longitudinal
                exclusion_reason_counts[PAIR_EXCLUDED_NO_LONGITUDINAL_OVERLAP] = (
                    exclusion_reason_counts.get(
                        PAIR_EXCLUDED_NO_LONGITUDINAL_OVERLAP, 0
                    )
                    + skipped_no_longitudinal
                )

            evaluated_fast_count = sum(
                1 for index in candidate_indexes if index in fast_set
            )
            evaluated_slow_count = sum(
                1 for index in candidate_indexes if index in slow_set
            )
            skipped_orientation_pairs = (
                suffix_fast_count[left_index + 1]
                - evaluated_fast_count
                - skipped_no_longitudinal
                + suffix_slow_count[left_index + 1]
                - evaluated_slow_count
            )
            if skipped_orientation_pairs > 0:
                excluded_pairs += skipped_orientation_pairs
                exclusion_reason_counts[PAIR_EXCLUDED_ORIENTATION_INCOMPATIBLE] = (
                    exclusion_reason_counts.get(
                        PAIR_EXCLUDED_ORIENTATION_INCOMPATIBLE, 0
                    )
                    + skipped_orientation_pairs
                )

            for right_index in sorted(candidate_indexes):
                evaluate_pair(left_index, right_index)
    else:
        for left_index in range(len(usable)):
            for right_index in range(left_index + 1, len(usable)):
                evaluate_pair(left_index, right_index)

    # Components over SAME ∪ AMBIGUOUS edges.
    related_links = same_links + ambiguous_links
    components = _union_find_groups(related_links, member_ids) if member_ids else []

    # Components are built only from SAME/AMBIGUOUS edges, so an edge of either
    # class belongs to a component iff either endpoint belongs to that component.
    # Track endpoint membership once instead of re-enumerating every possible
    # pair inside each connected component. This preserves the exact publication
    # semantics while avoiding quadratic component bookkeeping.
    ambiguous_edge_wall_ids = {
        wall_id for pair in ambiguous_links for wall_id in pair
    }
    same_edge_wall_ids = {wall_id for pair in same_links for wall_id in pair}

    ambiguous_walls: set[str] = set()
    same_groups: list[tuple[str, ...]] = []
    representatives: list[str] = []
    covered_non_representatives: set[str] = set()

    for component in components:
        component_set = set(component)
        has_ambiguous = not component_set.isdisjoint(ambiguous_edge_wall_ids)
        has_same = not component_set.isdisjoint(same_edge_wall_ids)
        if has_ambiguous:
            ambiguous_walls.update(component_set)
            for wall_id in component:
                blockers.setdefault(wall_id, []).append("ambiguous_physical_wall_equivalence")
            continue
        if has_same and len(component) > 1:
            group = tuple(sorted(component))
            same_groups.append(group)
            rep = _deterministic_representative(group)
            representatives.append(rep)
            for wall_id in group:
                if wall_id == rep:
                    continue
                covered_non_representatives.add(wall_id)
                blockers.setdefault(wall_id, []).append(
                    f"equivalent_physical_wall_represented_by:{rep}"
                )
            continue
        # singleton or unrelated — fall through to independent publication
        for wall_id in component:
            if wall_id not in blockers:
                representatives.append(wall_id)

    # Usable walls never linked into a SAME/AMBIGUOUS component publish alone.
    linked = {wall_id for group in components for wall_id in group}
    for wall_id in member_ids:
        if wall_id in linked:
            continue
        if wall_id not in blockers:
            representatives.append(wall_id)

    # Publication semantics must not depend on caller/input ordering.
    representatives = sorted(
        {
            wall_id
            for wall_id in representatives
            if wall_id not in blockers
        }
    )
    same_groups = sorted(set(same_groups))

    abstained: list[str] = []
    for identity in identities:
        if identity is None:
            continue
        wall_id = identity.wall_candidate_id
        reasons = tuple(dict.fromkeys(blockers.get(wall_id, ())))
        if reasons:
            blockers[wall_id] = list(reasons)
            abstained.append(wall_id)
        elif identity.usable and wall_id in representatives:
            continue
        elif not identity.usable:
            abstained.append(wall_id)

    return PhysicalWallEquivalenceResolution(
        scope_viewport_id=scope_viewport,
        representative_wall_ids=tuple(representatives),
        abstained_wall_ids=tuple(sorted(set(abstained))),
        equivalence_groups=tuple(same_groups),
        ambiguous_wall_ids=tuple(sorted(ambiguous_walls)),
        same_wall_ids=tuple(sorted({wall_id for group in same_groups for wall_id in group})),
        pair_classifications=tuple(sorted(pair_classifications)),
        blocking_reasons_by_wall_id={
            wall_id: tuple(dict.fromkeys(reasons)) for wall_id, reasons in blockers.items() if reasons
        },
        candidate_pair_audit=CandidatePairAudit(
            total_pairs=total_pairs,
            considered_pairs=total_pairs - excluded_pairs,
            excluded_pairs=excluded_pairs,
            exclusion_reason_counts=dict(sorted(exclusion_reason_counts.items())),
            verified_points_per_mm=verified_points_per_mm,
            candidate_wall_body_band_pt=candidate_wall_body_band_pt,
        ),
    )


def colliding_physical_wall_ids(
    identities: Iterable[Optional[PhysicalWallIdentity]],
) -> set[str]:
    """Wall ids that must abstain under physical-equivalence resolution."""
    resolution = resolve_physical_wall_equivalence(tuple(identities))
    return set(resolution.abstained_wall_ids)


def walls_missing_or_abstained_identity(
    walls: Sequence[WallCandidate],
    identities: Mapping[str, PhysicalWallIdentity],
) -> dict[str, tuple[str, ...]]:
    """Fail-closed map of walls that cannot publish when a sidecar was supplied."""
    resolution = resolve_physical_wall_equivalence(
        tuple(identities.get(wall.candidate_id) for wall in walls),
        walls_by_id={wall.candidate_id: wall for wall in walls},
    )
    blocked: dict[str, tuple[str, ...]] = {}
    for wall in walls:
        identity = identities.get(wall.candidate_id)
        if identity is None:
            blocked[wall.candidate_id] = ("physical_wall_identity_unavailable",)
            continue
        reasons = list(resolution.blockers_for(wall.candidate_id))
        if identity.usable and wall.candidate_id not in resolution.representative_wall_ids:
            if not reasons:
                reasons = ["physical_wall_not_selected_representative"]
        if not identity.usable and not reasons:
            reasons = list(identity.blocking_reasons or ("physical_wall_identity_abstained",))
        if reasons:
            blocked[wall.candidate_id] = tuple(dict.fromkeys(reasons))
    return blocked
