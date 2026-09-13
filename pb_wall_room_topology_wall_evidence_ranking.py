"""Generic, evidence-ranked promotion of W4 ``WallCandidate`` records.

W4 (``pb_wall_room_topology_wall_assembly``) assembles a ``WallCandidate``
for every chained Stage-A edge run that a real junction permits, with no
distinction at all between a genuine wall and a coincidental, undashed,
unlayered piece of geometry that happened to chain the same way -- glazing
bars, jamb/detail lines, dimension witness lines without a tagged layer,
furniture edges, annotation borders. Running the existing pipeline against
real drawings shows this is not a hypothetical: roughly 68-75% of
candidates on real Baghau/Lamu floor plans are short, isolated segments
with none of the corroborating structure a real wall run normally has.

This module does not touch W1-W4's own algorithms, and does not delete or
re-derive any candidate's own geometry. It REISSUES each ``WallCandidate``
(a frozen dataclass; reissued via ``dataclasses.replace``) with an
evidence-ranked ``status``/``confidence``/``supporting_evidence_ids``/
``reason_codes``, using the ONE fusion-status vocabulary already used
throughout W1-W10 (``EvidenceResolutionStatus`` -- no second, competing
vocabulary is introduced, per this workstream's own standing rule):

- ``ABSTAINED``  ("REJECTED_NON_WALL"): zero corroborating signals found at
  all -- an isolated line with no paired face, no fill/hatch support, no
  room-boundary participation, and no meaningful chain connectivity.
- ``CANDIDATE`` with exactly one ``supporting_evidence_ids`` entry
  ("CORROBORATED_WALL", W1's own documented CANDIDATE-with-a-single-
  corroborating-evidence-id boundary): exactly one signal found.
- ``CANDIDATE`` with two or more ``supporting_evidence_ids`` entries
  ("PROVED_WALL" without a resolved metric thickness): multiple
  independent signals agree, but no ``scale_pt_per_m`` was supplied, so a
  real ``thickness_m`` cannot be resolved.
- ``CORROBORATED`` ("PROVED_WALL" WITH a resolved metric thickness): the
  same multiple-independent-signals case, but a caller-supplied
  ``scale_pt_per_m`` (never derived here from text/project knowledge) lets
  a real ``thickness_m`` be computed from a paired-face gap, promoting
  ``thickness_authority`` to ``PDF_SCALED``. ``CORROBORATED`` status can
  never be set while ``thickness_authority`` stays ``PROVISIONAL`` --
  ``WallCandidate.__post_init__`` already forbids that combination
  (the topology spec's own Section 6/10 rule that well-evidenced identity
  never silently promotes an unmeasured quantity), so this module resolves
  a real thickness before ever using ``CORROBORATED``, rather than
  reaching for a status its own metre-space authority does not support.
- ``CANDIDATE`` with an explicit ambiguity reason code ("AMBIGUOUS"): two
  or more paired-face matches at meaningfully different, mutually
  incompatible thicknesses -- picking one would be exactly the kind of
  guess this workstream forbids.

Evidence signals, each reusing an already-proven mechanism rather than a
new one:

- **Paired approximately-parallel faces** (HIGH): reuses the same
  parallel-angle/plausible-gap/substantial-overlap test already proven in
  ``pb_vector_geometry_v130.detect_wall_pairs`` (referenced, not yet used,
  by W4's own docstring), restated here at the WallCandidate level (after
  chaining, not on raw pre-split segments) so a chain's own overall
  direction and full extent -- not one arbitrary constituent edge -- is
  what gets paired. A pair is discarded if the two candidates turn out to
  be the two opposite sides of one small closed quadrilateral (their four
  ends bridged by two other wall candidates) -- a furniture rectangle or
  an annotation border's own width/height can coincidentally fall inside
  a plausible wall-thickness range, and without this check its opposite
  sides would look exactly like one wall's two faces.
- **Wall-like fill support** (HIGH): a candidate's own centerline runs
  along (within ``_FACE_COORD_TOL_PT``-scale tolerance) one edge of a
  caller-supplied wall-like fill rectangle -- the same near-black,
  thin-and-long heuristic family already used independently in
  ``pb_hosted_opening_geometry.py`` and
  ``pb_wall_fill_internal_partition_evidence.py``, restated locally per
  this codebase's own established pattern for keeping each module
  independently testable, not imported across modules that do not share
  an architecture.
- **Room-boundary participation** (CORROBORATING): the candidate's own id
  appears in some real ``RoomCandidate.bounding_wall_candidate_ids`` --
  already computed by W5, reused as-is.
- **Connectivity into a larger, already-evidenced wall component**
  (CORROBORATING): the candidate is not a dead end (reusing ``JunctionType``
  values W3 already classified) AND shares an end node with a DIFFERENT
  wall candidate that itself carries direct paired-face or fill evidence.
  Bounded to one hop -- it never propagates from another wall's own
  connectivity or room-boundary credit -- so a whole loop of otherwise
  unevidenced lines (furniture, an annotation border) cannot vouch for
  itself merely by being closed; only genuine attachment to independently
  proven wall material counts.

Never uses raw segment length as a signal on its own, in either direction
-- a real short wall return must never be penalized for being short, and a
long isolated glazing bar or dimension line must never be promoted for
being long.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_contracts import JunctionType, RoomCandidate, WallCandidate

WALL_EVIDENCE_RANKING_SCHEMA_VERSION = "1.0.0"

# Mirrors pb_vector_geometry_v130.detect_wall_pairs' own tolerances exactly
# -- this is the same "paired approximately-parallel wall faces" test,
# restated at the WallCandidate level rather than duplicated with new
# numbers.
DEFAULT_PAIR_ANGLE_TOLERANCE_DEG = 2.5
DEFAULT_MIN_THICKNESS_PT = 1.5
DEFAULT_MAX_THICKNESS_PT = 40.0
DEFAULT_MIN_OVERLAP_FRACTION = 0.45
DEFAULT_MIN_OVERLAP_PT = 12.0

# Two paired-face thickness estimates for the SAME candidate agreeing
# within this tolerance are "the same wall band"; disagreeing beyond it is
# a genuine conflict (two different, incompatible pairings both looking
# plausible) rather than measurement noise -- mirrors the same small
# drafting-tolerance magnitude already used throughout this codebase's
# geometry modules (e.g. pb_hosted_opening_geometry's _FACE_COORD_TOL_PT
# family), not a new, unrelated constant.
DEFAULT_THICKNESS_AGREEMENT_TOL_PT = 2.0

# A candidate's own centerline running within this distance of a wall-like
# fill's own edge counts as "coincides with that fill's face" -- the same
# small-tolerance family as above.
DEFAULT_FILL_COORD_TOL_PT = 2.0

REASON_PAIRED_FACE = "paired_face_evidence"
REASON_FILL_SUPPORTED = "wall_like_fill_evidence"
REASON_ROOM_BOUNDARY = "room_boundary_participation"
REASON_CONNECTED = "connected_component_participation"
REASON_NO_EVIDENCE = "no_wall_evidence_found"
REASON_AMBIGUOUS_THICKNESS = "conflicting_paired_face_thickness_estimates"
REASON_MULTIPLE_SIGNALS_NO_SCALE = "multiple_independent_wall_signals_no_scale_authority"
REASON_MULTIPLE_SIGNALS_SCALED = "multiple_independent_wall_signals_with_resolved_thickness"


def _wall_endpoints(wall: WallCandidate) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    pts = wall.centerline_pts
    return pts[0], pts[-1]


def _wall_angle_deg(wall: WallCandidate) -> Optional[float]:
    (x1, y1), (x2, y2) = _wall_endpoints(wall)
    if x1 == x2 and y1 == y2:
        return None
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0


def _wall_length_pt(wall: WallCandidate) -> float:
    pts = wall.centerline_pts
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))


def _angle_delta(a_deg: float, b_deg: float) -> float:
    d = abs(a_deg - b_deg) % 180.0
    return min(d, 180.0 - d)


def _perpendicular_gap(a: WallCandidate, b: WallCandidate) -> Optional[float]:
    """Perpendicular distance from b's own start point to a's infinite
    line -- meaningless unless a and b are already known to be parallel."""
    (ax1, ay1), (ax2, ay2) = _wall_endpoints(a)
    (bx1, by1), _ = _wall_endpoints(b)
    ax, ay = ax2 - ax1, ay2 - ay1
    length = math.hypot(ax, ay)
    if length <= 0:
        return None
    return abs((bx1 - ax1) * ay - (by1 - ay1) * ax) / length


def _projection_overlap_pt(a: WallCandidate, b: WallCandidate) -> float:
    (ax1, ay1), (ax2, ay2) = _wall_endpoints(a)
    (bx1, by1), (bx2, by2) = _wall_endpoints(b)
    vx, vy = ax2 - ax1, ay2 - ay1
    length = math.hypot(vx, vy)
    if length <= 0:
        return 0.0
    ux, uy = vx / length, vy / length
    a0, a1 = 0.0, length
    vals = [
        (bx1 - ax1) * ux + (by1 - ay1) * uy,
        (bx2 - ax1) * ux + (by2 - ay1) * uy,
    ]
    b0, b1 = min(vals), max(vals)
    return max(0.0, min(a1, b1) - max(a0, b0))


def _node_to_wall_ids(walls: Sequence[WallCandidate]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for w in walls:
        for node_id in w.end_node_ids:
            out.setdefault(node_id, []).append(w.candidate_id)
    return out


def _shares_enclosing_quadrilateral(
    a: WallCandidate, b: WallCandidate, node_to_walls: Dict[str, List[str]]
) -> bool:
    """True if a and b are the two opposite sides of a simple closed
    quadrilateral -- i.e. a's two ends are bridged to b's two ends by two
    OTHER wall candidates (a-c-b-d-a). A rectangle's own width or height
    can coincidentally fall inside a plausible wall-thickness range
    (furniture, an annotation border, a small table), which would
    otherwise make ``find_paired_wall_faces`` treat its opposite sides as
    one wall's two faces. Genuine double-line wall corners do not trip
    this: the outer face's corner neighbour is the next wall's OUTER face,
    never the SAME wall's own inner face, so the two faces' ends are never
    both bridged by the same pair of connecting walls."""
    a1, a2 = a.end_node_ids
    b1, b2 = b.end_node_ids
    neighbors_a1 = set(node_to_walls.get(a1, ())) - {a.candidate_id, b.candidate_id}
    neighbors_a2 = set(node_to_walls.get(a2, ())) - {a.candidate_id, b.candidate_id}
    neighbors_b1 = set(node_to_walls.get(b1, ())) - {a.candidate_id, b.candidate_id}
    neighbors_b2 = set(node_to_walls.get(b2, ())) - {a.candidate_id, b.candidate_id}
    straight = bool(neighbors_a1 & neighbors_b1) and bool(neighbors_a2 & neighbors_b2)
    crossed = bool(neighbors_a1 & neighbors_b2) and bool(neighbors_a2 & neighbors_b1)
    return straight or crossed


def find_paired_wall_faces(
    walls: Sequence[WallCandidate],
    *,
    angle_tolerance_deg: float = DEFAULT_PAIR_ANGLE_TOLERANCE_DEG,
    min_thickness_pt: float = DEFAULT_MIN_THICKNESS_PT,
    max_thickness_pt: float = DEFAULT_MAX_THICKNESS_PT,
    min_overlap_fraction: float = DEFAULT_MIN_OVERLAP_FRACTION,
    min_overlap_pt: float = DEFAULT_MIN_OVERLAP_PT,
) -> Dict[str, List[Tuple[str, float]]]:
    """candidate_id -> [(other_candidate_id, gap_pt), ...] paired-face
    matches. Reuses exactly pb_vector_geometry_v130.detect_wall_pairs' own
    parallel/gap/overlap test, restated at the WallCandidate level, then
    excludes any pair that turns out to be the two opposite sides of one
    small closed quadrilateral rather than one wall's two faces."""
    node_to_walls = _node_to_wall_ids(walls)
    out: Dict[str, List[Tuple[str, float]]] = {w.candidate_id: [] for w in walls}
    angles = {w.candidate_id: _wall_angle_deg(w) for w in walls}
    lengths = {w.candidate_id: _wall_length_pt(w) for w in walls}
    for i, a in enumerate(walls):
        angle_a = angles[a.candidate_id]
        if angle_a is None:
            continue
        for b in walls[i + 1 :]:
            angle_b = angles[b.candidate_id]
            if angle_b is None:
                continue
            if _angle_delta(angle_a, angle_b) > angle_tolerance_deg:
                continue
            gap = _perpendicular_gap(a, b)
            if gap is None or not (min_thickness_pt <= gap <= max_thickness_pt):
                continue
            overlap = _projection_overlap_pt(a, b)
            shorter = min(lengths[a.candidate_id], lengths[b.candidate_id])
            if overlap < min_overlap_pt or overlap < min_overlap_fraction * shorter:
                continue
            if _shares_enclosing_quadrilateral(a, b, node_to_walls):
                continue
            out[a.candidate_id].append((b.candidate_id, gap))
            out[b.candidate_id].append((a.candidate_id, gap))
    return out


