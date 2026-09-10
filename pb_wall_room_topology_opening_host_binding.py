"""W7: opening-host topology binding from WallCandidate dangling-end gaps.

Detects candidate physical-opening locations purely from evidence already
present in W4's own ``WallCandidate`` records -- a real wall run drawn with a
door/window gap in plan view produces TWO separate ``WallCandidate`` chains
(Stage-A's own collinear/gap snapping in ``pb_wall_room_topology_stage_a``
already closes any gap at or below its own tolerance, so a *surviving* gap
between two dangling ``JunctionType.ENDPOINT`` ends is itself the evidence,
not an inference layered on top of it).

Deliberately does NOT:
- call into, wrap, or duplicate Cursor's frozen schedule/tag-count opening
  extraction (``pb_opening_schedule_v171`` and friends), or the v170-v175
  opening-evidence/production/reconciliation stack. Those modules carry no
  genuine plan-view geometric position for an opening (their
  ``position_along_wall_m`` is label/text-derived, not derived from real
  wall-line geometry -- confirmed by inspection before writing this module),
  so there is nothing safe to spatially bind from them yet. Integrating a
  future geometric-to-schedule match is out of scope for this stage.
- assign a door/window/type classification, a schedule tag, or a quantity;
- emit ``QuantityEvidence`` or any deduction;
- wire into any live extraction path;
- rewrite ``pb_opening_deduction_pipeline``'s existing bbox/fallback binding.

FAIL-CLOSED / AMBIGUITY
------------------------
A genuine physical opening interrupts exactly one wall run, but at THIS
stage of construction that run is represented as two independent
``WallCandidate`` chains (there is no evidence yet that lets us prove they
are "the same wall, interrupted" rather than two unrelated, coincidentally
collinear walls). Rather than arbitrarily picking one of the two chains as
"the" host -- which is exactly the kind of guess this workstream forbids --
every detected gap is recorded as ``host_status="ambiguous_host"`` with
BOTH (or, for a rarer 3+-way cluster, all) bounding wall ids listed in
``candidate_wall_ids_considered``. ``host_status="hosted"`` is therefore not
reachable from this detector alone; a later, separately-approved stage that
adds genuine single-wall opening evidence (e.g. from real plan-view door
swing/window-sill geometry, once available) can resolve individual cases to
"hosted" without changing this module's own behaviour. A lone dangling wall
end with no plausible collinear partner is NOT reported as an opening at
all -- an unpaired free end is just where a wall run stops (the drawing's
own extent, an intentionally open wall, etc.); nothing here says it is an
opening, so nothing here claims it is.

ONE PHYSICAL OPENING NEVER BECOMES TWO
-----------------------------------------
Each dangling end can belong to at most one gap cluster: clusters are
computed as the connected components of a "plausible collinear partner"
graph over ends (union-find, matching the pattern used for wall-chain
assembly in W4), never as one record per ordered pair. So a gap between
wall A and wall B produces exactly one ``OpeningHostCandidate``, not one
from each side.
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

from pb_migration_contracts import stable_contract_id
from pb_wall_room_topology_contracts import (
    JunctionType,
    OpeningHostCandidate,
    WallCandidate,
)
from pb_wall_room_topology_stage_a import (
    DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG,
    DEFAULT_GAP_SNAP_TOLERANCE_PT,
)

REASON_COLLINEAR_DANGLING_END_GAP = "collinear_dangling_end_gap"
REASON_GAP_CLUSTER_SIZE_GE_3 = "gap_cluster_size_three_or_more"
REASON_GAP_AT_OR_BELOW_SNAP_TOLERANCE = "gap_at_or_below_stage_a_snap_tolerance"

# A gap at/below Stage-A's own snap tolerance should already have been
# merged into one continuous WallCandidate; a survivor at that scale is
# unusual (not impossible -- e.g. a snap that only applied on one axis of a
# near-diagonal run) so it is still reported, just flagged with the reason
# code above rather than treated as an ordinary-confidence gap.
_SNAP_TOLERANCE_PT = DEFAULT_GAP_SNAP_TOLERANCE_PT
_PERPENDICULAR_OFFSET_TOLERANCE_PT = DEFAULT_GAP_SNAP_TOLERANCE_PT
_COLLINEAR_ANGLE_TOLERANCE_DEG = DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG

# A gap wider than half of either bounding wall's own centerline length is
# not a plausible single-opening interruption of that wall -- this is a
# purely relative, non-benchmark-tuned sanity bound (no absolute metre
# guess), since page-point-to-metre scale may not be resolved for either
# wall at this stage.
_MAX_GAP_RELATIVE_TO_SHORTER_WALL_PT = 0.5


class _UnionFind:
    def __init__(self, items: Sequence[str]) -> None:
        self._parent: Dict[str, str] = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_a] = root_b


def _dist(p: Tuple[float, float], q: Tuple[float, float]) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _outward_direction(centerline_pts: Sequence[Tuple[float, float]], end_index: int) -> Tuple[float, float]:
    """Unit vector at end 0 or end 1 pointing AWAY from the wall body."""
    if end_index == 0:
        p_from, p_to = centerline_pts[1], centerline_pts[0]
    else:
        p_from, p_to = centerline_pts[-2], centerline_pts[-1]
    dx, dy = p_to[0] - p_from[0], p_to[1] - p_from[1]
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _angle_between_deg(u: Tuple[float, float], v: Tuple[float, float]) -> float:
    dot = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
    return math.degrees(math.acos(dot))


class _DanglingEnd:
    __slots__ = ("wall_id", "end_index", "point", "direction", "wall_length_pt")

    def __init__(
        self,
        wall_id: str,
        end_index: int,
        point: Tuple[float, float],
        direction: Tuple[float, float],
        wall_length_pt: float,
    ) -> None:
        self.wall_id = wall_id
        self.end_index = end_index
        self.point = point
        self.direction = direction
        self.wall_length_pt = wall_length_pt


def _collect_dangling_ends(walls: Sequence[WallCandidate]) -> List[_DanglingEnd]:
    ends: List[_DanglingEnd] = []
    for wall in walls:
        centerline_pts = wall.centerline_pts
        wall_length_pt = sum(
            _dist(centerline_pts[i], centerline_pts[i + 1]) for i in range(len(centerline_pts) - 1)
        )
        for end_index in (0, 1):
            if wall.junction_types[end_index] != JunctionType.ENDPOINT:
                continue
            point = centerline_pts[0] if end_index == 0 else centerline_pts[-1]
            direction = _outward_direction(centerline_pts, end_index)
            ends.append(_DanglingEnd(wall.candidate_id, end_index, point, direction, wall_length_pt))
    return ends


def _plausible_gap_partners(end_a: _DanglingEnd, end_b: _DanglingEnd) -> bool:
    """True when two dangling ends look like the two sides of one interrupted wall run."""
    if end_a.wall_id == end_b.wall_id:
        return False

    gap = _dist(end_a.point, end_b.point)
    if gap <= 0.0:
        return False

    shorter_wall_length = min(end_a.wall_length_pt, end_b.wall_length_pt)
    if shorter_wall_length > 0.0 and gap > _MAX_GAP_RELATIVE_TO_SHORTER_WALL_PT * shorter_wall_length:
        return False

    # The two ends must extend AWAY from each other along (approximately)
    # the same line: their outward directions are close to anti-parallel...
    angle = _angle_between_deg(end_a.direction, end_b.direction)
    if angle < 180.0 - _COLLINEAR_ANGLE_TOLERANCE_DEG:
        return False

    # ...and the segment joining them must run along that same direction
    # (rules out two parallel-but-offset walls on different rows/columns).
    joining = (end_b.point[0] - end_a.point[0], end_b.point[1] - end_a.point[1])
    joining_length = math.hypot(*joining)
    if joining_length <= 0.0:
        return False
    joining_unit = (joining[0] / joining_length, joining[1] / joining_length)
    joining_angle = min(
        _angle_between_deg(end_a.direction, joining_unit),
        _angle_between_deg(end_a.direction, (-joining_unit[0], -joining_unit[1])),
    )
    if joining_angle > _COLLINEAR_ANGLE_TOLERANCE_DEG:
        return False

    return True


def _perpendicular_offset_ok(end_a: _DanglingEnd, end_b: _DanglingEnd) -> bool:
    """Reject ends that are collinear in direction but offset sideways from
    each other's own line by more than Stage-A's own snap tolerance."""
    dx, dy = end_a.direction
    to_b = (end_b.point[0] - end_a.point[0], end_b.point[1] - end_a.point[1])
    # Perpendicular component of (b - a) relative to a's own direction line.
    perpendicular = abs(to_b[0] * (-dy) + to_b[1] * dx)
    return perpendicular <= _PERPENDICULAR_OFFSET_TOLERANCE_PT


def detect_opening_host_candidates(walls: Sequence[WallCandidate]) -> List[OpeningHostCandidate]:
    """Main W7 entry point for one viewport's already-assembled WallCandidates.

    Returns one ``OpeningHostCandidate`` per detected dangling-end gap
    cluster. Every returned record has ``host_status="ambiguous_host"``
    (see module docstring for why "hosted" is not reachable here).
    """
    ends = _collect_dangling_ends(walls)
    if len(ends) < 2:
        return []

    end_key = lambda e: (e.wall_id, e.end_index)  # noqa: E731
    keys = [end_key(e) for e in ends]
    uf = _UnionFind([f"{w}:{i}" for w, i in keys])

    def uf_key(e: _DanglingEnd) -> str:
        return f"{e.wall_id}:{e.end_index}"

    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            if _plausible_gap_partners(ends[i], ends[j]) and _perpendicular_offset_ok(ends[i], ends[j]):
                uf.union(uf_key(ends[i]), uf_key(ends[j]))

    clusters: Dict[str, List[_DanglingEnd]] = {}
    for end in ends:
        clusters.setdefault(uf.find(uf_key(end)), []).append(end)

    candidates: List[OpeningHostCandidate] = []
    for members in clusters.values():
        if len(members) < 2:
            continue  # an unpaired dangling end is not opening evidence.

        member_wall_ids = sorted({m.wall_id for m in members})
        if len(member_wall_ids) < 2:
            continue  # both ends belong to the same wall -- not a real gap.

        min_gap = min(
            _dist(members[a].point, members[b].point)
            for a in range(len(members))
            for b in range(a + 1, len(members))
        )

        reason_codes: List[str] = [REASON_COLLINEAR_DANGLING_END_GAP]
        if len(member_wall_ids) >= 3:
            reason_codes.append(REASON_GAP_CLUSTER_SIZE_GE_3)
        if min_gap <= _SNAP_TOLERANCE_PT:
            reason_codes.append(REASON_GAP_AT_OR_BELOW_SNAP_TOLERANCE)

        gap_width_m = _resolve_gap_width_m(members, walls_by_id={w.candidate_id: w for w in walls})

        confidence = 0.6 if len(member_wall_ids) == 2 else 0.35
        if REASON_GAP_AT_OR_BELOW_SNAP_TOLERANCE in reason_codes:
            confidence = min(confidence, 0.3)

        host_candidate_id = stable_contract_id(
            "openinghost",
            {
                "members": sorted(f"{m.wall_id}:{m.end_index}" for m in members),
            },
        )

        candidates.append(
            OpeningHostCandidate(
                host_candidate_id=host_candidate_id,
                wall_candidate_id=member_wall_ids[0],
                position_along_wall_m=None,
                gap_width_m=gap_width_m,
                host_status="ambiguous_host",
                candidate_wall_ids_considered=tuple(member_wall_ids),
                confidence=confidence,
                reason_codes=tuple(reason_codes),
            )
        )

    candidates.sort(key=lambda c: c.host_candidate_id)
    return candidates


def _resolve_gap_width_m(
    members: Sequence[_DanglingEnd], *, walls_by_id: Dict[str, WallCandidate]
) -> float | None:
    """Derive the gap's metre width from any bounding wall whose own
    length_m is already resolved, using that wall's own pt-per-metre ratio
    (never a global or invented scale). Returns None if no bounding wall in
    this cluster has a resolved length_m yet -- fail-closed, not guessed."""
    min_gap_pt = min(
        _dist(members[a].point, members[b].point)
        for a in range(len(members))
        for b in range(a + 1, len(members))
    )
    ratios: List[float] = []
    for member in members:
        wall = walls_by_id.get(member.wall_id)
        if wall is None or wall.length_m is None or member.wall_length_pt <= 0.0:
            continue
        ratios.append(wall.length_m / member.wall_length_pt)
    if not ratios:
        return None
    average_ratio = sum(ratios) / len(ratios)
    return round(min_gap_pt * average_ratio, 4)
