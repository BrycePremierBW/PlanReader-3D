"""W10: canonical building graph adapter.

Translates one viewport's already-produced W1-W9 topology (WallCandidate,
RoomCandidate, OpeningHostCandidate) into the ONE canonical building-graph
schema that already exists in this codebase: ``pb_canonical_building``
(``CanonicalLevel`` / ``CanonicalWall`` / ``CanonicalSpace`` / ``ObjectType``
/ ``ReviewState`` / ``Provenance``). Confirmed by inspection before writing
any code: that module is a mature, already-used "single-source-of-truth
object graph representing physical building geometry" (its own docstring),
already consumed by ``pb_production_3d_adapter_phase5m.py``,
``pb_canonical_persistence.py``, and others. The user's own standing rule
("do not start a second canonical graph") makes this an ADAPTER stage, not
a new-graph stage -- no new node/entity schema is introduced here.

Returns exactly one ``CanonicalLevel`` per call (one viewport's worth of
geometry), with real ``CanonicalWall``/``CanonicalSpace`` children --
nothing wraps it in a ``CanonicalBuilding``/``CanonicalProject``, because
this workstream has no evidence yet of how multiple viewports compose into
one building (that decision is out of scope, not merely deferred by
convenience).

FAIL-CLOSED TRANSLATION RULES
------------------------------
- IDs are reused verbatim (``WallCandidate.candidate_id`` ->
  ``CanonicalWall.id``, ``RoomCandidate.room_ref`` -> ``CanonicalSpace.id``)
  -- this is a translation of the same entities, not a re-identification.
- ``takeoff_eligible`` and ``deduction_authority`` are hardcoded ``False``
  on every element this adapter produces, unconditionally. Those two
  booleans are exactly the "this is now measurement-authority-grade data"
  signal in the existing schema, and nothing produced by a topology/
  perception workstream is measurement-authority-grade yet.
- ``review_state`` is never ``CONFIRMED`` (that means human/authoritative
  confirmation, which nothing here has). ``EvidenceResolutionStatus.
  CORROBORATED`` maps to ``ReviewState.INFERRED``; every other status
  (``CANDIDATE``, ``RAW``, ``ABSTAINED``, ``CONFLICT``) maps to
  ``ReviewState.REVIEW_REQUIRED``.
- ``height_m`` is left ``None`` on every ``CanonicalWall``/``CanonicalSpace``/
  ``CanonicalLevel`` this adapter produces -- no wall height, room height,
  or level elevation evidence exists anywhere in W1-W9, and this stage
  does not start producing any (explicitly out of scope per the
  workstream's own hard-stop list).
- ``CanonicalSpace.specified_floor_area_m2`` is left ``None`` even though
  ``RoomCandidate.floor_area_m2`` already exists as a topology-candidate
  field -- "room areas" is explicitly on this workstream's own hard-stop
  list, and ``specified_floor_area_m2`` reads in the existing schema as an
  authoritative/explicit area value, not a raw geometry-derived candidate.
  Publishing it here would be exactly the "wire topology into commercial
  publishing" this workstream is forbidden from doing.
- ``CanonicalWall.start_point``/``end_point`` are populated in metres only
  when that specific wall's own ``length_m`` is already resolved (the
  metric centerline length W5's calibration produced) -- the metre
  coordinates are derived from that wall's OWN already-resolved
  page-point-to-metre ratio (the same reuse pattern W7 used for
  ``gap_width_m``: never a global or invented scale). When ``length_m`` is
  unresolved, both points stay ``Vector2D()`` (``x=None, y=None``) -- the
  existing schema's own "fails closed with ZERO made-up defaults"
  default, not a guess.
- No ``CanonicalOpening`` is EVER produced by this stage. Every
  ``OpeningHostCandidate`` W7 can currently produce is
  ``host_status="ambiguous_host"`` by that stage's own design (see W7's
  module docstring) -- ``CanonicalOpening.wall_id`` requires committing to
  ONE wall, and picking one of the 2+ still-plausible walls would be
  exactly the guess W7 itself refused to make. Each affected
  ``CanonicalWall``'s own ``metadata["candidate_opening_host_ids"]``
  instead cross-references (by id only) every still-unresolved opening
  host that considered it, and the returned ``CanonicalLevel``'s own
  ``metadata["unresolved_opening_host_ids"]`` lists all of them for the
  level as a whole -- informational cross-references, not authority.

Does NOT:
- construct a ``CanonicalBuilding``/``CanonicalProject`` (out of scope --
  no cross-viewport building composition evidence exists);
- emit ``QuantityEvidence`` or set any authority/eligibility flag;
- wire into any live extraction, persistence, or publishing path
  (``pb_canonical_persistence`` is never imported or called here);
- resolve any of W6/W7/W8's existing fail-closed ambiguities -- they are
  translated as-is (see ``interior_exterior`` handling below), never
  re-decided.
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

from pb_canonical_building import (
    CanonicalLevel,
    CanonicalSpace,
    CanonicalWall,
    Provenance,
    ReviewState,
    Vector2D,
)
from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_contracts import OpeningHostCandidate, RoomCandidate, WallCandidate

ADAPTER_PRODUCER_MODULE = "pb_wall_room_topology_canonical_adapter"
ADAPTER_PRODUCER_VERSION = "1.0"

_STATUS_TO_REVIEW_STATE: Dict[EvidenceResolutionStatus, ReviewState] = {
    EvidenceResolutionStatus.CORROBORATED: ReviewState.INFERRED,
    EvidenceResolutionStatus.CANDIDATE: ReviewState.REVIEW_REQUIRED,
    EvidenceResolutionStatus.RAW: ReviewState.REVIEW_REQUIRED,
    EvidenceResolutionStatus.ABSTAINED: ReviewState.REVIEW_REQUIRED,
    EvidenceResolutionStatus.CONFLICT: ReviewState.REVIEW_REQUIRED,
}


def _review_state_for(status: EvidenceResolutionStatus) -> ReviewState:
    return _STATUS_TO_REVIEW_STATE.get(status, ReviewState.REVIEW_REQUIRED)


def _polyline_length_pt(points: Sequence[Tuple[float, float]]) -> float:
    return sum(
        math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        for i in range(len(points) - 1)
    )


def _wall_endpoints_m(wall: WallCandidate) -> Tuple[Vector2D, Vector2D]:
    """Metre-space endpoints derived from this wall's OWN resolved length_m,
    or (Vector2D(), Vector2D()) -- both x=None,y=None -- when unresolved."""
    if wall.length_m is None:
        return Vector2D(), Vector2D()
    length_pt = _polyline_length_pt(wall.centerline_pts)
    if length_pt <= 0.0:
        return Vector2D(), Vector2D()
    ratio = wall.length_m / length_pt
    start_pt, end_pt = wall.centerline_pts[0], wall.centerline_pts[-1]
    return (
        Vector2D(x=round(start_pt[0] * ratio, 4), y=round(start_pt[1] * ratio, 4)),
        Vector2D(x=round(end_pt[0] * ratio, 4), y=round(end_pt[1] * ratio, 4)),
    )


def _adapt_wall(
    wall: WallCandidate,
    *,
    document_id: str,
    candidate_opening_host_ids: Sequence[str],
) -> CanonicalWall:
    start_point, end_point = _wall_endpoints_m(wall)
    is_external = wall.interior_exterior == "exterior"
    review_state = _review_state_for(wall.status)
    if wall.interior_exterior == "unresolved":
        review_state = ReviewState.REVIEW_REQUIRED

    return CanonicalWall(
        id=wall.candidate_id,
        level_id=wall.level_id,
        confidence=wall.confidence,
        review_state=review_state,
        provenance=Provenance(
            document_id=document_id,
            wall_ref=wall.candidate_id,
            contributing_evidence=list(wall.supporting_evidence_ids),
            producer_module=ADAPTER_PRODUCER_MODULE,
            producer_version=ADAPTER_PRODUCER_VERSION,
        ),
        metadata={
            "topology_status": wall.status.value,
            "topology_reason_codes": list(wall.reason_codes),
            "interior_exterior_topology_status": wall.interior_exterior,
            "candidate_opening_host_ids": list(candidate_opening_host_ids),
            "schema_version": wall.schema_version,
        },
        takeoff_eligible=False,
        deduction_authority=False,
        start_point=start_point,
        end_point=end_point,
        thickness_m=wall.thickness_m,
        height_m=None,
        is_external=is_external,
        openings=[],
    )


def _adapt_room(room: RoomCandidate, *, document_id: str) -> CanonicalSpace:
    boundary_polygon = (
        [Vector2D(x=pt[0], y=pt[1]) for pt in room.polygon_m] if room.polygon_m else []
    )

    return CanonicalSpace(
        id=room.room_ref,
        name=room.label if room.label else "Unnamed Element",
        level_id=room.level_id,
        confidence=room.geometry_confidence,
        review_state=_review_state_for(room.status),
        provenance=Provenance(
            document_id=document_id,
            page_number=room.source_page or None,
            producer_module=ADAPTER_PRODUCER_MODULE,
            producer_version=ADAPTER_PRODUCER_VERSION,
        ),
        metadata={
            "topology_status": room.status.value,
            "topology_reason_codes": list(room.reason_codes),
            "bounding_wall_candidate_ids": list(room.bounding_wall_candidate_ids),
            "adjacent_room_refs": list(room.adjacent_room_refs),
            "has_voids": room.has_voids,
            "schema_version": room.schema_version,
        },
        takeoff_eligible=False,
        deduction_authority=False,
        boundary_polygon=boundary_polygon,
        height_m=None,
        specified_floor_area_m2=None,
        room_number=None,
    )


def adapt_topology_to_canonical_level(
    *,
    document_id: str,
    viewport_id: str,
    walls: Sequence[WallCandidate] = (),
    rooms: Sequence[RoomCandidate] = (),
    opening_hosts: Sequence[OpeningHostCandidate] = (),
) -> CanonicalLevel:
    """Main W10 entry point: adapt one viewport's W1-W9 output into one
    ``CanonicalLevel`` (the existing schema's own per-floor-plan container).

    ``level_index``/``elevation_m``/``height_m`` are left at their fail-
    closed defaults (``0``/``None``/``None``) -- no real level identity or
    vertical position exists in this workstream yet.
    """
    candidate_host_ids_by_wall: Dict[str, List[str]] = {}
    for host in opening_hosts:
        for wall_id in host.candidate_wall_ids_considered:
            candidate_host_ids_by_wall.setdefault(wall_id, []).append(host.host_candidate_id)

    canonical_walls = [
        _adapt_wall(
            wall,
            document_id=document_id,
            candidate_opening_host_ids=candidate_host_ids_by_wall.get(wall.candidate_id, []),
        )
        for wall in walls
    ]
    canonical_spaces = [_adapt_room(room, document_id=document_id) for room in rooms]
    unresolved_opening_host_ids = [host.host_candidate_id for host in opening_hosts]

    return CanonicalLevel(
        id=viewport_id,
        review_state=ReviewState.REVIEW_REQUIRED,
        provenance=Provenance(
            document_id=document_id,
            producer_module=ADAPTER_PRODUCER_MODULE,
            producer_version=ADAPTER_PRODUCER_VERSION,
        ),
        metadata={"unresolved_opening_host_ids": unresolved_opening_host_ids},
        takeoff_eligible=False,
        deduction_authority=False,
        walls=canonical_walls,
        spaces=canonical_spaces,
    )