def _fill_supported(wall: WallCandidate, fills: Sequence[Tuple[float, float, float, float]], tol: float) -> bool:
    (x1, y1), (x2, y2) = _wall_endpoints(wall)
    for fx0, fy0, fx1, fy1 in fills:
        # Horizontal wall run tested against a horizontal fill edge (top or
        # bottom), vertical run against a vertical fill edge (left or
        # right) -- a wall candidate lying along either long edge of a real
        # wall-like fill rectangle is evidenced by that fill.
        if abs(y1 - y2) <= tol and (abs(y1 - fy0) <= tol or abs(y1 - fy1) <= tol):
            if min(x1, x2) >= fx0 - tol and max(x1, x2) <= fx1 + tol:
                return True
        if abs(x1 - x2) <= tol and (abs(x1 - fx0) <= tol or abs(x1 - fx1) <= tol):
            if min(y1, y2) >= fy0 - tol and max(y1, y2) <= fy1 + tol:
                return True
    return False


def _is_dead_end(wall: WallCandidate) -> bool:
    isolated_types = (JunctionType.UNRESOLVED,)
    a, b = wall.junction_types
    dead_end_a = a == JunctionType.ENDPOINT or a in isolated_types
    dead_end_b = b == JunctionType.ENDPOINT or b in isolated_types
    return dead_end_a and dead_end_b


