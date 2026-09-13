"""Generic wall-BAND consistency evidence -- research module, NOT wired into
W4's WallCandidate construction and NOT wired into HostedOpeningWallBinding.

This replaces the tier semantics from an earlier research pass (PR #273's
``pb_wall_room_topology_wall_evidence_ranking``), which independent
validation proved epistemically unsound in specific, confirmed ways:

- ``room_boundary`` participation and one-hop ``connected_component``
  participation were counted as independent corroborating signals when they
  are not: a room face is built FROM the same wall candidates it would then
  "corroborate" (circular), and a candidate merely touching an already-
  evidenced neighbour is not itself evidenced by anything except contact.
- A single, one-off paired-face measurement was accepted as strong evidence
  on its own once a caller supplied a scale authority, with no check that
  the measured gap was anything other than a coincidental pairing (a room-
  width pair, a glazing/frame gap, a furniture rectangle's own short side).

This module's own standard for "independent evidence" is stricter and is
the central design choice here: a signal counts only when it comes from
geometry OTHER than the candidate's own single local measurement --
specifically, either (a) the SAME thickness recurring at OTHER, spatially
distinct locations in the drawing (``REPEATED_THICKNESS_MODE``), or (b) an
ADJACENT wall candidate, linked by real topology (a shared corner/junction
or a plausible opening gap), independently showing the same thickness
(``BAND_CONTINUITY``). Neither of these can be produced by one candidate's
own geometry in isolation, which is what makes them genuinely independent of
each other and of the candidate's own local pairing.

No new evidence/status vocabulary: every status value is
``pb_migration_contracts.EvidenceResolutionStatus``, matching the "AMBIGUOUS
candidates are CANDIDATE with an explanatory reason code" convention this
codebase already documents for W1 (there is no separate AMBIGUOUS status
value to introduce).

No project-specific or benchmark-fitted thresholds: every tolerance here is
either a relative/dimensionless fraction (drafting-tolerance-scale, matching
the same small-magnitude family already used throughout this codebase's own
geometry modules), or -- for the one genuinely scale-dependent signal,
``SCALE_PLAUSIBLE`` -- a broad, generic physical range (spans everything
from a stud partition to a thick masonry wall) that is never, on its own,
sufficient for any status promotion.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_contracts import JunctionType, WallCandidate

WALL_BAND_EVIDENCE_SCHEMA_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Tolerances. Every one below is a RELATIVE fraction or a small drafting-
# tolerance-scale absolute value already used elsewhere in this codebase's
# own geometry modules -- never a benchmark-fitted or project-specific
# number. See each constant's own comment for its specific justification.
# ---------------------------------------------------------------------------

DEFAULT_PAIR_ANGLE_TOLERANCE_DEG = 2.5
DEFAULT_MIN_THICKNESS_PT = 1.5
DEFAULT_MAX_THICKNESS_PT = 40.0
DEFAULT_MIN_OVERLAP_FRACTION = 0.45
DEFAULT_MIN_OVERLAP_PT = 12.0

# A paired-face gap is sampled at these fixed arc-length fractions along the
# shorter wall's own overlap region (not at whichever raw vertices happen to
# exist -- see pb_wall_room_topology_wall_assembly._shape_fingerprint for the
# same fixed-fraction-sampling rationale applied there to identity). Deciles,
# a generic, round choice.
_GAP_SAMPLE_FRACTIONS = (0.1, 0.3, 0.5, 0.7, 0.9)

# A paired-face gap's own samples must agree within this RELATIVE fraction
# of their mean to count as "one locally consistent wall band" rather than
# "two lines that happen to be parallel-ish over part of their length" (a
# stepped/ladder shape, a coincidental near-miss). Relative, not absolute --
# a thin partition and a thick masonry wall have very different absolute
# pt magnitudes but the SAME expectation of staying consistent along their
# own run.
DEFAULT_LOCAL_CONSISTENCY_RELATIVE_TOLERANCE = 0.12

# Two independently-measured mean gaps (from geometrically DISTINCT,
# non-overlapping candidates) belong to the same recurring thickness MODE
# when they agree within this relative fraction of each other. Same
# magnitude as the local-consistency tolerance above, deliberately: both are
# "does this measured thickness agree with another measurement of what
# should be the same physical quantity," just at two different scopes (one
# wall's own run vs. across the whole drawing).
DEFAULT_MODE_RELATIVE_TOLERANCE = 0.12

# A specific (gap, overlap-length) shape recurring this many times or more,
# at geometrically DISTINCT non-overlapping locations, is treated as a
# stamped/copied symbol (furniture, a hatch tick, a glazing-bar ladder, a
# grid of identical stubs) rather than field-built wall material -- real
# wall runs are each individually dimensioned to fit their own opening/room,
# so an EXACT length match recurring three-plus times is a materially
# different claim than a mere thickness match recurring (which real
# construction unremarkably does, at every wall of the same specified type).
DEFAULT_SYMBOL_REPETITION_COUNT = 3

# Rounding precision (in pt) used only to bucket a (gap, overlap) pair into
# a repetition-detection key -- coarse enough to treat "the same symbol,
# drawn at slightly different sub-pixel positions" as one shape, fine enough
# not to conflate two genuinely different short returns. Matches this
# codebase's own small-drafting-tolerance-magnitude family (e.g. Stage A's
# own 2.5pt gap-snap tolerance).
_SYMBOL_SHAPE_ROUND_PT = 2.0

# Broad, generic physical-plausibility band for a wall's own thickness, once
# a real scale authority is available -- spans a stud partition (~50mm)
# through a thick masonry/stone wall (~600mm). Deliberately wide: this is a
# sanity check against gross scale errors, never a discriminator on its own
# (a room-width pair or a glazing gap can each individually still fall
# inside a band this wide -- see module docstring on why this is never
# sufficient alone).
DEFAULT_MIN_PLAUSIBLE_THICKNESS_M = 0.04
DEFAULT_MAX_PLAUSIBLE_THICKNESS_M = 0.6

REASON_NO_EVIDENCE = "no_wall_band_evidence_found"
REASON_SYMBOL_LIKE = "repeated_symbol_like_shape_rejected"
REASON_INCONSISTENT_LOCAL_THICKNESS = "paired_face_gap_not_locally_consistent"
REASON_ISOLATED_LOCAL_PAIR = "locally_consistent_pair_with_no_corroborating_channel"
REASON_REPEATED_MODE = "repeated_thickness_mode_at_distinct_location"
REASON_BAND_CONTINUITY = "band_continuity_through_adjacent_topology"
REASON_SCALE_PLAUSIBLE = "scale_aware_thickness_plausible"
REASON_SCALE_IMPLAUSIBLE = "scale_aware_thickness_implausible"


# ---------------------------------------------------------------------------
# Basic wall geometry helpers (restated locally per this codebase's own
# established convention of not cross-importing private helpers between
# modules that do not share an architecture).
# ---------------------------------------------------------------------------


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


def _point_at_arc_length(points: Sequence[Tuple[float, float]], target: float) -> Tuple[float, float]:
    if target <= 0.0:
        return points[0]
    travelled = 0.0
    for i in range(len(points) - 1):
        ax, ay = points[i]
        bx, by = points[i + 1]
        seg_len = math.hypot(bx - ax, by - ay)
        if seg_len <= 0.0:
            continue
        if travelled + seg_len >= target:
            t = (target - travelled) / seg_len
            return (ax + t * (bx - ax), ay + t * (by - ay))
        travelled += seg_len
    return points[-1]


def _perpendicular_distance_to_line(
    point: Tuple[float, float], line_a: Tuple[float, float], line_b: Tuple[float, float]
) -> Optional[float]:
    ax, ay = line_a
    bx, by = line_b
    lx, ly = bx - ax, by - ay
    length = math.hypot(lx, ly)
    if length <= 0.0:
        return None
    px, py = point
    return abs((px - ax) * ly - (py - ay) * lx) / length


def _projection_overlap_pt(a: WallCandidate, b: WallCandidate) -> float:
    (ax1, ay1), (ax2, ay2) = _wall_endpoints(a)
    (bx1, by1), (bx2, by2) = _wall_endpoints(b)
    vx, vy = ax2 - ax1, ay2 - ay1
    length = math.hypot(vx, vy)
    if length <= 0.0:
        return 0.0
    ux, uy = vx / length, vy / length
    a0, a1 = 0.0, length
    vals = [
        (bx1 - ax1) * ux + (by1 - ay1) * uy,
        (bx2 - ax1) * ux + (by2 - ay1) * uy,
    ]
    b0, b1 = min(vals), max(vals)
    return max(0.0, min(a1, b1) - max(a0, b0))


def _overlap_interval_pt(a: WallCandidate, b: WallCandidate) -> Optional[Tuple[float, float]]:
    """The overlapping sub-range of ``a``'s own [0, length] extent that
    projects onto ``b`` -- the region multi-point gap sampling is confined
    to, so a sample is never taken past where ``b`` actually exists."""
    (ax1, ay1), (ax2, ay2) = _wall_endpoints(a)
    (bx1, by1), (bx2, by2) = _wall_endpoints(b)
    vx, vy = ax2 - ax1, ay2 - ay1
    length = math.hypot(vx, vy)
    if length <= 0.0:
        return None
    ux, uy = vx / length, vy / length
    vals = [
        (bx1 - ax1) * ux + (by1 - ay1) * uy,
        (bx2 - ax1) * ux + (by2 - ay1) * uy,
    ]
    lo, hi = max(0.0, min(vals)), min(length, max(vals))
    if hi <= lo:
        return None
    return (lo, hi)


# ---------------------------------------------------------------------------
# Face-pair hypotheses with multi-point local-consistency sampling.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FacePairHypothesis:
    wall_a_id: str
    wall_b_id: str
    gap_samples: Tuple[float, ...]
    mean_gap_pt: float
    relative_spread: float
    overlap_pt: float
    is_locally_consistent: bool
    bbox: Tuple[float, float, float, float]  # min_x, min_y, max_x, max_y over both walls' overlap region


def _node_to_wall_ids(walls: Sequence[WallCandidate]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for w in walls:
        for node_id in w.end_node_ids:
            out.setdefault(node_id, []).append(w.candidate_id)
    return out


def _shares_enclosing_quadrilateral(
    a: WallCandidate, b: WallCandidate, node_to_walls: Dict[str, List[str]]
) -> bool:
    """True if a and b are the two opposite sides of one small closed
    quadrilateral (bridged by two other walls at each end) rather than one
    wall's two faces -- a furniture rectangle's or a room's own opposite
    walls can otherwise coincidentally satisfy the parallel/gap/overlap test
    exactly like a real double-line wall's two faces. See PR #273's own
    research for the original discovery of this false-positive class; this
    restates the same check since it addresses a real geometric coincidence,
    independent of the tier-semantics changes this module makes."""
    a1, a2 = a.end_node_ids
    b1, b2 = b.end_node_ids
    neighbors_a1 = set(node_to_walls.get(a1, ())) - {a.candidate_id, b.candidate_id}
    neighbors_a2 = set(node_to_walls.get(a2, ())) - {a.candidate_id, b.candidate_id}
    neighbors_b1 = set(node_to_walls.get(b1, ())) - {a.candidate_id, b.candidate_id}
    neighbors_b2 = set(node_to_walls.get(b2, ())) - {a.candidate_id, b.candidate_id}
    straight = bool(neighbors_a1 & neighbors_b1) and bool(neighbors_a2 & neighbors_b2)
    crossed = bool(neighbors_a1 & neighbors_b2) and bool(neighbors_a2 & neighbors_b1)
    return straight or crossed


def _sample_gap(
    a: WallCandidate, b: WallCandidate, *, sample_fractions: Sequence[float] = _GAP_SAMPLE_FRACTIONS
) -> Optional[Tuple[float, ...]]:
    """Perpendicular gap from ``a`` to ``b``'s own infinite line, sampled at
    fixed fractions of ``a``'s OVERLAP region with ``b`` (not of a's full
    length, and not at a's raw vertices) -- a wall bowed or kinked along
    only part of its run, or measured against a partner shorter than
    itself, is sampled only where the two actually run alongside each
    other."""
    overlap = _overlap_interval_pt(a, b)
    if overlap is None:
        return None
    lo, hi = overlap
    a_pts = a.centerline_pts
    b_line_a, b_line_b = _wall_endpoints(b)
    samples = []
    for fraction in sample_fractions:
        arc_len = lo + fraction * (hi - lo)
        point = _point_at_arc_length(a_pts, arc_len)
        dist = _perpendicular_distance_to_line(point, b_line_a, b_line_b)
        if dist is None:
            return None
        samples.append(dist)
    return tuple(samples)


def find_face_pair_hypotheses(
    walls: Sequence[WallCandidate],
    *,
    angle_tolerance_deg: float = DEFAULT_PAIR_ANGLE_TOLERANCE_DEG,
    min_thickness_pt: float = DEFAULT_MIN_THICKNESS_PT,
    max_thickness_pt: float = DEFAULT_MAX_THICKNESS_PT,
    min_overlap_fraction: float = DEFAULT_MIN_OVERLAP_FRACTION,
    min_overlap_pt: float = DEFAULT_MIN_OVERLAP_PT,
    local_consistency_relative_tolerance: float = DEFAULT_LOCAL_CONSISTENCY_RELATIVE_TOLERANCE,
) -> List[FacePairHypothesis]:
    """Every geometrically plausible paired-face hypothesis between two
    walls, each carrying its OWN multi-point local-consistency verdict.

    This is deliberately a HYPOTHESIS list, not a verdict on wall identity:
    a pair failing ``is_locally_consistent`` is still returned (with that
    flag False) so a caller can distinguish "no plausible pairing exists"
    from "a pairing exists but its own gap wanders too much to trust,"
    which the earlier PR #273 model conflated (it only ever flagged
    ambiguity when TWO DIFFERENT partners disagreed, never when a single
    partner's own gap was internally inconsistent along the run -- e.g. a
    stepped/ladder shape that is only locally parallel-looking over part of
    its length)."""
    node_to_walls = _node_to_wall_ids(walls)
    angles = {w.candidate_id: _wall_angle_deg(w) for w in walls}
    lengths = {w.candidate_id: _wall_length_pt(w) for w in walls}
    out: List[FacePairHypothesis] = []

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
            samples = _sample_gap(a, b)
            if samples is None:
                continue
            mean_gap = statistics.mean(samples)
            if mean_gap <= 0.0 or not (min_thickness_pt <= mean_gap <= max_thickness_pt):
                continue
            overlap = _projection_overlap_pt(a, b)
            shorter = min(lengths[a.candidate_id], lengths[b.candidate_id])
            if overlap < min_overlap_pt or overlap < min_overlap_fraction * shorter:
                continue
            if _shares_enclosing_quadrilateral(a, b, node_to_walls):
                continue

            spread = (max(samples) - min(samples)) / mean_gap if mean_gap > 0 else float("inf")
            is_consistent = spread <= local_consistency_relative_tolerance

            xs = [p[0] for p in a.centerline_pts] + [p[0] for p in b.centerline_pts]
            ys = [p[1] for p in a.centerline_pts] + [p[1] for p in b.centerline_pts]
            bbox = (min(xs), min(ys), max(xs), max(ys))

            out.append(
                FacePairHypothesis(
                    wall_a_id=a.candidate_id,
                    wall_b_id=b.candidate_id,
                    gap_samples=samples,
                    mean_gap_pt=mean_gap,
                    relative_spread=spread,
                    overlap_pt=overlap,
                    is_locally_consistent=is_consistent,
                    bbox=bbox,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Signal: repeated thickness modes (cross-pair clustering, requiring
# geometrically DISTINCT, non-overlapping occurrences).
# ---------------------------------------------------------------------------


def _bboxes_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0 or ax0 > bx1 or ay1 < by0 or ay0 > by1)


class _UnionFind:
    def __init__(self, keys: Sequence[int]) -> None:
        self._parent: Dict[int, int] = {k: k for k in keys}

    def find(self, key: int) -> int:
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            lo, hi = sorted((ra, rb))
            self._parent[hi] = lo


def cluster_thickness_modes(
    pairs: Sequence[FacePairHypothesis],
    *,
    relative_tolerance: float = DEFAULT_MODE_RELATIVE_TOLERANCE,
) -> Dict[int, List[int]]:
    """Cluster the LOCALLY CONSISTENT pairs by mutually-agreeing mean gap,
    returning mode_id -> [pair_index, ...]. A mode with pairs from only ONE
    spatial location (all pairwise bounding boxes overlap -- i.e. they are
    all measurements of the same physical run) is not "repeated" evidence
    for any of its members; only a mode containing pairs from two or more
    spatially DISTINCT (non-overlapping) locations counts as a genuine
    repeated thickness mode -- see ``modes_with_distinct_occurrences``."""
    consistent_indices = [i for i, p in enumerate(pairs) if p.is_locally_consistent]
    uf = _UnionFind(consistent_indices)
    for idx_a in range(len(consistent_indices)):
        i = consistent_indices[idx_a]
        for idx_b in range(idx_a + 1, len(consistent_indices)):
            j = consistent_indices[idx_b]
            gap_i, gap_j = pairs[i].mean_gap_pt, pairs[j].mean_gap_pt
            denom = max(gap_i, gap_j)
            if denom <= 0:
                continue
            if abs(gap_i - gap_j) / denom <= relative_tolerance:
                uf.union(i, j)

    modes: Dict[int, List[int]] = {}
    for i in consistent_indices:
        modes.setdefault(uf.find(i), []).append(i)
    return modes


def modes_with_distinct_occurrences(
    pairs: Sequence[FacePairHypothesis], modes: Dict[int, List[int]]
) -> Set[int]:
    """Pair indices belonging to a mode that has at least two members whose
    own bounding boxes do NOT overlap -- i.e. the same thickness measured at
    two genuinely separate locations in the drawing, not just twice at the
    same physical run (which is not repetition, it is the same measurement
    counted twice)."""
    qualifying: Set[int] = set()
    for member_indices in modes.values():
        if len(member_indices) < 2:
            continue
        boxes = [pairs[i].bbox for i in member_indices]
        has_distinct_pair = False
        for a in range(len(boxes)):
            for b in range(a + 1, len(boxes)):
                if not _bboxes_overlap(boxes[a], boxes[b]):
                    has_distinct_pair = True
                    break
            if has_distinct_pair:
                break
        if has_distinct_pair:
            qualifying.update(member_indices)
    return qualifying


# ---------------------------------------------------------------------------
# Signal: repeated symbol-like shape (evidence AGAINST wall authority).
# ---------------------------------------------------------------------------


def find_symbol_like_pair_indices(
    pairs: Sequence[FacePairHypothesis],
    *,
    round_pt: float = _SYMBOL_SHAPE_ROUND_PT,
    repetition_count: int = DEFAULT_SYMBOL_REPETITION_COUNT,
) -> Set[int]:
    """Pair indices whose own (gap, overlap-length) SHAPE -- not just
    thickness -- recurs identically at three or more spatially distinct
    locations: a stamped/copied symbol (furniture, a hatch tick, a
    glazing-bar ladder, a repeated stub grid), as opposed to real wall runs,
    which are each individually dimensioned to fit their own opening or
    room and so essentially never share both their thickness AND their
    exact length by coincidence, repeatedly."""

    def _key(p: FacePairHypothesis) -> Tuple[float, float]:
        return (
            round(p.mean_gap_pt / round_pt) * round_pt,
            round(p.overlap_pt / round_pt) * round_pt,
        )

    by_shape: Dict[Tuple[float, float], List[int]] = {}
    for i, p in enumerate(pairs):
        by_shape.setdefault(_key(p), []).append(i)

    flagged: Set[int] = set()
    for indices in by_shape.values():
        if len(indices) < repetition_count:
            continue
        boxes = [pairs[i].bbox for i in indices]
        distinct_count = 1
        representative_boxes = [boxes[0]]
        for box in boxes[1:]:
            if all(not _bboxes_overlap(box, rep) for rep in representative_boxes):
                distinct_count += 1
                representative_boxes.append(box)
        if distinct_count >= repetition_count:
            flagged.update(indices)
    return flagged


# ---------------------------------------------------------------------------
# Signal: wall-band continuity through adjacent topology (a shared
# junction/corner, or a plausible opening gap between two collinear runs).
# ---------------------------------------------------------------------------


def _walls_share_junction_node(a: WallCandidate, b: WallCandidate) -> bool:
    return bool(set(a.end_node_ids) & set(b.end_node_ids))


def _outward_direction(centerline_pts: Sequence[Tuple[float, float]], end_index: int) -> Tuple[float, float]:
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


def _walls_are_collinear_gap_partners(
    a: WallCandidate,
    b: WallCandidate,
    *,
    angle_tolerance_deg: float = DEFAULT_PAIR_ANGLE_TOLERANCE_DEG,
    max_gap_relative_to_shorter: float = 0.5,
) -> bool:
    """True when a and b look like the two sides of ONE run interrupted by
    a real opening -- the same collinear-dangling-end test already proven
    in W7 (``pb_wall_room_topology_opening_host_binding._plausible_gap_
    partners``/``_perpendicular_offset_ok``), restated here since this
    module does not import that one's private helpers, per this codebase's
    established per-module restatement convention.

    Checking only "some endpoint of a is within a plausible distance of
    some endpoint of b" is NOT enough on its own -- that also matches two
    PARALLEL, merely-offset walls (a real double-line wall's own two
    faces, or a coincidental room-width pair), since two long parallel
    lines' nearest endpoints can easily sit well within a generous
    fraction of either one's own length. The discriminator W7 already
    established is direction: the two candidate dangling ends must extend
    AWAY from each other along (approximately) the same line -- their own
    outward directions close to anti-parallel, AND the vector actually
    joining the two end points aligned with that same line (not
    perpendicular to it, which is what a merely-parallel-and-offset pair
    would show)."""
    angle_a, angle_b = _wall_angle_deg(a), _wall_angle_deg(b)
    if angle_a is None or angle_b is None or _angle_delta(angle_a, angle_b) > angle_tolerance_deg:
        return False

    shorter_len = min(_wall_length_pt(a), _wall_length_pt(b))
    if shorter_len <= 0.0:
        return False

    for end_a in (0, 1):
        if a.junction_types[end_a] != JunctionType.ENDPOINT:
            continue  # only a genuine dangling end can be one side of an opening gap
        point_a = a.centerline_pts[0] if end_a == 0 else a.centerline_pts[-1]
        direction_a = _outward_direction(a.centerline_pts, end_a)
        for end_b in (0, 1):
            if b.junction_types[end_b] != JunctionType.ENDPOINT:
                continue
            point_b = b.centerline_pts[0] if end_b == 0 else b.centerline_pts[-1]
            direction_b = _outward_direction(b.centerline_pts, end_b)

            gap = math.hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])
            if gap <= 0.0 or gap > max_gap_relative_to_shorter * shorter_len:
                continue

            # Outward directions must be close to anti-parallel (each end
            # points away from its own wall body, toward the other).
            if _angle_between_deg(direction_a, direction_b) < 180.0 - angle_tolerance_deg:
                continue

            # The vector actually joining the two points must run along
            # that same line -- rules out two parallel-but-offset walls.
            joining = ((point_b[0] - point_a[0]) / gap, (point_b[1] - point_a[1]) / gap)
            joining_angle = min(
                _angle_between_deg(direction_a, joining),
                _angle_between_deg(direction_a, (-joining[0], -joining[1])),
            )
            if joining_angle > angle_tolerance_deg:
                continue

            return True
    return False


def find_band_continuity_wall_ids(
    walls: Sequence[WallCandidate],
    pairs: Sequence[FacePairHypothesis],
    *,
    mode_relative_tolerance: float = DEFAULT_MODE_RELATIVE_TOLERANCE,
) -> Set[str]:
    """Wall ids that have at least one LOCALLY CONSISTENT paired-face
    measurement of their own, AND are topologically adjacent (shared
    junction node, or a plausible collinear opening gap) to a DIFFERENT
    wall that is ALSO independently locally consistent, at a matching
    thickness. This is the "two faces tracked together through a corner,
    a T, or an opening, behaving like offsets of the same physical
    centreline" signal -- genuinely independent of both a wall's own local
    consistency (it requires a SEPARATE candidate's own independent
    measurement to agree) and of the repeated-thickness-mode signal (it
    requires REAL topological adjacency, not merely a matching gap value
    anywhere else in the drawing)."""
    walls_by_id = {w.candidate_id: w for w in walls}
    consistent_pairs = [p for p in pairs if p.is_locally_consistent]
    gap_by_wall: Dict[str, List[float]] = {}
    for p in consistent_pairs:
        gap_by_wall.setdefault(p.wall_a_id, []).append(p.mean_gap_pt)
        gap_by_wall.setdefault(p.wall_b_id, []).append(p.mean_gap_pt)

    evidenced_wall_ids = set(gap_by_wall.keys())
    band_ids: Set[str] = set()
    evidenced_list = list(evidenced_wall_ids)
    for i, wall_a_id in enumerate(evidenced_list):
        wall_a = walls_by_id[wall_a_id]
        own_gaps = gap_by_wall[wall_a_id]
        for wall_b_id in evidenced_list[i + 1 :]:
            if wall_a_id == wall_b_id:
                continue
            wall_b = walls_by_id[wall_b_id]
            adjacent = _walls_share_junction_node(wall_a, wall_b) or _walls_are_collinear_gap_partners(
                wall_a, wall_b
            )
            if not adjacent:
                continue
            other_gaps = gap_by_wall[wall_b_id]
            matches = any(
                abs(g_a - g_b) / max(g_a, g_b) <= mode_relative_tolerance
                for g_a in own_gaps
                for g_b in other_gaps
                if max(g_a, g_b) > 0
            )
            if matches:
                band_ids.add(wall_a_id)
                band_ids.add(wall_b_id)
    return band_ids


# ---------------------------------------------------------------------------
# Signal: scale-aware physical plausibility (weak, optional, never
# sufficient alone).
# ---------------------------------------------------------------------------


def is_scale_plausible(
    mean_gap_pt: float,
    scale_pt_per_m: float,
    *,
    min_m: float = DEFAULT_MIN_PLAUSIBLE_THICKNESS_M,
    max_m: float = DEFAULT_MAX_PLAUSIBLE_THICKNESS_M,
) -> bool:
    if scale_pt_per_m <= 0:
        return False
    thickness_m = mean_gap_pt / scale_pt_per_m
    return min_m <= thickness_m <= max_m


# ---------------------------------------------------------------------------
# Final, independence-respecting evidence combination.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WallBandEvidence:
    wall_id: str
    status: EvidenceResolutionStatus
    confidence: float
    supporting_evidence_ids: Tuple[str, ...]
    reason_codes: Tuple[str, ...]
    thickness_m: Optional[float] = None
    best_pair: Optional[FacePairHypothesis] = None


def rank_wall_band_evidence(
    walls: Sequence[WallCandidate],
    *,
    scale_pt_per_m: Optional[float] = None,
    angle_tolerance_deg: float = DEFAULT_PAIR_ANGLE_TOLERANCE_DEG,
    min_thickness_pt: float = DEFAULT_MIN_THICKNESS_PT,
    max_thickness_pt: float = DEFAULT_MAX_THICKNESS_PT,
    min_overlap_fraction: float = DEFAULT_MIN_OVERLAP_FRACTION,
    min_overlap_pt: float = DEFAULT_MIN_OVERLAP_PT,
    local_consistency_relative_tolerance: float = DEFAULT_LOCAL_CONSISTENCY_RELATIVE_TOLERANCE,
    mode_relative_tolerance: float = DEFAULT_MODE_RELATIVE_TOLERANCE,
    symbol_repetition_count: int = DEFAULT_SYMBOL_REPETITION_COUNT,
) -> List[WallBandEvidence]:
    """Evaluate every wall's own wall-band evidence. Returns a list
    POSITIONALLY ALIGNED with ``walls`` (same length, same order) --
    deliberately NOT a ``Dict[str, WallBandEvidence]`` keyed by
    ``candidate_id``. W4's own id generation, even after the shape-
    fingerprint fix (see ``pb_wall_room_topology_wall_assembly``), is not
    guaranteed globally unique on real, messy geometry: confirmed on real
    Dungicha data, two genuinely duplicate Stage-A edges (the same 2-point
    line traced twice, apparently not caught by Stage A's own coincident-
    edge dedup) produced two distinct ``WallCandidate`` objects sharing one
    id, since both really are the same straight line and are THEREFORE
    correctly assigned the same content-derived id. A dict keyed by that id
    would silently drop one of the two candidates. This module's own job is
    to evaluate every candidate it is given -- silently dropping one is
    exactly the failure class this whole workstream exists to eliminate,
    so the return shape is chosen to make that structurally impossible
    rather than merely unlikely. A caller wanting id-keyed lookup should
    build ``dict(zip((w.candidate_id for w in walls), result))`` itself,
    an explicit choice to accept id collisions rather than a hidden one.

    Walls with literally no geometric pairing hypothesis at all still get
    an entry (ABSTAINED, ``REASON_NO_EVIDENCE``).

    Tier rules (never room-boundary, never bare one-hop connectivity -- see
    module docstring for why those were removed):

    - Flagged symbol-like (a shape repeating 3+ times at distinct
      locations): ABSTAINED, regardless of any other signal -- a stamped
      symbol's own "local consistency" is an artifact of being copy-pasted,
      not evidence of field-built wall material.
    - No pairing hypothesis at all: ABSTAINED, no evidence.
    - Paired, but the gap is not locally consistent along the overlap
      (spread exceeds the relative tolerance): CANDIDATE, weak, flagged
      ambiguous -- a stepped/ladder shape or a coincidental near-miss.
    - Locally consistent, but ISOLATED (no repeated mode elsewhere, no
      topologically-adjacent matching neighbour): CANDIDATE, one genuine
      signal.
    - Locally consistent AND at least one of {repeated mode, band
      continuity}: CANDIDATE, two genuinely independent signals.
    - Locally consistent AND repeated mode AND band continuity AND (when a
      real scale authority is supplied) scale-plausible: CORROBORATED, with
      a real resolved thickness_m -- the only path to CORROBORATED, and it
      requires three independent structural signals plus a real
      measurement, not merely "two signals" as an earlier research pass
      allowed.
    """
    pairs = find_face_pair_hypotheses(
        walls,
        angle_tolerance_deg=angle_tolerance_deg,
        min_thickness_pt=min_thickness_pt,
        max_thickness_pt=max_thickness_pt,
        min_overlap_fraction=min_overlap_fraction,
        min_overlap_pt=min_overlap_pt,
        local_consistency_relative_tolerance=local_consistency_relative_tolerance,
    )
    symbol_like_indices = find_symbol_like_pair_indices(pairs, repetition_count=symbol_repetition_count)
    modes = cluster_thickness_modes(pairs, relative_tolerance=mode_relative_tolerance)
    repeated_mode_indices = modes_with_distinct_occurrences(pairs, modes)
    band_continuity_wall_ids = find_band_continuity_wall_ids(
        walls, pairs, mode_relative_tolerance=mode_relative_tolerance
    )

    symbol_like_wall_ids: Set[str] = set()
    for i in symbol_like_indices:
        symbol_like_wall_ids.add(pairs[i].wall_a_id)
        symbol_like_wall_ids.add(pairs[i].wall_b_id)

    pairs_by_wall: Dict[str, List[int]] = {}
    for i, p in enumerate(pairs):
        pairs_by_wall.setdefault(p.wall_a_id, []).append(i)
        pairs_by_wall.setdefault(p.wall_b_id, []).append(i)

    out: List[WallBandEvidence] = []
    for wall in walls:
        wid = wall.candidate_id
        own_pair_indices = pairs_by_wall.get(wid, [])

        if wid in symbol_like_wall_ids:
            out.append(
                WallBandEvidence(
                    wall_id=wid,
                    status=EvidenceResolutionStatus.ABSTAINED,
                    confidence=0.0,
                    supporting_evidence_ids=(),
                    reason_codes=(REASON_SYMBOL_LIKE,),
                )
            )
            continue

        if not own_pair_indices:
            out.append(
                WallBandEvidence(
                    wall_id=wid,
                    status=EvidenceResolutionStatus.ABSTAINED,
                    confidence=0.0,
                    supporting_evidence_ids=(),
                    reason_codes=(REASON_NO_EVIDENCE,),
                )
            )
            continue

        consistent_here = [i for i in own_pair_indices if pairs[i].is_locally_consistent]
        if not consistent_here:
            best = max(own_pair_indices, key=lambda i: pairs[i].overlap_pt)
            out.append(
                WallBandEvidence(
                    wall_id=wid,
                    status=EvidenceResolutionStatus.CANDIDATE,
                    confidence=0.2,
                    supporting_evidence_ids=(),
                    reason_codes=(REASON_INCONSISTENT_LOCAL_THICKNESS,),
                    best_pair=pairs[best],
                )
            )
            continue

        best_idx = min(consistent_here, key=lambda i: pairs[i].relative_spread)
        best_pair = pairs[best_idx]

        has_repeated_mode = any(i in repeated_mode_indices for i in consistent_here)
        has_band_continuity = wid in band_continuity_wall_ids

        signals: List[str] = []
        if has_repeated_mode:
            signals.append(REASON_REPEATED_MODE)
        if has_band_continuity:
            signals.append(REASON_BAND_CONTINUITY)

        if not signals:
            out.append(
                WallBandEvidence(
                    wall_id=wid,
                    status=EvidenceResolutionStatus.CANDIDATE,
                    confidence=0.45,
                    supporting_evidence_ids=(),
                    reason_codes=(REASON_ISOLATED_LOCAL_PAIR,),
                    best_pair=best_pair,
                )
            )
            continue

        if len(signals) == 1:
            out.append(
                WallBandEvidence(
                    wall_id=wid,
                    status=EvidenceResolutionStatus.CANDIDATE,
                    confidence=0.6,
                    supporting_evidence_ids=tuple(signals),
                    reason_codes=tuple(signals),
                    best_pair=best_pair,
                )
            )
            continue

        # Both independent structural signals present. CORROBORATED still
        # requires a real, resolved metric thickness -- never granted from
        # geometry alone, matching WallCandidate's own validation rule that
        # CORROBORATED cannot coexist with an unresolved (PROVISIONAL)
        # thickness authority.
        if scale_pt_per_m and scale_pt_per_m > 0:
            plausible = is_scale_plausible(best_pair.mean_gap_pt, scale_pt_per_m)
            if plausible:
                thickness_m = round(best_pair.mean_gap_pt / scale_pt_per_m, 4)
                out.append(
                    WallBandEvidence(
                        wall_id=wid,
                        status=EvidenceResolutionStatus.CORROBORATED,
                        confidence=0.9,
                        supporting_evidence_ids=tuple(signals + [REASON_SCALE_PLAUSIBLE]),
                        reason_codes=tuple(signals + [REASON_SCALE_PLAUSIBLE]),
                        thickness_m=thickness_m,
                        best_pair=best_pair,
                    )
                )
                continue
            out.append(
                WallBandEvidence(
                    wall_id=wid,
                    status=EvidenceResolutionStatus.CANDIDATE,
                    confidence=0.5,
                    supporting_evidence_ids=tuple(signals),
                    reason_codes=tuple(signals + [REASON_SCALE_IMPLAUSIBLE]),
                    best_pair=best_pair,
                )
            )
            continue

        out.append(
            WallBandEvidence(
                wall_id=wid,
                status=EvidenceResolutionStatus.CANDIDATE,
                confidence=0.7,
                supporting_evidence_ids=tuple(signals),
                reason_codes=tuple(signals),
                best_pair=best_pair,
            )
        )

    return out
