"""W6: room<->wall and room<->room topology relationships.

Converts W5's RoomCandidates (each already carrying
``bounding_wall_candidate_ids`` from W5, but always ``adjacent_room_refs=()``
and never cross-referenced back from the wall's own side) plus W4's
WallCandidates (each always ``interior_exterior="unresolved"``, deliberately
left that way in W4 pending exactly this evidence) into:

- explicit ``RoomTopologyRelationship`` records (BOUNDED_BY/BOUNDS/
  ADJACENT_TO/SEPARATES);
- NEW (non-mutated -- these are frozen dataclasses) ``RoomCandidate`` records
  with ``adjacent_room_refs`` correctly populated;
- NEW ``WallCandidate`` records with ``interior_exterior`` resolved to
  ``"interior"`` (shared by exactly two rooms), ``"exterior"`` (used by
  exactly one identified room), or left ``"unresolved"`` (used by zero rooms,
  or a genuinely anomalous 3+-room case -- see below).

Does NOT:
- compute or emit any quantity / area / length authority;
- emit ``QuantityEvidence``;
- infer or bind a semantic room name (that is W8);
- wire into any live extraction path;
- touch benchmark gold, scoring, or tolerances;
- create a second canonical graph or a second relationship-type vocabulary
  (``RoomTopologyRelationship`` reuses ``TopologyRelationshipType`` --
  see ``pb_wall_room_topology_contracts`` for why its own SHAPE is new
  while the type enum is shared).

SHARED WALLS ARE NEVER DUPLICATED
------------------------------------
A wall used by two rooms remains the SAME single ``WallCandidate`` (same
``candidate_id``) referenced from both rooms' ``bounding_wall_candidate_ids``
-- this was already true from W4/W5 by construction (both rooms' boundary
matching looks up the identical Stage-A-edge-to-wall-candidate mapping).
This module only adds relationship records and resolves each wall's own
``interior_exterior`` classification; it never constructs a second
``WallCandidate`` for an already-known wall id.

AMBIGUITY / FAIL-CLOSED
-------------------------
A wall referenced by three or more distinct rooms is geometrically anomalous
for a simple 2D wall (which has exactly two physical sides) -- rather than
arbitrarily picking two of the three-plus rooms to call "adjacent", this
module emits NO ``ADJACENT_TO``/``SEPARATES`` relationships for that wall at
all, leaves its ``interior_exterior`` as ``"unresolved"``, and records the
anomaly as a reason code on the reissued ``WallCandidate``. A room or wall
whose own W5 status is not ``CANDIDATE`` (e.g. a tiny spurious loop already
flagged ``ABSTAINED``) is still included in wall-usage counting (excluding it
would risk silently treating a real shared wall as exterior merely because
one side was itself flagged for review) but never becomes the SOLE basis for
promoting anything to a higher-confidence status than it already had.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Sequence, Tuple

from pb_migration_contracts import stable_contract_id
from pb_wall_room_topology_contracts import (
    RoomCandidate,
    RoomTopologyRelationship,
    TopologyRelationshipType,
    WallCandidate,
)

REASON_ANOMALOUS_WALL_USAGE = "wall_used_by_three_or_more_rooms_relationship_skipped"


def compute_wall_usage(rooms: Sequence[RoomCandidate]) -> Dict[str, List[str]]:
    """Return wall_candidate_id -> list of room_refs using it, in encounter order."""
    usage: Dict[str, List[str]] = {}
    for room in rooms:
        for wall_id in room.bounding_wall_candidate_ids:
            usage.setdefault(wall_id, []).append(room.room_ref)
    return usage


def derive_room_wall_relationships(
    rooms: Sequence[RoomCandidate], walls: Sequence[WallCandidate]
) -> Tuple[List[RoomCandidate], List[WallCandidate], List[RoomTopologyRelationship]]:
    """Main W6 entry point for one viewport's already-reconstructed rooms/walls."""
    wall_usage = compute_wall_usage(rooms)
    rooms_by_ref = {r.room_ref: r for r in rooms}
    walls_by_id = {w.candidate_id: w for w in walls}

    relationships: List[RoomTopologyRelationship] = []

    # BOUNDED_BY / BOUNDS: one pair of relationships per (room, wall) edge,
    # regardless of how many rooms ultimately share that wall.
    for room in rooms:
        for wall_id in room.bounding_wall_candidate_ids:
            relationships.append(
                RoomTopologyRelationship(
                    relationship_id=stable_contract_id(
                        "roomrel", {"room": room.room_ref, "wall": wall_id, "rel": "bounded_by"}
                    ),
                    subject_ref=room.room_ref,
                    object_ref=wall_id,
                    relationship_type=TopologyRelationshipType.BOUNDED_BY,
                    confidence=room.geometry_confidence,
                )
            )
            relationships.append(
                RoomTopologyRelationship(
                    relationship_id=stable_contract_id(
                        "roomrel", {"room": room.room_ref, "wall": wall_id, "rel": "bounds"}
                    ),
                    subject_ref=wall_id,
                    object_ref=room.room_ref,
                    relationship_type=TopologyRelationshipType.BOUNDS,
                    confidence=room.geometry_confidence,
                )
            )

    # ADJACENT_TO / SEPARATES: only for a wall used by EXACTLY two rooms.
    # Three-or-more is a fail-closed skip (see module docstring); one or
    # zero has no adjacency to express.
    anomalous_wall_ids: set = set()
    interior_wall_ids: set = set()
    exterior_wall_ids: set = set()

    for wall_id, room_refs in wall_usage.items():
        distinct_rooms = list(dict.fromkeys(room_refs))
        if len(distinct_rooms) >= 3:
            anomalous_wall_ids.add(wall_id)
            continue
        if len(distinct_rooms) == 2:
            interior_wall_ids.add(wall_id)
            room_a_ref, room_b_ref = distinct_rooms
            room_a, room_b = rooms_by_ref[room_a_ref], rooms_by_ref[room_b_ref]
            pair_confidence = min(room_a.geometry_confidence, room_b.geometry_confidence)

            relationships.append(
                RoomTopologyRelationship(
                    relationship_id=stable_contract_id(
                        "roomrel", {"a": room_a_ref, "b": room_b_ref, "wall": wall_id, "rel": "adjacent_a_to_b"}
                    ),
                    subject_ref=room_a_ref,
                    object_ref=room_b_ref,
                    relationship_type=TopologyRelationshipType.ADJACENT_TO,
                    confidence=pair_confidence,
                    reason_codes=(f"shared_wall_id:{wall_id}",),
                )
            )
            relationships.append(
                RoomTopologyRelationship(
                    relationship_id=stable_contract_id(
                        "roomrel", {"a": room_b_ref, "b": room_a_ref, "wall": wall_id, "rel": "adjacent_b_to_a"}
                    ),
                    subject_ref=room_b_ref,
                    object_ref=room_a_ref,
                    relationship_type=TopologyRelationshipType.ADJACENT_TO,
                    confidence=pair_confidence,
                    reason_codes=(f"shared_wall_id:{wall_id}",),
                )
            )
            relationships.append(
                RoomTopologyRelationship(
                    relationship_id=stable_contract_id(
                        "roomrel", {"wall": wall_id, "a": room_a_ref, "b": room_b_ref, "rel": "separates"}
                    ),
                    subject_ref=wall_id,
                    object_ref=room_a_ref,
                    relationship_type=TopologyRelationshipType.SEPARATES,
                    confidence=pair_confidence,
                    reason_codes=(f"other_side_room_ref:{room_b_ref}",),
                )
            )
        elif len(distinct_rooms) == 1:
            exterior_wall_ids.add(wall_id)
        # len == 0 cannot occur here (wall_usage only contains walls that
        # appear in at least one room's bounding_wall_candidate_ids).

    # Reissue RoomCandidates with adjacent_room_refs populated.
    adjacency_map: Dict[str, set] = {}
    for rel in relationships:
        if rel.relationship_type == TopologyRelationshipType.ADJACENT_TO:
            adjacency_map.setdefault(rel.subject_ref, set()).add(rel.object_ref)

    updated_rooms: List[RoomCandidate] = []
    for room in rooms:
        adjacent_refs = tuple(sorted(adjacency_map.get(room.room_ref, set())))
        if adjacent_refs == room.adjacent_room_refs:
            updated_rooms.append(room)
        else:
            updated_rooms.append(replace(room, adjacent_room_refs=adjacent_refs))

    # Reissue WallCandidates with interior_exterior resolved.
    updated_walls: List[WallCandidate] = []
    for wall in walls:
        if wall.candidate_id in anomalous_wall_ids:
            reason_codes = tuple(wall.reason_codes) + (REASON_ANOMALOUS_WALL_USAGE,)
            updated_walls.append(replace(wall, reason_codes=reason_codes))
        elif wall.candidate_id in interior_wall_ids:
            updated_walls.append(replace(wall, interior_exterior="interior"))
        elif wall.candidate_id in exterior_wall_ids:
            updated_walls.append(replace(wall, interior_exterior="exterior"))
        else:
            # Used by zero identified rooms (e.g. part of an open, unclosed
            # boundary) -- correctly stays "unresolved", not guessed either way.
            updated_walls.append(wall)

    return updated_rooms, updated_walls, relationships