def _point_to_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    vx, vy = bx - ax, by - ay
    length_sq = vx * vx + vy * vy
    if length_sq <= 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / length_sq))
    cx, cy = ax + t * vx, ay + t * vy
    return math.hypot(px - cx, py - cy)


def _touches_wall_interior(point: Tuple[float, float], other: WallCandidate, tol: float) -> bool:
    """True if ``point`` lies on (within ``tol`` of) any part of ``other``'s
    own centerline run -- including a MID-SPAN point, not just its two
    outer ends. A branch attaching to the SIDE of a long, unbroken wall
    run (a genuine T-junction where the through-wall was chained past the
    branch as one interior vertex rather than ending there) never shows up
    in that through-wall's own ``end_node_ids``, so the node-id adjacency
    alone misses it; this spatial check catches that case."""
    px, py = point
    pts = other.centerline_pts
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        if _point_to_segment_distance(px, py, ax, ay, bx, by) <= tol:
            return True
    return False


def _connected_to_evidenced_neighbor(
    wall: WallCandidate,
    node_to_walls: Dict[str, List[str]],
    directly_evidenced_ids: "set[str]",
    walls_by_id: Dict[str, WallCandidate],
    interior_touch_tol: float,
) -> bool:
    """True if this candidate attaches -- at a shared end node, OR at a
    mid-span point along another wall's own run -- to a DIFFERENT wall
    candidate that itself carries DIRECT evidence (a paired face or a
    wall-like fill -- never room-boundary or connectivity itself, so this
    never chains transitively beyond one hop). A bare junction type that
    is merely "not a dead end" is not enough on its own: a closed
    quadrilateral of unevidenced lines (furniture, an annotation border)
    also has non-dead-end junction types at every corner, purely from
    closing the loop, with nothing to actually corroborate any one side."""
    if _is_dead_end(wall):
        return False
    for node_id in wall.end_node_ids:
        for other_id in node_to_walls.get(node_id, ()):
            if other_id == wall.candidate_id:
                continue
            if other_id in directly_evidenced_ids:
                return True
    for own_point in _wall_endpoints(wall):
        for other_id in directly_evidenced_ids:
            if other_id == wall.candidate_id:
                continue
            other = walls_by_id[other_id]
            if _touches_wall_interior(own_point, other, interior_touch_tol):
                return True
    return False


