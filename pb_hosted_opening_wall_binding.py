"""Section H: a thin, purely geometric bridge between
``pb_hosted_opening_geometry.HostedOpeningSpan`` (a wall-hosted opening's own
evidenced span, detected from hatch/fill-gap evidence -- see that module) and
``pb_wall_room_topology_contracts.WallCandidate`` (the existing, adopted
W1-W10 wall-graph topology).

Neither of the two modules this binder connects knows the other exists --
``pb_hosted_opening_geometry`` never reads a wall graph, and none of W1-W10
reads glazing/hatch/door-swing evidence. This module answers exactly one
question, purely from already-established geometry: "does one specific,
already-reconstructed ``WallCandidate`` evidently host this specific,
already-evidenced opening span?"

Deliberately does NOT:
- assign, infer, or read a W1/W2/D1 schedule identity (that is Cursor's
  ``pb_opening_provenance_graph`` -- a different, text/tag-identity axis of
  evidence; this module never reads text or tags at all);
- compute or emit any wall-area deduction, quantity, or ``QuantityEvidence``;
- infer an opening height (plan geometry alone never shows height);
- wire into any live extraction path;
- default to "the nearest wall" or any other perimeter/proximity guess when
  the geometry is genuinely ambiguous -- see AMBIGUOUS below.

BINDING RULE
------------
A ``WallCandidate`` is a plausible host only when ALL of the following hold,
projected onto the opening's own host axis (``host_orientation_deg`` is
always exactly ``0.0`` for a horizontal wall run or ``90.0`` for a vertical
one -- see ``pb_hosted_opening_geometry.resolve_hosted_opening_spans``):

1. the wall's own overall direction (its centerline's first point to its
   last) is collinear with that axis, within ``angle_tolerance_deg``;
2. the wall's own cross-axis position (its centerline points' mean
   perpendicular coordinate) is within ``perpendicular_tolerance_pt`` (or
   the span's own evidenced ``wall_thickness_pt``, whichever is larger) of
   the opening's own cross-axis position;
3. AND either:
   a. the wall's own along-axis extent fully contains the opening's jamb
      interval (a wall drawn continuously through the opening -- e.g. a
      diagonal-hatch-tick gap convention, where Stage A's segment graph
      never sees a face-line break at all, so W4 assembles one unbroken
      ``WallCandidate`` spanning straight through it); or
   b. the wall's own along-axis extent ends within ``adjacency_tolerance_pt``
      of one of the opening's two jamb positions (a wall drawn with a
      genuine face-line gap -- e.g. a solid-fill-pier convention -- so W4
      never merges across the gap and produces two separate dangling
      chains, one flanking each jamb).

STATUS SEMANTICS
-----------------
- ``"bound"``: exactly one wall candidate satisfies rule 3a (contains the
  span) and no other candidate satisfies 3a or 3b at all. ``wall_candidate_id``
  names that one candidate.
- ``"ambiguous"``: more than one candidate is plausible under the rule above
  -- most commonly exactly two candidates each satisfying 3b at opposite
  jambs (the opening genuinely splits one physical wall run into two W4
  chains; both are equally real hosts and picking one over the other would
  be exactly the kind of guess ``pb_wall_room_topology_opening_host_binding``
  already refuses to make for the structurally identical "two dangling
  chains" situation -- this binder mirrors that same discipline rather than
  inventing a different rule for the same problem). Also reached for any
  other multi-candidate situation (e.g. a duplicate wall line elsewhere at
  the same orientation and cross-axis position). ``wall_candidate_id`` is
  always ``None``; ``considered_wall_candidate_ids`` names every plausible
  candidate so the ambiguity is auditable, never silently discarded.
- ``"unbound"``: no wall candidate satisfies the rule at all. This is an
  expected, honest outcome -- e.g. the opening's own host wall did not
  survive as a ``WallCandidate`` (fell below Stage A's structural-segment
  filter, or the viewport scoping used for the two detectors did not
  exactly match) -- not evidence of a detector defect on its own.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence, Tuple

from pb_hosted_opening_geometry import HostedOpeningSpan
from pb_migration_contracts import stable_contract_id
from pb_wall_room_topology_contracts import WallCandidate

BINDING_SCHEMA_VERSION = "1.0.0"

DEFAULT_ANGLE_TOLERANCE_DEG = 3.0
DEFAULT_PERPENDICULAR_TOLERANCE_PT = 3.0
DEFAULT_ADJACENCY_TOLERANCE_PT = 3.0
DEFAULT_CONTAINMENT_MARGIN_PT = 0.5

REASON_BOUND_CONTAINED = "single_wall_candidate_contains_opening_span"
REASON_AMBIGUOUS_TWO_FLANKING_CHAINS = "opening_flanked_by_two_distinct_wall_chains"
REASON_AMBIGUOUS_MULTIPLE_CANDIDATES = "multiple_plausible_wall_candidates"
REASON_UNBOUND_NO_HOST = "no_plausible_host"

BindingStatus = Literal["bound", "ambiguous", "unbound"]


@dataclass(frozen=True)
class HostedOpeningWallBinding:
    """One opening span's resolved (or explicitly unresolved) relationship
    to the wall-candidate topology. See module docstring for status
    semantics. Never carries a schedule identity, a quantity, or a height --
    none of those exist in either module this binder reads from."""

    binding_id: str
    page: int
    viewport_id: str
    host_orientation_deg: float
    jamb_start: Tuple[float, float]
    jamb_end: Tuple[float, float]
    span_pt: float
    subtype: str
    status: BindingStatus
    wall_candidate_id: Optional[str]
    considered_wall_candidate_ids: Tuple[str, ...]
    reason: str
    evidence_flags: Tuple[str, ...]
    schema_version: str = BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status == "bound":
            if self.wall_candidate_id is None:
                raise ValueError("status='bound' must set wall_candidate_id")
            if self.considered_wall_candidate_ids != (self.wall_candidate_id,):
                raise ValueError(
                    "status='bound' must have considered_wall_candidate_ids == (wall_candidate_id,)"
                )
        else:
            if self.wall_candidate_id is not None:
                raise ValueError(f"status={self.status!r} must not set wall_candidate_id")
            if self.status == "unbound" and self.considered_wall_candidate_ids:
                raise ValueError("status='unbound' must have no considered wall candidates")
            if self.status == "ambiguous" and len(self.considered_wall_candidate_ids) < 2:
                raise ValueError("status='ambiguous' must consider at least two wall candidates")


def _angle_delta(a_deg: float, b_deg: float) -> float:
    d = abs(a_deg - b_deg) % 180.0
    return min(d, 180.0 - d)


def _wall_angle_deg(wall: WallCandidate) -> Optional[float]:
    pts = wall.centerline_pts
    if len(pts) < 2:
        return None
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    if x1 == x2 and y1 == y2:
        return None
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0


def _axis_extent_and_cross(wall: WallCandidate, *, along_x: bool) -> Tuple[float, float, float]:
    pts = wall.centerline_pts
    if along_x:
        alongs = [p[0] for p in pts]
        crosses = [p[1] for p in pts]
    else:
        alongs = [p[1] for p in pts]
        crosses = [p[0] for p in pts]
    return min(alongs), max(alongs), sum(crosses) / len(crosses)


def bind_hosted_opening_to_walls(
    span: HostedOpeningSpan,
    walls: Sequence[WallCandidate],
    *,
    viewport_id: str,
    angle_tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG,
    perpendicular_tolerance_pt: float = DEFAULT_PERPENDICULAR_TOLERANCE_PT,
    adjacency_tolerance_pt: float = DEFAULT_ADJACENCY_TOLERANCE_PT,
    containment_margin_pt: float = DEFAULT_CONTAINMENT_MARGIN_PT,
) -> HostedOpeningWallBinding:
    """Resolve one ``HostedOpeningSpan`` against a viewport's already-built
    ``WallCandidate`` list. See module docstring for the binding rule and
    status semantics. Pure function: never mutates ``walls``, never reads a
    PDF, never reads text/tags."""
    along_x = span.host_orientation_deg == 0.0
    if along_x:
        lo, hi = sorted((span.jamb_start[0], span.jamb_end[0]))
        cross = (span.jamb_start[1] + span.jamb_end[1]) / 2.0
    else:
        lo, hi = sorted((span.jamb_start[1], span.jamb_end[1]))
        cross = (span.jamb_start[0] + span.jamb_end[0]) / 2.0

    target_angle = 0.0 if along_x else 90.0
    perp_tol = max(perpendicular_tolerance_pt, span.wall_thickness_pt)

    contained_ids: List[str] = []
    adjacent_lo_ids: List[str] = []
    adjacent_hi_ids: List[str] = []

    for wall in walls:
        angle = _wall_angle_deg(wall)
        if angle is None:
            continue
        if _angle_delta(angle, target_angle) > angle_tolerance_deg:
            continue
        w_lo, w_hi, w_cross = _axis_extent_and_cross(wall, along_x=along_x)
        if abs(w_cross - cross) > perp_tol:
            continue
        if w_lo <= lo + containment_margin_pt and w_hi >= hi - containment_margin_pt:
            contained_ids.append(wall.candidate_id)
        elif abs(w_hi - lo) <= adjacency_tolerance_pt:
            adjacent_lo_ids.append(wall.candidate_id)
        elif abs(w_lo - hi) <= adjacency_tolerance_pt:
            adjacent_hi_ids.append(wall.candidate_id)

    binding_id = stable_contract_id(
        "hostbind",
        {
            "page": span.page,
            "viewport_id": viewport_id,
            "host_orientation_deg": span.host_orientation_deg,
            "jamb_start": span.jamb_start,
            "jamb_end": span.jamb_end,
        },
    )
    base_kwargs = dict(
        binding_id=binding_id,
        page=span.page,
        viewport_id=viewport_id,
        host_orientation_deg=span.host_orientation_deg,
        jamb_start=span.jamb_start,
        jamb_end=span.jamb_end,
        span_pt=span.span_pt,
        subtype=span.subtype,
    )

    considered = sorted(set(contained_ids) | set(adjacent_lo_ids) | set(adjacent_hi_ids))

    if len(contained_ids) == 1 and not adjacent_lo_ids and not adjacent_hi_ids:
        return HostedOpeningWallBinding(
            **base_kwargs,
            status="bound",
            wall_candidate_id=contained_ids[0],
            considered_wall_candidate_ids=(contained_ids[0],),
            reason=REASON_BOUND_CONTAINED,
            evidence_flags=("wall_candidate_contains_span",),
        )

    if (
        not contained_ids
        and len(adjacent_lo_ids) == 1
        and len(adjacent_hi_ids) == 1
        and adjacent_lo_ids[0] != adjacent_hi_ids[0]
    ):
        return HostedOpeningWallBinding(
            **base_kwargs,
            status="ambiguous",
            wall_candidate_id=None,
            considered_wall_candidate_ids=tuple(considered),
            reason=REASON_AMBIGUOUS_TWO_FLANKING_CHAINS,
            evidence_flags=("adjacent_at_both_jambs",),
        )

    if len(considered) >= 2:
        return HostedOpeningWallBinding(
            **base_kwargs,
            status="ambiguous",
            wall_candidate_id=None,
            considered_wall_candidate_ids=tuple(considered),
            reason=REASON_AMBIGUOUS_MULTIPLE_CANDIDATES,
            evidence_flags=("multiple_candidates_considered",),
        )

    if len(considered) == 1:
        # Exactly one candidate is adjacent at only ONE of the two jambs,
        # with no candidate at all reaching the other jamb and no candidate
        # containing the full span. Weaker evidence than either a full
        # containment match or a genuine two-sided flanking pair -- a
        # single dangling wall end near one jamb, alone, could equally be
        # an unrelated wall terminus that merely happens to land nearby.
        # Fail closed rather than promote a one-sided coincidence to a
        # confident bind.
        return HostedOpeningWallBinding(
            **base_kwargs,
            status="unbound",
            wall_candidate_id=None,
            considered_wall_candidate_ids=(),
            reason="single_sided_adjacency_insufficient",
            evidence_flags=("one_jamb_only_candidate:" + considered[0],),
        )

    return HostedOpeningWallBinding(
        **base_kwargs,
        status="unbound",
        wall_candidate_id=None,
        considered_wall_candidate_ids=(),
        reason=REASON_UNBOUND_NO_HOST,
        evidence_flags=(),
    )
