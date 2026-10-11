"""Source-authenticated room-face authority derived from physical wall topology.

Consumes only producer-owned PhysicalWallCandidateAuthority scopes. It derives
bounded planar room faces from authenticated physical wall centerlines and
publishes exact page-space polygons only where the enclosing wall component is
topologically resolved.

Positive publication is intentionally narrow:
- the physical-wall scope is CORROBORATED and either complete, or is a
  producer-owned authenticated viewport whose per-candidate boundary audit is
  available for fail-closed local recovery;
- every PUBLISHED bounded-face edge belongs to exactly one authenticated
  physical wall and every bounding wall is boundary-clean when local recovery
  is used;
- no structural primitive excluded at the viewport boundary may touch or cross
  a published face;
- a strict minority of faces touched by competing-owner edge spans may be
  withheld explicitly, but a missing owner or a non-minority contaminated
  universe still fails the whole scope;
- tiny/degenerate faces use the same candidate-local strict-minority guard;
- a connected component contains at least two bounded faces and at least one
  wall shared by two faces, preventing isolated boxes/title blocks from
  becoming room authority;
- no caller room polygon, label, benchmark value, material, finish, scale or
  expected quantity participates in the proof.

This authority establishes room-face geometry and lineage only. It does not
establish ceiling finish, room use, metric area, wall finish, or commercial
quantity.

Every scope result also carries a SHADOW ``ownership_evaluation`` that
classifies, per planar face, whether each face edge has a unique authenticated
wall owner. The live candidate-local rule independently mirrors the same exact
ownership predicate; the shadow remains audit metadata and a failure to compute
it cannot alter the live decision.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
import math
from numbers import Real
from types import MappingProxyType
from typing import Iterable, Mapping, Optional

from pb_accuracy_v13_engines_v145 import extract_planar_faces
from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_physical_wall_candidate_authority import (
    BOUNDARY_EVALUATION_EVALUATED,
    PhysicalWallCandidateAuthority,
)


SOURCE_ROOM_FACE_SCHEMA_VERSION = "1.0.0"
SOURCE_ROOM_FACE_SCOPE_RESOLVED = "source_room_face_scope_resolved"
SOURCE_ROOM_FACE_UNIVERSE_PARTIAL = "source_room_face_universe_partial"
SOURCE_ROOM_FACE_SCOPE_UNAVAILABLE = "source_room_face_scope_unavailable"
SOURCE_ROOM_FACE_BOUNDARY_UNRESOLVED = "source_room_face_boundary_unresolved"
SOURCE_ROOM_FACE_BOUNDARY_LOCAL_RECOVERY = "source_room_face_boundary_local_recovery"
SOURCE_ROOM_FACE_DUPLICATE_EDGE = "source_room_face_duplicate_edge_ownership"
SOURCE_ROOM_FACE_DEGENERATE = "source_room_face_tiny_or_degenerate"
SOURCE_ROOM_FACE_COMPONENT_AMBIGUOUS = "source_room_face_component_ambiguous"

# Shadow per-face boundary-ownership evaluation (descriptive; never a decision).
OWNERSHIP_EVALUATION_NOT_EVALUATED = "not_evaluated"
OWNERSHIP_EVALUATION_EVALUATED = "evaluated"
OWNERSHIP_EVALUATION_UNAVAILABLE = "unavailable"
EDGE_OWNERSHIP_COMPETING = "competing_owners"
EDGE_OWNERSHIP_NONE = "no_owner"
SOURCE_ROOM_FACE_EDGE_OWNER_COMPETING = "source_room_face_edge_owner_competing"
SOURCE_ROOM_FACE_EDGE_OWNER_MISSING = "source_room_face_edge_owner_missing"

_AUTHORITY_SEAL = object()
_ABSOLUTE_DEGENERATE_AREA_PT2 = 1.0
_TINY_RELATIVE_THRESHOLD = 0.01
_NDIGITS = 6
# Spatial prefilter for the shadow ownership evaluation. It is a SUPERSET
# prefilter in front of the exact _edge_contains_edge predicate, so no result
# depends on these values; the pad is derived from the containment tolerance.
_OWNERSHIP_GRID_CELL_PT = 64.0
_OWNERSHIP_GRID_PAD_PT = 8.0 * math.sqrt(2.0) * (10.0 ** -_NDIGITS)
_OWNERSHIP_GRID_MAX_CELLS_PER_EDGE = 256
# Safety valve only: shadow metadata must never be able to dominate runtime.
_OWNERSHIP_EVALUATION_MAX_EDGES = 200_000

Point = tuple[float, float]
Edge = tuple[Point, Point]
_ScopeKey = tuple[str, str, str, str, str, str]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _point(value: Iterable[float]) -> Point:
    x, y = value
    return (round(float(x), _NDIGITS), round(float(y), _NDIGITS))


def _edge(first: Iterable[float], second: Iterable[float]) -> Edge:
    a, b = _point(first), _point(second)
    return (a, b) if a <= b else (b, a)


def _collapse_exact_ring_backtracks(
    points: Iterable[Point],
) -> tuple[Point, ...]:
    """Remove only exact zero-area A->B->A spurs from a closed boundary walk.

    Half-edge traversal can legitimately walk out along a bridge and immediately
    retrace the same source edge before continuing around a bounded face. That
    retraced spur contributes zero area and is not part of the room boundary,
    but retaining it makes an otherwise source-owned ring self-intersect.

    This normalization is deliberately exact after the existing six-decimal
    source quantization. It applies no distance/angle tolerance, does not reorder
    vertices, does not close gaps, and cannot collapse a merely-near return.
    """

    cleaned = list(points)
    # Consecutive identical vertices carry no edge and are representation noise.
    compact: list[Point] = []
    for point in cleaned:
        if compact and point == compact[-1]:
            continue
        compact.append(point)
    if len(compact) > 1 and compact[0] == compact[-1]:
        compact.pop()

    while len(compact) >= 3:
        changed = False
        size = len(compact)
        for index in range(size):
            previous_index = (index - 1) % size
            next_index = (index + 1) % size
            if compact[previous_index] != compact[next_index]:
                continue

            # Rotate from the retained A vertex and skip B plus the duplicate A.
            retained = compact[previous_index]
            reduced = [retained]
            cursor = (next_index + 1) % size
            while cursor != previous_index:
                reduced.append(compact[cursor])
                cursor = (cursor + 1) % size
            compact = reduced
            changed = True
            break
        if not changed:
            break

    return tuple(compact) if len(compact) >= 3 else ()


def _canonical_cycle(points: Iterable[Point]) -> tuple[Point, ...]:
    cleaned = tuple(points)
    if len(cleaned) < 3:
        return ()
    variants: list[tuple[Point, ...]] = []
    for start in range(len(cleaned)):
        variants.append(
            tuple(cleaned[(start + i) % len(cleaned)] for i in range(len(cleaned)))
        )
        variants.append(
            tuple(cleaned[(start - i) % len(cleaned)] for i in range(len(cleaned)))
        )
    return min(variants)


def _canonical_polygon(points: Iterable[Iterable[float]]) -> tuple[Point, ...]:
    """Canonicalize the RAW planar face without deleting topology evidence.

    Competing-owner and contamination logic consumes this exact walk. In
    particular, retraced A->B->A edges must remain visible until ownership has
    been evaluated; otherwise representation cleanup could erase evidence that
    two authenticated walls compete for the same span.
    """

    return _canonical_cycle(tuple(_point(point) for point in points))


def _publication_polygon(
    raw_polygon: Iterable[Iterable[float]],
) -> tuple[Point, ...]:
    """Normalize representation-only exact retraces after authority gates.

    This helper must never be used for ownership/contamination decisions.
    """

    return _canonical_cycle(
        _collapse_exact_ring_backtracks(
            tuple(_point(point) for point in raw_polygon)
        )
    )


def _publication_boundary_ownership(
    raw_polygon: tuple[Point, ...],
    *,
    edge_owner: Mapping[Edge, str],
    ownership_grid: Mapping[tuple[int, int], list[tuple[str, Edge]]],
    ownership_oversized: list[tuple[str, Edge]],
    wall_edges: Mapping[str, tuple[Edge, ...]],
) -> Optional[
    tuple[
        tuple[Point, ...],
        tuple[str, ...],
        tuple[tuple[str, Edge], ...],
    ]
]:
    """Return a clean publication ring only with exact unique boundary owners.

    The raw face has already passed the live ownership, contamination,
    strict-minority and component gates before this is called. Cleanup removes
    only exact zero-area retraces; every edge that remains must still resolve
    through the same exact/contained source-wall ownership contract.
    """

    polygon = _publication_polygon(raw_polygon)
    if not polygon:
        return None

    owned_edges: list[tuple[str, Edge]] = []
    owners: list[str] = []
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        face_edge = _edge(first, second)
        if face_edge[0] == face_edge[1]:
            return None

        owner = edge_owner.get(face_edge)
        if owner is None:
            containing = _containing_wall_ids(
                face_edge,
                grid=ownership_grid,
                oversized=ownership_oversized,
                wall_edges=wall_edges,
            )
            if len(containing) != 1:
                return None
            owner = containing[0]
        owners.append(owner)
        owned_edges.append((owner, face_edge))

    return (
        polygon,
        tuple(sorted(set(owners))),
        tuple(owned_edges),
    )


def _polygon_area(points: tuple[Point, ...]) -> float:
    total = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _wall_edges(record: object) -> tuple[Edge, ...]:
    wall_candidate = getattr(record, "wall_candidate", None)
    points = tuple(getattr(wall_candidate, "centerline_pts", ()) or ())
    if len(points) < 2:
        return ()
    result: list[Edge] = []
    for first, second in zip(points, points[1:]):
        edge = _edge(first, second)
        if edge[0] != edge[1]:
            result.append(edge)
    return tuple(result)


def _finite_source_edge(value: Edge) -> bool:
    """Reject invalid endpoints and overflowed lengths on either source edge."""
    try:
        if len(value) != 2 or any(len(point) != 2 for point in value):
            return False
        # Downstream predicates operate on the ORIGINAL coordinates, not the
        # float-converted copies below. Numeric strings and bools must not be
        # laundered into seemingly valid source geometry by float().
        if any(
            not isinstance(coordinate, Real) or isinstance(coordinate, bool)
            for point in value
            for coordinate in point
        ):
            return False
        first, second = (
            tuple(float(coordinate) for coordinate in point)
            for point in value
        )
        if not all(math.isfinite(c) for point in (first, second) for c in point):
            return False
        return math.isfinite(
            math.hypot(second[0] - first[0], second[1] - first[1])
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _edge_contains_edge(parent: Edge, child: Edge) -> bool:
    """Return True only when a child edge is a quantized subsegment of parent.

    ``extract_planar_faces`` may split an authenticated wall centerline at an
    intersection. Those split points are rounded through the same six-decimal
    page-space contract as wall edges, so containment is allowed only within
    the maximum error implied by that quantization. No geometric extension,
    nearest-edge selection, or angle-only matching is permitted.
    """
    if not (_finite_source_edge(parent) and _finite_source_edge(child)):
        return False
    (ax, ay), (bx, by) = parent
    tolerance = 4.0 * math.sqrt(2.0) * (10.0 ** -_NDIGITS)
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= tolerance:
        return False

    xmin, xmax = min(ax, bx) - tolerance, max(ax, bx) + tolerance
    ymin, ymax = min(ay, by) - tolerance, max(ay, by) + tolerance

    for px, py in child:
        if not (xmin <= px <= xmax and ymin <= py <= ymax):
            return False
        perpendicular_distance = abs((px - ax) * dy - (py - ay) * dx) / length
        if not math.isfinite(perpendicular_distance) or perpendicular_distance > tolerance:
            return False
    return child[0] != child[1]


def _collinear_overlap_edge(left: Edge, right: Edge) -> Edge | None:
    """Return the positive-length quantized overlap of two collinear edges.

    The overlap is SOURCE geometry used only to stabilize fail-closed local
    abstention. It never selects an owner or extends either source edge.
    """
    if not (_finite_source_edge(left) and _finite_source_edge(right)):
        return None
    (ax, ay), (bx, by) = left
    (cx, cy), (dx, dy) = right
    tolerance = 4.0 * math.sqrt(2.0) * (10.0 ** -_NDIGITS)
    vx, vy = bx - ax, by - ay
    length = math.hypot(vx, vy)
    if not math.isfinite(length) or length <= tolerance:
        return None

    for px, py in ((cx, cy), (dx, dy)):
        perpendicular_distance = abs((px - ax) * vy - (py - ay) * vx) / length
        if not math.isfinite(perpendicular_distance) or perpendicular_distance > tolerance:
            return None

    ux, uy = vx / length, vy / length
    right_positions = (
        (cx - ax) * ux + (cy - ay) * uy,
        (dx - ax) * ux + (dy - ay) * uy,
    )
    if not all(math.isfinite(value) for value in right_positions):
        return None
    start = max(0.0, min(right_positions))
    end = min(length, max(right_positions))
    if end - start <= tolerance:
        return None

    return _edge(
        (ax + start * ux, ay + start * uy),
        (ax + end * ux, ay + end * uy),
    )


def _edges_share_positive_collinear_span(left: Edge, right: Edge) -> bool:
    """True only when two quantized edges share positive-length collinear span."""
    return _collinear_overlap_edge(left, right) is not None


def _orientation(first: Point, second: Point, third: Point) -> float:
    return (
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    )


def _point_on_edge(point: Point, edge: Edge) -> bool:
    tolerance = 4.0 * math.sqrt(2.0) * (10.0 ** -_NDIGITS)
    (ax, ay), (bx, by) = edge
    px, py = point
    if (
        px < min(ax, bx) - tolerance
        or px > max(ax, bx) + tolerance
        or py < min(ay, by) - tolerance
        or py > max(ay, by) + tolerance
    ):
        return False
    length = math.hypot(bx - ax, by - ay)
    if length <= tolerance:
        return math.hypot(px - ax, py - ay) <= tolerance
    return (
        abs((px - ax) * (by - ay) - (py - ay) * (bx - ax)) / length
        <= tolerance
    )


def _edges_intersect(left: Edge, right: Edge) -> bool:
    """Closed segment intersection used only for fail-closed contamination."""
    a, b = left
    c, d = right
    tolerance = 4.0 * math.sqrt(2.0) * (10.0 ** -_NDIGITS)
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if (
        ((o1 > tolerance and o2 < -tolerance) or (o1 < -tolerance and o2 > tolerance))
        and ((o3 > tolerance and o4 < -tolerance) or (o3 < -tolerance and o4 > tolerance))
    ):
        return True
    return (
        (abs(o1) <= tolerance and _point_on_edge(c, left))
        or (abs(o2) <= tolerance and _point_on_edge(d, left))
        or (abs(o3) <= tolerance and _point_on_edge(a, right))
        or (abs(o4) <= tolerance and _point_on_edge(b, right))
    )


def _point_in_or_on_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    if len(polygon) < 3:
        return False
    edges = tuple(
        _edge(first, polygon[(index + 1) % len(polygon)])
        for index, first in enumerate(polygon)
    )
    if any(_point_on_edge(point, edge) for edge in edges):
        return True

    x, y = point
    inside = False
    for first, second in edges:
        x1, y1 = first
        x2, y2 = second
        if (y1 > y) == (y2 > y):
            continue
        crossing_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        if crossing_x > x:
            inside = not inside
    return inside


def _excluded_primitive_touches_face(
    primitive: object, polygon: tuple[Point, ...]
) -> bool:
    """Return True when excluded structural geometry can affect this face."""
    try:
        primitive_edge = _edge(
            (float(getattr(primitive, "x1")), float(getattr(primitive, "y1"))),
            (float(getattr(primitive, "x2")), float(getattr(primitive, "y2"))),
        )
    except (TypeError, ValueError, AttributeError):
        return True
    if primitive_edge[0] == primitive_edge[1]:
        return True
    if _point_in_or_on_polygon(primitive_edge[0], polygon):
        return True
    if _point_in_or_on_polygon(primitive_edge[1], polygon):
        return True
    return any(
        _edges_intersect(
            primitive_edge,
            _edge(first, polygon[(index + 1) % len(polygon)]),
        )
        for index, first in enumerate(polygon)
    )


def _boundary_local_recovery_inputs(
    scope: object,
    records: tuple[object, ...],
) -> tuple[set[str], tuple[object, ...]] | None:
    """Return producer-owned contamination for a safe local viewport proof."""
    if bool(getattr(scope, "scope_complete", False)):
        return set(), ()
    if str(getattr(scope, "scope_kind", "")) != "viewport":
        return None
    evaluation = getattr(scope, "boundary_evaluation", None)
    if (
        evaluation is None
        or getattr(evaluation, "status", None) != BOUNDARY_EVALUATION_EVALUATED
    ):
        return None

    record_ids = {
        _clean(getattr(record, "wall_candidate_id", ""))
        for record in records
        if _clean(getattr(record, "wall_candidate_id", ""))
    }
    evaluated_ids = {
        _clean(value)
        for value in tuple(
            getattr(evaluation, "evaluated_wall_candidate_ids", ()) or ()
        )
        if _clean(value)
    }
    tainted_ids = {
        _clean(value)
        for value in tuple(
            getattr(evaluation, "boundary_tainted_wall_candidate_ids", ()) or ()
        )
        if _clean(value)
    }
    if not record_ids or evaluated_ids != record_ids or not tainted_ids <= record_ids:
        return None
    return tainted_ids, tuple(
        getattr(evaluation, "excluded_boundary_primitives", ()) or ()
    )


def _unique_containing_wall_owner(
    edge: Edge,
    *,
    edge_owner: Mapping[Edge, str],
    wall_edges: Mapping[str, tuple[Edge, ...]],
) -> str | None:
    """Resolve a planarized face edge to exactly one authenticated wall.

    Exact ownership remains authoritative. A fallback is used only when the
    face edge is wholly contained by an original collinear authenticated wall
    edge. Competing physical wall ids fail closed instead of selecting first,
    nearest, shortest, or longest.
    """
    exact = edge_owner.get(edge)
    if exact is not None:
        return exact

    owner: str | None = None
    for wall_id in sorted(wall_edges):
        if not any(
            _edge_contains_edge(parent, edge) for parent in wall_edges[wall_id]
        ):
            continue
        if owner is not None and owner != wall_id:
            return None
        owner = wall_id
    return owner


@dataclass(frozen=True)
class SourceRoomFaceSelector:
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str

    @property
    def key(self) -> _ScopeKey:
        return (
            _clean(self.document_id),
            _clean(self.revision_id),
            _clean(self.source_sha256),
            _clean(self.snapshot_id),
            _clean(self.page_id),
            _clean(self.decision_scope_id),
        )


@dataclass(frozen=True)
class SourceRoomFaceRecord:
    record_id: str
    face_id: str
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    polygon_pdf_pts: tuple[Point, ...]
    bounding_wall_ids: tuple[str, ...]
    area_page_pts2: float
    # Exact producer-owned mapping from each planarized face subedge to its
    # uniquely authenticated W4 wall owner. This is additive provenance: it
    # does not change room identity or geometry and lets downstream topology
    # distinguish one long wall chain from the local edge shared by two cells.
    boundary_wall_edges: tuple[tuple[str, Edge], ...] = ()
    schema_version: str = SOURCE_ROOM_FACE_SCHEMA_VERSION


@dataclass(frozen=True)
class SourceRoomFaceAbstention:
    """A planar face withheld from publication, with its provenance.

    Abstention is candidate-local: it never publishes the face and never
    deletes it silently, and it does not by itself invalidate unrelated faces.
    """

    face_id: str
    reason: str
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    polygon_pdf_pts: tuple[Point, ...]
    bounding_wall_ids: tuple[str, ...]
    area_page_pts2: float
    # Exact producer-owned subedge ownership is retained even when this face is
    # withheld. Downstream authorities may inspect abstention provenance, but
    # the abstention remains non-published and cannot become a room merely
    # because this metadata exists.
    boundary_wall_edges: tuple[tuple[str, Edge], ...] = ()
    schema_version: str = SOURCE_ROOM_FACE_SCHEMA_VERSION


@dataclass(frozen=True)
class SourceRoomFaceEdgeOwnershipFinding:
    """One planarized face edge without a unique authenticated wall owner."""

    edge: Edge
    kind: str
    wall_ids: tuple[str, ...]


@dataclass(frozen=True)
class SourceRoomFaceOwnershipFinding:
    """A planar face with at least one edge lacking a unique wall owner."""

    face_id: str
    area_page_pts2: float
    vertex_count: int
    reason_codes: tuple[str, ...]
    edge_findings: tuple[SourceRoomFaceEdgeOwnershipFinding, ...]
    competing_wall_ids: tuple[str, ...]


@dataclass(frozen=True)
class SourceRoomFaceOwnershipEvaluation:
    """SHADOW per-face boundary-ownership census of one wall scope.

    Mirrors, face by face, the ownership rule that fails the whole scope with
    ``source_room_face_boundary_unresolved`` (exact edge ownership is
    authoritative, otherwise exactly one wall edge must contain the planarized
    face edge). It publishes nothing and is consumed by nothing: status,
    reason codes, records and abstentions of the scope result are decided by the
    unchanged derivation. ``degenerate_owned_face_ids`` applies the existing
    tiny/degenerate rule to the OWNED faces only, so reviewers can see what a
    future candidate-local abstention would leave without changing any
    threshold.
    """

    status: str = OWNERSHIP_EVALUATION_NOT_EVALUATED
    reason_code: str = "ownership_evaluation_not_reached"
    scope_complete_at_evaluation: bool = False
    owned_face_ids: tuple[str, ...] = ()
    unresolved_faces: tuple[SourceRoomFaceOwnershipFinding, ...] = ()
    degenerate_owned_face_ids: tuple[str, ...] = ()
    largest_owned_face_area_pt2: float = 0.0
    face_edge_count: int = 0
    competing_edge_count: int = 0
    unowned_edge_count: int = 0

    @property
    def face_count(self) -> int:
        return len(self.owned_face_ids) + len(self.unresolved_faces)

    @property
    def unresolved_face_ids(self) -> tuple[str, ...]:
        return tuple(finding.face_id for finding in self.unresolved_faces)

    @property
    def competing_wall_ids(self) -> tuple[str, ...]:
        """Walls on any competing-owner edge. Stable even when the planarizer
        attaches a doubled collinear edge to a different adjacent face."""
        return tuple(
            sorted({w for f in self.unresolved_faces for w in f.competing_wall_ids})
        )

    def is_face_ownership_clean(self, face_id: str) -> bool:
        """True only for a face evaluated as fully, uniquely wall-owned."""
        return (
            self.status == OWNERSHIP_EVALUATION_EVALUATED
            and str(face_id) in self.owned_face_ids
        )


@dataclass(frozen=True)
class SourceRoomFaceScopeResult:
    status: EvidenceResolutionStatus
    scope_complete: bool
    records: tuple[SourceRoomFaceRecord, ...]
    reason_codes: tuple[str, ...]
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    schema_version: str = SOURCE_ROOM_FACE_SCHEMA_VERSION
    abstained_faces: tuple[SourceRoomFaceAbstention, ...] = ()
    ownership_evaluation: SourceRoomFaceOwnershipEvaluation = field(
        default_factory=SourceRoomFaceOwnershipEvaluation
    )

    @property
    def face_universe_complete(self) -> bool:
        """True only when the authority proved the whole face universe."""
        return (
            self.status is EvidenceResolutionStatus.CORROBORATED
            and bool(self.scope_complete)
            and not self.abstained_faces
            and SOURCE_ROOM_FACE_UNIVERSE_PARTIAL not in self.reason_codes
        )


class SourceRoomFaceAuthority:
    def __init__(
        self,
        results: Mapping[_ScopeKey, SourceRoomFaceScopeResult],
        *,
        _seal: object = None,
    ) -> None:
        if _seal is not _AUTHORITY_SEAL:
            raise TypeError("SourceRoomFaceAuthority is producer-owned")
        self._results = MappingProxyType(dict(results))

    def resolve_scope(
        self, selector: SourceRoomFaceSelector
    ) -> SourceRoomFaceScopeResult:
        if type(selector) is not SourceRoomFaceSelector:
            raise TypeError("selector must be SourceRoomFaceSelector")
        result = self._results.get(selector.key)
        if result is not None:
            return result
        return SourceRoomFaceScopeResult(
            status=EvidenceResolutionStatus.ABSTAINED,
            scope_complete=False,
            records=(),
            reason_codes=(SOURCE_ROOM_FACE_SCOPE_UNAVAILABLE,),
            document_id=selector.document_id,
            revision_id=selector.revision_id,
            source_sha256=selector.source_sha256,
            snapshot_id=selector.snapshot_id,
            page_id=selector.page_id,
            decision_scope_id=selector.decision_scope_id,
        )


def _blocked(scope: object, reason: str) -> SourceRoomFaceScopeResult:
    return SourceRoomFaceScopeResult(
        status=EvidenceResolutionStatus.ABSTAINED,
        scope_complete=False,
        records=(),
        reason_codes=(reason,),
        document_id=_clean(getattr(scope, "document_id", "")),
        revision_id=_clean(getattr(scope, "revision_id", "")),
        source_sha256=_clean(getattr(scope, "source_sha256", "")),
        snapshot_id=_clean(getattr(scope, "snapshot_id", "")),
        page_id=_clean(getattr(scope, "page_id", "")),
        decision_scope_id=_clean(getattr(scope, "decision_scope_id", "")),
    )


def _derive_scope_outcome(scope: object) -> SourceRoomFaceScopeResult:
    records = tuple(getattr(scope, "records", ()) or ())
    if (
        getattr(scope, "status", None) is not EvidenceResolutionStatus.CORROBORATED
        or not records
    ):
        return _blocked(scope, SOURCE_ROOM_FACE_SCOPE_UNAVAILABLE)

    boundary_local_recovery = not bool(getattr(scope, "scope_complete", False))
    boundary_inputs = _boundary_local_recovery_inputs(scope, records)
    if boundary_inputs is None:
        return _blocked(scope, SOURCE_ROOM_FACE_SCOPE_UNAVAILABLE)
    boundary_tainted_wall_ids, excluded_boundary_primitives = boundary_inputs
    wall_edges: dict[str, tuple[Edge, ...]] = {}
    edge_owner: dict[Edge, str] = {}
    duplicate_edges: set[Edge] = set()
    endpoints_by_wall: dict[str, set[Point]] = {}

    for record in records:
        wall_id = _clean(getattr(record, "wall_candidate_id", ""))
        edges = _wall_edges(record)
        if not wall_id or not edges:
            continue
        wall_edges[wall_id] = edges
        endpoints_by_wall[wall_id] = {point for edge in edges for point in edge}
        for edge in edges:
            prior = edge_owner.get(edge)
            if prior is not None and prior != wall_id:
                duplicate_edges.add(edge)
            else:
                edge_owner[edge] = wall_id

    wall_ids = tuple(sorted(wall_edges))
    if not wall_ids:
        return _blocked(scope, SOURCE_ROOM_FACE_SCOPE_UNAVAILABLE)
    if duplicate_edges:
        return _blocked(scope, SOURCE_ROOM_FACE_DUPLICATE_EDGE)

    raw_segments = [
        (edge[0], edge[1]) for wall_id in wall_ids for edge in wall_edges[wall_id]
    ]
    raw_faces = extract_planar_faces(raw_segments, min_area=1e-6)

    polygons: dict[str, tuple[Point, ...]] = {}
    face_walls: dict[str, tuple[str, ...]] = {}
    face_wall_edges: dict[str, tuple[tuple[str, Edge], ...]] = {}
    face_areas: dict[str, float] = {}
    directly_competing_face_ids: set[str] = set()
    competing_spans: set[Edge] = set()
    competing_span_wall_ids: dict[Edge, set[str]] = defaultdict(set)
    missing_owner_seen = False
    ownership_grid, ownership_oversized = _ownership_edge_index(wall_edges)

    for raw_face in raw_faces:
        polygon = _canonical_polygon(raw_face)
        if not polygon:
            continue
        owners: list[str] = []
        owned_edges: list[tuple[str, Edge]] = []
        face_competing = False
        face_missing = False
        for index, first in enumerate(polygon):
            second = polygon[(index + 1) % len(polygon)]
            face_edge = _edge(first, second)

            # Exact source ownership stays authoritative, matching
            # _unique_containing_wall_owner and the shadow evaluator.
            owner = edge_owner.get(face_edge)
            if owner is not None:
                owners.append(owner)
                owned_edges.append((owner, face_edge))
                continue

            containing = _containing_wall_ids(
                face_edge,
                grid=ownership_grid,
                oversized=ownership_oversized,
                wall_edges=wall_edges,
            )
            if len(containing) == 1:
                owners.append(containing[0])
                owned_edges.append((containing[0], face_edge))
                continue
            if not containing:
                face_missing = True
                missing_owner_seen = True
                continue

            # Multiple authenticated walls can own this same planarized span.
            # Do not choose first/nearest/shortest. Record the competing span
            # and all candidate owners so the abstention can be expanded to the
            # stable geometric neighbourhood rather than whichever face the
            # planarizer happened to attach the doubled edge to.
            face_competing = True
            owners.extend(containing)

            # Derive the complete SOURCE overlap of the competing authenticated
            # walls, not merely the raw face edge that exposed it. The planarizer
            # can attach a doubled-edge spur to a different adjacent face after
            # translation; the source-wall overlap itself is invariant.
            source_overlap_found = False
            for left_index, left_wall_id in enumerate(containing):
                for right_wall_id in containing[left_index + 1 :]:
                    for left_edge in wall_edges.get(left_wall_id, ()):
                        if not _edge_contains_edge(left_edge, face_edge):
                            continue
                        for right_edge in wall_edges.get(right_wall_id, ()):
                            if not _edge_contains_edge(right_edge, face_edge):
                                continue
                            overlap_edge = _collinear_overlap_edge(
                                left_edge, right_edge
                            )
                            if overlap_edge is None:
                                continue
                            source_overlap_found = True
                            competing_spans.add(overlap_edge)
                            competing_span_wall_ids[overlap_edge].update(
                                (left_wall_id, right_wall_id)
                            )

            # Defense in depth: if a future source representation proves
            # multiple owners without exposing their parent overlap, retain the
            # observed ambiguous face edge rather than silently shrinking the
            # contaminated set to zero.
            if not source_overlap_found:
                competing_spans.add(face_edge)
                competing_span_wall_ids[face_edge].update(containing)

        face_id = stable_contract_id(
            "source_room_face",
            {
                "document_id": scope.document_id,
                "revision_id": scope.revision_id,
                "source_sha256": scope.source_sha256,
                "snapshot_id": scope.snapshot_id,
                "page_id": scope.page_id,
                "decision_scope_id": scope.decision_scope_id,
                "polygon": polygon,
            },
            digest_chars=32,
        )
        polygons[face_id] = polygon
        face_walls[face_id] = tuple(sorted(set(owners)))
        face_wall_edges[face_id] = tuple(owned_edges)
        face_areas[face_id] = _polygon_area(polygon)
        if face_competing:
            directly_competing_face_ids.add(face_id)
        if face_missing:
            # Missing ownership is not localizable to a known authenticated
            # competing span. Preserve the legacy whole-scope fail-closed rule.
            missing_owner_seen = True

    if not polygons or missing_owner_seen:
        return _blocked(scope, SOURCE_ROOM_FACE_BOUNDARY_UNRESOLVED)

    # The planarizer is not stable about WHICH adjacent face receives a doubled
    # collinear edge. Stabilize the live decision by tainting every face whose
    # boundary shares positive collinear span with the actual competing edge,
    # not only the raw face that happened to carry the ambiguity this run.
    ownership_tainted_face_ids = set(directly_competing_face_ids)
    if competing_spans:
        for face_id, polygon in polygons.items():
            face_edges = tuple(
                _edge(first, polygon[(index + 1) % len(polygon)])
                for index, first in enumerate(polygon)
            )
            contaminating_wall_ids: set[str] = set()
            for face_edge in face_edges:
                for competing in competing_spans:
                    if _edges_share_positive_collinear_span(face_edge, competing):
                        contaminating_wall_ids.update(
                            competing_span_wall_ids.get(competing, ())
                        )
            if contaminating_wall_ids:
                ownership_tainted_face_ids.add(face_id)
                face_walls[face_id] = tuple(
                    sorted(set(face_walls[face_id]) | contaminating_wall_ids)
                )

    boundary_tainted_face_ids: set[str] = set()
    if boundary_local_recovery:
        for face_id, polygon in polygons.items():
            if set(face_walls[face_id]) & boundary_tainted_wall_ids:
                boundary_tainted_face_ids.add(face_id)
                continue
            if any(
                _excluded_primitive_touches_face(primitive, polygon)
                for primitive in excluded_boundary_primitives
            ):
                boundary_tainted_face_ids.add(face_id)

    ownership_clean_face_ids = (
        set(polygons) - ownership_tainted_face_ids - boundary_tainted_face_ids
    )
    if not ownership_clean_face_ids:
        return _blocked(scope, SOURCE_ROOM_FACE_BOUNDARY_UNRESOLVED)

    # Tiny/degenerate classification is evaluated only over boundary- and
    # ownership-clean faces. A contaminated giant must never make an otherwise
    # sound room appear tiny.
    largest_area = max(face_areas[face_id] for face_id in ownership_clean_face_ids)
    degenerate_face_ids = {
        face_id
        for face_id in ownership_clean_face_ids
        if face_areas[face_id] < _ABSOLUTE_DEGENERATE_AREA_PT2
        or (
            largest_area > 0.0
            and face_areas[face_id] < _TINY_RELATIVE_THRESHOLD * largest_area
        )
    }

    # Generalized pollution guard: ALL locally withheld defects combined must
    # remain a strict minority of the discovered face universe. Otherwise the
    # survivors are not independently trustworthy enough to publish.
    locally_withheld_face_ids = (
        ownership_tainted_face_ids | boundary_tainted_face_ids | degenerate_face_ids
    )
    if locally_withheld_face_ids and 2 * len(locally_withheld_face_ids) >= len(polygons):
        return _blocked(
            scope,
            SOURCE_ROOM_FACE_BOUNDARY_UNRESOLVED
            if ownership_tainted_face_ids or boundary_tainted_face_ids
            else SOURCE_ROOM_FACE_DEGENERATE,
        )

    valid_face_ids = tuple(
        sorted(
            face_id
            for face_id in ownership_clean_face_ids
            if face_id not in degenerate_face_ids
        )
    )
    if not valid_face_ids:
        return _blocked(
            scope,
            SOURCE_ROOM_FACE_BOUNDARY_UNRESOLVED
            if ownership_tainted_face_ids or boundary_tainted_face_ids
            else SOURCE_ROOM_FACE_DEGENERATE,
        )

    wall_faces: dict[str, set[str]] = {wall_id: set() for wall_id in wall_ids}
    wall_face_edges: dict[str, dict[Edge, set[str]]] = {
        wall_id: defaultdict(set) for wall_id in wall_ids
    }
    for face_id in valid_face_ids:
        for wall_id in face_walls[face_id]:
            if wall_id in wall_faces:
                wall_faces[wall_id].add(face_id)
        for wall_id, face_edge in face_wall_edges[face_id]:
            if wall_id in wall_face_edges:
                wall_face_edges[wall_id][face_edge].add(face_id)

    active_wall_ids = tuple(
        wall_id
        for wall_id in wall_ids
        if not boundary_local_recovery or wall_id not in boundary_tainted_wall_ids
    )
    parent = {wall_id: wall_id for wall_id in active_wall_ids}

    def find(wall_id: str) -> str:
        while parent[wall_id] != wall_id:
            parent[wall_id] = parent[parent[wall_id]]
            wall_id = parent[wall_id]
        return wall_id

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for index, left in enumerate(active_wall_ids):
        for right in active_wall_ids[index + 1 :]:
            if endpoints_by_wall[left] & endpoints_by_wall[right]:
                union(left, right)

    component_walls: dict[str, set[str]] = defaultdict(set)
    for wall_id in active_wall_ids:
        component_walls[find(wall_id)].add(wall_id)

    resolved_faces: set[str] = set()
    for component in component_walls.values():
        component_faces = set().union(
            *(wall_faces[wall_id] for wall_id in component)
        )
        # A long physical wall may own disjoint subedges of several rooms on
        # the same side. That is not a shared interior boundary. Require the
        # exact same planarized subedge to bound two faces before treating a
        # wall as two-sided for the anti-box/component gate.
        has_two_sided_wall = any(
            len(face_ids) == 2
            for wall_id in component
            for face_ids in wall_face_edges[wall_id].values()
        )
        if len(component_faces) >= 2 and has_two_sided_wall:
            resolved_faces.update(component_faces)

    if not resolved_faces:
        return _blocked(scope, SOURCE_ROOM_FACE_COMPONENT_AMBIGUOUS)

    output: list[SourceRoomFaceRecord] = []
    for face_id in sorted(resolved_faces):
        raw_polygon = polygons.get(face_id)
        if raw_polygon is None:
            return _blocked(scope, SOURCE_ROOM_FACE_BOUNDARY_UNRESOLVED)

        publication = _publication_boundary_ownership(
            raw_polygon,
            edge_owner=edge_owner,
            ownership_grid=ownership_grid,
            ownership_oversized=ownership_oversized,
            wall_edges=wall_edges,
        )
        if publication is None:
            return _blocked(scope, SOURCE_ROOM_FACE_BOUNDARY_UNRESOLVED)
        polygon, publication_wall_ids, _publication_edges = publication

        # Exact A->B->A retraces have zero signed area. Refuse publication if
        # cleanup changes the already-authorized face area for any other reason.
        publication_area = _polygon_area(polygon)
        if not math.isclose(
            publication_area,
            face_areas[face_id],
            rel_tol=1e-12,
            abs_tol=1e-6,
        ):
            return _blocked(scope, SOURCE_ROOM_FACE_BOUNDARY_UNRESOLVED)

        payload = {
            "face_id": face_id,
            "document_id": scope.document_id,
            "revision_id": scope.revision_id,
            "source_sha256": scope.source_sha256,
            "snapshot_id": scope.snapshot_id,
            "page_id": scope.page_id,
            "decision_scope_id": scope.decision_scope_id,
            "polygon": polygon,
            "bounding_wall_ids": publication_wall_ids,
            "area_page_pts2": face_areas[face_id],
        }
        output.append(
            SourceRoomFaceRecord(
                record_id=stable_contract_id(
                    "source_room_face_record", payload, digest_chars=32
                ),
                face_id=face_id,
                document_id=scope.document_id,
                revision_id=scope.revision_id,
                source_sha256=scope.source_sha256,
                snapshot_id=scope.snapshot_id,
                page_id=scope.page_id,
                decision_scope_id=scope.decision_scope_id,
                polygon_pdf_pts=polygon,
                bounding_wall_ids=publication_wall_ids,
                area_page_pts2=face_areas[face_id],
                boundary_wall_edges=_publication_edges,
            )
        )

    abstained = tuple(
        SourceRoomFaceAbstention(
            face_id=face_id,
            reason=(
                SOURCE_ROOM_FACE_BOUNDARY_UNRESOLVED
                if (
                    face_id in ownership_tainted_face_ids
                    or face_id in boundary_tainted_face_ids
                )
                else SOURCE_ROOM_FACE_DEGENERATE
            ),
            document_id=scope.document_id,
            revision_id=scope.revision_id,
            source_sha256=scope.source_sha256,
            snapshot_id=scope.snapshot_id,
            page_id=scope.page_id,
            decision_scope_id=scope.decision_scope_id,
            polygon_pdf_pts=polygons[face_id],
            bounding_wall_ids=face_walls[face_id],
            area_page_pts2=face_areas[face_id],
            boundary_wall_edges=face_wall_edges[face_id],
        )
        for face_id in sorted(locally_withheld_face_ids)
    )
    return SourceRoomFaceScopeResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
        records=tuple(output),
        reason_codes=(
            SOURCE_ROOM_FACE_SCOPE_RESOLVED,
            *((SOURCE_ROOM_FACE_BOUNDARY_LOCAL_RECOVERY,) if boundary_local_recovery else ()),
            *(
                (SOURCE_ROOM_FACE_UNIVERSE_PARTIAL,)
                if abstained or boundary_local_recovery
                else ()
            ),
        ),
        document_id=scope.document_id,
        revision_id=scope.revision_id,
        source_sha256=scope.source_sha256,
        snapshot_id=scope.snapshot_id,
        page_id=scope.page_id,
        decision_scope_id=scope.decision_scope_id,
        abstained_faces=abstained,
    )


def _cell_bounds(edge: Edge) -> tuple[int, int, int, int]:
    (ax, ay), (bx, by) = edge
    pad = _OWNERSHIP_GRID_PAD_PT
    cell = _OWNERSHIP_GRID_CELL_PT
    return (
        int(math.floor((min(ax, bx) - pad) / cell)),
        int(math.floor((max(ax, bx) + pad) / cell)),
        int(math.floor((min(ay, by) - pad) / cell)),
        int(math.floor((max(ay, by) + pad) / cell)),
    )


def _cell_count(bounds: tuple[int, int, int, int]) -> int:
    x0, x1, y0, y1 = bounds
    return (x1 - x0 + 1) * (y1 - y0 + 1)


def _ownership_edge_index(
    wall_edges: Mapping[str, tuple[Edge, ...]],
) -> tuple[
    dict[tuple[int, int], list[tuple[str, Edge]]],
    list[tuple[str, Edge]],
]:
    grid: dict[tuple[int, int], list[tuple[str, Edge]]] = defaultdict(list)
    oversized: list[tuple[str, Edge]] = []
    for wall_id in sorted(wall_edges):
        for edge in wall_edges[wall_id]:
            bounds = _cell_bounds(edge)
            if _cell_count(bounds) > _OWNERSHIP_GRID_MAX_CELLS_PER_EDGE:
                oversized.append((wall_id, edge))
                continue
            x0, x1, y0, y1 = bounds
            for cx in range(x0, x1 + 1):
                for cy in range(y0, y1 + 1):
                    grid[(cx, cy)].append((wall_id, edge))
    return grid, oversized


def _containing_wall_ids(
    edge: Edge,
    *,
    grid: Mapping[tuple[int, int], list[tuple[str, Edge]]],
    oversized: list[tuple[str, Edge]],
    wall_edges: Mapping[str, tuple[Edge, ...]],
) -> tuple[str, ...]:
    """Every wall with an edge that wholly contains ``edge`` (sorted, distinct)."""
    found: set[str] = set()
    bounds = _cell_bounds(edge)
    if _cell_count(bounds) > _OWNERSHIP_GRID_MAX_CELLS_PER_EDGE:
        for wall_id in sorted(wall_edges):
            if any(_edge_contains_edge(parent, edge) for parent in wall_edges[wall_id]):
                found.add(wall_id)
        return tuple(sorted(found))
    for wall_id, parent in oversized:
        if wall_id not in found and _edge_contains_edge(parent, edge):
            found.add(wall_id)
    x0, x1, y0, y1 = bounds
    for cx in range(x0, x1 + 1):
        for cy in range(y0, y1 + 1):
            for wall_id, parent in grid.get((cx, cy), ()):
                if wall_id not in found and _edge_contains_edge(parent, edge):
                    found.add(wall_id)
    return tuple(sorted(found))


def _evaluate_face_ownership(
    scope: object,
    *,
    wall_edges: Mapping[str, tuple[Edge, ...]],
    edge_owner: Mapping[Edge, str],
    raw_faces: Iterable[Iterable[Iterable[float]]],
) -> SourceRoomFaceOwnershipEvaluation:
    """Classify every planar face's edge ownership without deciding anything.

    The per-edge rule is exactly ``_unique_containing_wall_owner``: exact edge
    ownership is authoritative; otherwise the edge must be wholly contained by
    exactly one wall's edge. Competing owners and missing owners are reported,
    never resolved by first/nearest/shortest.
    """
    grid, oversized = _ownership_edge_index(wall_edges)
    owned_area: dict[str, float] = {}
    unresolved: dict[str, SourceRoomFaceOwnershipFinding] = {}
    face_edge_count = 0
    competing_edge_count = 0
    unowned_edge_count = 0

    for raw_face in raw_faces:
        polygon = _canonical_polygon(raw_face)
        if not polygon:
            continue
        face_id = stable_contract_id(
            "source_room_face",
            {
                "document_id": scope.document_id,
                "revision_id": scope.revision_id,
                "source_sha256": scope.source_sha256,
                "snapshot_id": scope.snapshot_id,
                "page_id": scope.page_id,
                "decision_scope_id": scope.decision_scope_id,
                "polygon": polygon,
            },
            digest_chars=32,
        )
        if face_id in owned_area or face_id in unresolved:
            continue
        edge_findings: list[SourceRoomFaceEdgeOwnershipFinding] = []
        for index, first in enumerate(polygon):
            second = polygon[(index + 1) % len(polygon)]
            face_edge = _edge(first, second)
            face_edge_count += 1
            if edge_owner.get(face_edge) is not None:
                continue
            walls = _containing_wall_ids(
                face_edge, grid=grid, oversized=oversized, wall_edges=wall_edges
            )
            if len(walls) == 1:
                continue
            edge_findings.append(
                SourceRoomFaceEdgeOwnershipFinding(
                    edge=face_edge,
                    kind=EDGE_OWNERSHIP_COMPETING if walls else EDGE_OWNERSHIP_NONE,
                    wall_ids=walls,
                )
            )
        area = _polygon_area(polygon)
        if not edge_findings:
            owned_area[face_id] = area
            continue
        competing = [f for f in edge_findings if f.kind == EDGE_OWNERSHIP_COMPETING]
        competing_edge_count += len(competing)
        unowned_edge_count += len(edge_findings) - len(competing)
        unresolved[face_id] = SourceRoomFaceOwnershipFinding(
            face_id=face_id,
            area_page_pts2=area,
            vertex_count=len(polygon),
            reason_codes=tuple(
                sorted(
                    {
                        SOURCE_ROOM_FACE_EDGE_OWNER_COMPETING
                        if f.kind == EDGE_OWNERSHIP_COMPETING
                        else SOURCE_ROOM_FACE_EDGE_OWNER_MISSING
                        for f in edge_findings
                    }
                )
            ),
            edge_findings=tuple(edge_findings),
            competing_wall_ids=tuple(
                sorted({wall_id for f in competing for wall_id in f.wall_ids})
            ),
        )

    largest = max(owned_area.values(), default=0.0)
    degenerate = tuple(
        sorted(
            face_id
            for face_id, area in owned_area.items()
            if area < _ABSOLUTE_DEGENERATE_AREA_PT2
            or (largest > 0.0 and area < _TINY_RELATIVE_THRESHOLD * largest)
        )
    )
    return SourceRoomFaceOwnershipEvaluation(
        status=OWNERSHIP_EVALUATION_EVALUATED,
        reason_code="ownership_evaluated",
        owned_face_ids=tuple(sorted(owned_area)),
        unresolved_faces=tuple(unresolved[face_id] for face_id in sorted(unresolved)),
        degenerate_owned_face_ids=degenerate,
        largest_owned_face_area_pt2=largest,
        face_edge_count=face_edge_count,
        competing_edge_count=competing_edge_count,
        unowned_edge_count=unowned_edge_count,
    )


def _shadow_ownership_evaluation(scope: object) -> SourceRoomFaceOwnershipEvaluation:
    """Shadow-only: never influences the scope decision; may only be unavailable."""
    try:
        if getattr(scope, "status", None) is not EvidenceResolutionStatus.CORROBORATED:
            return SourceRoomFaceOwnershipEvaluation(
                reason_code="ownership_evaluation_scope_not_corroborated"
            )
        records = tuple(getattr(scope, "records", ()) or ())
        if not records:
            return SourceRoomFaceOwnershipEvaluation(
                reason_code="ownership_evaluation_no_wall_records"
            )
        wall_edges: dict[str, tuple[Edge, ...]] = {}
        edge_owner: dict[Edge, str] = {}
        duplicate_edges: set[Edge] = set()
        for record in records:
            wall_id = _clean(getattr(record, "wall_candidate_id", ""))
            edges = _wall_edges(record)
            if not wall_id or not edges:
                continue
            wall_edges[wall_id] = edges
            for edge in edges:
                prior = edge_owner.get(edge)
                if prior is not None and prior != wall_id:
                    duplicate_edges.add(edge)
                else:
                    edge_owner[edge] = wall_id
        if not wall_edges:
            return SourceRoomFaceOwnershipEvaluation(
                reason_code="ownership_evaluation_no_wall_edges"
            )
        if duplicate_edges:
            return SourceRoomFaceOwnershipEvaluation(
                reason_code="ownership_evaluation_duplicate_edge_ownership"
            )
        if sum(len(edges) for edges in wall_edges.values()) > _OWNERSHIP_EVALUATION_MAX_EDGES:
            return SourceRoomFaceOwnershipEvaluation(
                reason_code="ownership_evaluation_scope_too_large"
            )
        raw_segments = [
            (edge[0], edge[1]) for wall_id in sorted(wall_edges) for edge in wall_edges[wall_id]
        ]
        raw_faces = extract_planar_faces(raw_segments, min_area=1e-6)
        evaluation = _evaluate_face_ownership(
            scope,
            wall_edges=wall_edges,
            edge_owner=edge_owner,
            raw_faces=raw_faces,
        )
        return replace(
            evaluation,
            scope_complete_at_evaluation=bool(getattr(scope, "scope_complete", False)),
        )
    except Exception as exc:  # pragma: no cover - shadow metadata must never break live
        return SourceRoomFaceOwnershipEvaluation(
            status=OWNERSHIP_EVALUATION_UNAVAILABLE,
            reason_code=f"ownership_evaluation_error:{type(exc).__name__}",
        )


def _derive_scope(scope: object) -> SourceRoomFaceScopeResult:
    """Live room-face derivation plus the additive ownership audit evaluation."""
    result = _derive_scope_outcome(scope)
    return replace(result, ownership_evaluation=_shadow_ownership_evaluation(scope))


def build_source_room_face_authority(
    physical_wall_candidate_authority: PhysicalWallCandidateAuthority,
) -> SourceRoomFaceAuthority:
    """Build sealed room-face results from all producer-owned wall scopes."""

    if type(physical_wall_candidate_authority) is not PhysicalWallCandidateAuthority:
        raise TypeError(
            "physical_wall_candidate_authority must be producer-owned "
            "PhysicalWallCandidateAuthority"
        )

    results: dict[_ScopeKey, SourceRoomFaceScopeResult] = {}
    for scope in physical_wall_candidate_authority._scopes.values():
        result = _derive_scope(scope)
        key: _ScopeKey = (
            _clean(scope.document_id),
            _clean(scope.revision_id),
            _clean(scope.source_sha256),
            _clean(scope.snapshot_id),
            _clean(scope.page_id),
            _clean(scope.decision_scope_id),
        )
        results[key] = result
    return SourceRoomFaceAuthority(results, _seal=_AUTHORITY_SEAL)


__all__ = [
    "EDGE_OWNERSHIP_COMPETING",
    "EDGE_OWNERSHIP_NONE",
    "OWNERSHIP_EVALUATION_EVALUATED",
    "OWNERSHIP_EVALUATION_NOT_EVALUATED",
    "OWNERSHIP_EVALUATION_UNAVAILABLE",
    "SOURCE_ROOM_FACE_BOUNDARY_UNRESOLVED",
    "SOURCE_ROOM_FACE_COMPONENT_AMBIGUOUS",
    "SOURCE_ROOM_FACE_DEGENERATE",
    "SOURCE_ROOM_FACE_DUPLICATE_EDGE",
    "SOURCE_ROOM_FACE_EDGE_OWNER_COMPETING",
    "SOURCE_ROOM_FACE_EDGE_OWNER_MISSING",
    "SOURCE_ROOM_FACE_SCHEMA_VERSION",
    "SOURCE_ROOM_FACE_SCOPE_RESOLVED",
    "SOURCE_ROOM_FACE_UNIVERSE_PARTIAL",
    "SOURCE_ROOM_FACE_SCOPE_UNAVAILABLE",
    "SourceRoomFaceAuthority",
    "SourceRoomFaceAbstention",
    "SourceRoomFaceEdgeOwnershipFinding",
    "SourceRoomFaceOwnershipEvaluation",
    "SourceRoomFaceOwnershipFinding",
    "SourceRoomFaceRecord",
    "SourceRoomFaceScopeResult",
    "SourceRoomFaceSelector",
    "build_source_room_face_authority",
]