def rank_wall_candidates(
    walls: Sequence[WallCandidate],
    *,
    rooms: Sequence[RoomCandidate] = (),
    wall_like_fills: Sequence[Tuple[float, float, float, float]] = (),
    scale_pt_per_m: Optional[float] = None,
    angle_tolerance_deg: float = DEFAULT_PAIR_ANGLE_TOLERANCE_DEG,
    min_thickness_pt: float = DEFAULT_MIN_THICKNESS_PT,
    max_thickness_pt: float = DEFAULT_MAX_THICKNESS_PT,
    min_overlap_fraction: float = DEFAULT_MIN_OVERLAP_FRACTION,
    min_overlap_pt: float = DEFAULT_MIN_OVERLAP_PT,
    fill_coord_tol_pt: float = DEFAULT_FILL_COORD_TOL_PT,
    thickness_agreement_tol_pt: float = DEFAULT_THICKNESS_AGREEMENT_TOL_PT,
) -> List[WallCandidate]:
    """Reissue every wall candidate with an evidence-ranked status. Never
    drops a candidate; never invents length as evidence; never resolves a
    metric thickness without a caller-supplied scale_pt_per_m."""
    pairs = find_paired_wall_faces(
        walls,
        angle_tolerance_deg=angle_tolerance_deg,
        min_thickness_pt=min_thickness_pt,
        max_thickness_pt=max_thickness_pt,
        min_overlap_fraction=min_overlap_fraction,
        min_overlap_pt=min_overlap_pt,
    )
    room_boundary_ids = {wid for room in rooms for wid in room.bounding_wall_candidate_ids}
    fill_supported_ids = {
        w.candidate_id for w in walls if _fill_supported(w, wall_like_fills, fill_coord_tol_pt)
    }
    # "Connectivity into a larger wall component" only propagates from a
    # neighbour's DIRECT, in-the-material evidence (paired face or fill) --
    # never from another wall's own room-boundary or connectivity credit,
    # which would let an entire unevidenced loop launder itself into
    # existence by having its members vouch for each other.
    directly_evidenced_ids = {wid for wid in pairs if pairs[wid]} | fill_supported_ids
    node_to_walls = _node_to_wall_ids(walls)
    walls_by_id = {w.candidate_id: w for w in walls}

    out: List[WallCandidate] = []
    for wall in walls:
        signals: List[str] = []
        own_pairs = pairs.get(wall.candidate_id, [])
        if own_pairs:
            signals.append(REASON_PAIRED_FACE)
        if wall.candidate_id in fill_supported_ids:
            signals.append(REASON_FILL_SUPPORTED)
        if wall.candidate_id in room_boundary_ids:
            signals.append(REASON_ROOM_BOUNDARY)
        if _connected_to_evidenced_neighbor(
            wall,
            node_to_walls,
            directly_evidenced_ids - {wall.candidate_id},
            walls_by_id,
            fill_coord_tol_pt,
        ):
            signals.append(REASON_CONNECTED)

        ambiguous = False
        if len(own_pairs) >= 2:
            gaps = [g for _, g in own_pairs]
            if max(gaps) - min(gaps) > thickness_agreement_tol_pt:
                ambiguous = True

        if ambiguous:
            # own_pairs' own partner id is not always a reliable per-object
            # key on real, messy geometry: W4's own candidate_id generation
            # (unmodified here, out of this module's scope) can assign the
            # same id to two distinct chains that happen to share both
            # outer endpoints -- confirmed on real Baghau data. Folding the
            # gap into each entry keeps genuinely distinct measurements
            # distinguishable instead of colliding into one string, and the
            # dict.fromkeys pass guarantees WallCandidate's own uniqueness
            # requirement holds even if two entries still coincide exactly.
            raw_ids = (f"{REASON_PAIRED_FACE}:{oid}:{round(gap, 4)}" for oid, gap in own_pairs)
            out.append(
                replace(
                    wall,
                    status=EvidenceResolutionStatus.CANDIDATE,
                    confidence=max(wall.confidence, 0.3),
                    supporting_evidence_ids=tuple(dict.fromkeys(raw_ids)),
                    reason_codes=tuple(wall.reason_codes) + (REASON_AMBIGUOUS_THICKNESS,),
                )
            )
            continue

        if not signals:
            out.append(
                replace(
                    wall,
                    status=EvidenceResolutionStatus.ABSTAINED,
                    confidence=0.0,
                    reason_codes=tuple(wall.reason_codes) + (REASON_NO_EVIDENCE,),
                )
            )
            continue

        evidence_ids = tuple(signals)
        if len(signals) == 1:
            out.append(
                replace(
                    wall,
                    status=EvidenceResolutionStatus.CANDIDATE,
                    confidence=max(wall.confidence, 0.5),
                    supporting_evidence_ids=evidence_ids,
                    reason_codes=tuple(wall.reason_codes),
                )
            )
            continue

        # Two or more independent signals agree. Promote to CORROBORATED
        # only if a real thickness can be resolved from paired-face
        # evidence and a caller-supplied scale -- WallCandidate's own
        # validation forbids CORROBORATED status while thickness_authority
        # stays PROVISIONAL (the topology spec's Section 6/10 rule that
        # well-evidenced identity never silently promotes an unmeasured
        # quantity), so this never sets CORROBORATED without also
        # resolving a real thickness_m first.
        if own_pairs and scale_pt_per_m and scale_pt_per_m > 0:
            thickness_m = statistics.median(g for _, g in own_pairs) / scale_pt_per_m
            out.append(
                replace(
                    wall,
                    status=EvidenceResolutionStatus.CORROBORATED,
                    confidence=max(wall.confidence, 0.85),
                    supporting_evidence_ids=evidence_ids,
                    reason_codes=tuple(wall.reason_codes) + (REASON_MULTIPLE_SIGNALS_SCALED,),
                    thickness_m=round(thickness_m, 4),
                    thickness_authority=MeasurementAuthorityType.PDF_SCALED,
                )
            )
            continue

        out.append(
            replace(
                wall,
                status=EvidenceResolutionStatus.CANDIDATE,
                confidence=max(wall.confidence, 0.7),
                supporting_evidence_ids=evidence_ids,
                reason_codes=tuple(wall.reason_codes) + (REASON_MULTIPLE_SIGNALS_NO_SCALE,),
            )
        )
    return out
