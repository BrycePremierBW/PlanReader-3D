"""W9: topology confidence / conflict reconciliation.

Aggregates and cross-checks entities already produced by W1-W8 for one
viewport into a single ``TopologyReconciliationSummary``. This stage is a
REPORTING pass, not a decision-making one:

- No new confidence model. ``status_counts`` tallies the ONE
  ``EvidenceResolutionStatus`` vocabulary already used by
  ``JunctionCandidate``/``WallCandidate``/``RoomCandidate``, plus each
  entity's own existing discriminator (``TopologyRelationshipType`` for
  relationships, ``host_status`` for opening hosts) -- nothing new is
  invented.
- No promotion. Nothing here changes any entity's ``status``,
  ``confidence``, ``label``, or ``interior_exterior`` -- every dataclass
  this module reads is returned untouched; this module only ever
  constructs the new, purely-additive ``TopologyReconciliationSummary``.
- No re-deciding. W6's ``ambiguous_host``/3+-room anomalies, W7's
  ``ambiguous_host`` opening candidates, and W8's ``ABSTAINED`` label
  conflicts are surfaced in ``flagged_entities`` exactly as those stages
  left them -- never resolved, merged, or overridden here.

FLAGGING RULES (per entity type, because "non-empty reason_codes" means
different things in different W1-W8 contracts)
-----------------------------------------------
- ``JunctionCandidate``: flagged when ``status`` is not
  ``CANDIDATE``/``CORROBORATED`` (i.e. ``RAW``/``CONFLICT``/
  ``ABSTAINED``), OR ``reason_codes`` is non-empty -- W3 only ever
  populates ``reason_codes`` for a genuine review/anomaly case
  (near-miss demotions, short-arm demotions, ambiguous/unresolved
  classifications); every ordinary ENDPOINT/L_CORNER/T_JUNCTION/
  X_CROSSING/COLLINEAR_CONTINUATION/MULTI_WAY classification carries an
  empty ``reason_codes`` at baseline, so non-empty is never routine here.
- ``WallCandidate``: W4 unconditionally attaches a routine
  ``"assembled_from_N_stage_a_edges"`` provenance code to EVERY wall
  (verified by inspection, not assumed) -- that one code is explicitly
  excluded from flagging. A wall is flagged when ``status`` is not
  ``CANDIDATE``/``CORROBORATED``, it carries any OTHER reason code
  (``non_simple_chain_topology_fallback_ordering``,
  ``chain_extension_blocked_by:...``, W6's
  ``REASON_ANOMALOUS_WALL_USAGE``), or ``interior_exterior ==
  "unresolved"`` even with no extra reason code yet (e.g. a wall no room
  ever bounded) -- still worth surfacing for review.
- ``RoomCandidate``: flagged when ``status`` is not
  ``CANDIDATE``/``CORROBORATED``, ``reason_codes`` is non-empty, or
  ``area_conflict`` is set. NOT flagged merely for ``label == ""`` --
  most rooms never have a drawing-text label at all, so that alone is
  not an anomaly.
- ``RoomTopologyRelationship``: NEVER flagged by ``reason_codes`` --
  W6 uses that field for routine provenance on every relationship it
  creates (``shared_wall_id:...``, ``other_side_room_ref:...``), and the
  genuinely ambiguous case (a wall used by 3+ rooms) already produces NO
  relationship at all rather than a flagged one. Relationships only
  contribute to ``status_counts`` and to the referential-integrity
  checks below.
- ``OpeningHostCandidate``: flagged whenever ``host_status != "hosted"``
  -- as of W7, every candidate is ``"ambiguous_host"`` by design, so
  every one is currently surfaced; this stays correct once a later stage
  can ever produce ``"hosted"``.

CROSS-STAGE REFERENTIAL-INTEGRITY CHECKS (the genuinely new value this
stage adds -- structural consistency across already-existing outputs,
not new domain judgment)
-----------------------------------------------------------------------
- Every ``RoomCandidate.bounding_wall_candidate_ids`` / ``adjacent_room_refs``
  entry must resolve to a wall/room actually present in the inputs.
- Every ``OpeningHostCandidate.candidate_wall_ids_considered`` entry must
  resolve to a wall actually present in the inputs.
- Every ``RoomTopologyRelationship``'s wall-side and room-side references
  (including the second room carried in a ``SEPARATES`` relationship's
  ``other_side_room_ref:`` reason code) must resolve to entities present
  in the inputs.
- A ``WallCandidate`` with ``interior_exterior == "unresolved"`` that IS
  referenced by at least one room's ``bounding_wall_candidate_ids`` (so
  W6 actually considered it) but does NOT carry
  ``REASON_ANOMALOUS_WALL_USAGE`` is an inconsistency -- under W6's own
  rules that combination should not occur.

Deliberately does NOT check ``JunctionCandidate.incident_wall_candidate_ids``
against the wall list: per that dataclass's own documented sequencing
note, those currently reference Stage-A edge ids, not
``WallCandidate.candidate_id`` values -- a different, unrelated
namespace, not a dangling reference.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Mapping, Sequence, Tuple

from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_contracts import (
    JunctionCandidate,
    OpeningHostCandidate,
    RoomCandidate,
    RoomTopologyRelationship,
    TopologyRelationshipType,
    WallCandidate,
)
from pb_wall_room_topology_room_wall_relationships import REASON_ANOMALOUS_WALL_USAGE

RECONCILIATION_SCHEMA_VERSION = "1.0"

_HEALTHY_STATUSES = frozenset({EvidenceResolutionStatus.CANDIDATE, EvidenceResolutionStatus.CORROBORATED})

# W4 (pb_wall_room_topology_wall_assembly) unconditionally attaches this
# routine provenance code to every WallCandidate -- never a signal of
# anything needing review, so it is excluded from wall flagging.
_ROUTINE_WALL_PROVENANCE_RE = re.compile(r"^assembled_from_\d+_stage_a_edges$")


def _wall_reason_codes_needing_review(reason_codes: Tuple[str, ...]) -> Tuple[str, ...]:
    return tuple(code for code in reason_codes if not _ROUTINE_WALL_PROVENANCE_RE.match(code))


@dataclass(frozen=True)
class FlaggedEntity:
    """One entity carried over from W1-W8 that still needs review.

    This is purely a pointer back into the already-existing record (by
    ``entity_type`` + ``entity_id``) plus the reasons already attached to
    it there -- it duplicates no data and resolves nothing.
    """

    entity_type: str
    entity_id: str
    status_or_discriminator: str
    reason_codes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TopologyReconciliationSummary:
    viewport_id: str
    status_counts: Mapping[str, Mapping[str, int]]
    flagged_entities: Tuple[FlaggedEntity, ...]
    integrity_issues: Tuple[str, ...]
    schema_version: str = RECONCILIATION_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "viewport_id": self.viewport_id,
            "status_counts": {k: dict(v) for k, v in self.status_counts.items()},
            "flagged_entities": [
                {
                    "entity_type": f.entity_type,
                    "entity_id": f.entity_id,
                    "status_or_discriminator": f.status_or_discriminator,
                    "reason_codes": list(f.reason_codes),
                }
                for f in self.flagged_entities
            ],
            "integrity_issues": list(self.integrity_issues),
            "schema_version": self.schema_version,
        }


def _tally(items, key) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        counts[key(item)] = counts.get(key(item), 0) + 1
    return counts


def reconcile_topology(
    viewport_id: str,
    *,
    junctions: Sequence[JunctionCandidate] = (),
    walls: Sequence[WallCandidate] = (),
    rooms: Sequence[RoomCandidate] = (),
    room_relationships: Sequence[RoomTopologyRelationship] = (),
    opening_hosts: Sequence[OpeningHostCandidate] = (),
) -> TopologyReconciliationSummary:
    """Main W9 entry point for one viewport's already-produced W1-W8 output."""
    status_counts: Dict[str, Dict[str, int]] = {
        "junctions": _tally(junctions, lambda j: j.status.value),
        "walls": _tally(walls, lambda w: w.status.value),
        "rooms": _tally(rooms, lambda r: r.status.value),
        "room_relationships": _tally(room_relationships, lambda r: r.relationship_type.value),
        "opening_hosts": _tally(opening_hosts, lambda h: h.host_status),
    }

    flagged: list = []
    for junction in junctions:
        if junction.status not in _HEALTHY_STATUSES or junction.reason_codes:
            flagged.append(
                FlaggedEntity("junction", junction.node_id, junction.status.value, junction.reason_codes)
            )
    for wall in walls:
        review_reasons = _wall_reason_codes_needing_review(wall.reason_codes)
        needs_review = (
            wall.status not in _HEALTHY_STATUSES
            or bool(review_reasons)
            or wall.interior_exterior == "unresolved"
        )
        if needs_review:
            flagged.append(
                FlaggedEntity("wall", wall.candidate_id, wall.status.value, wall.reason_codes)
            )
    for room in rooms:
        needs_review = (
            room.status not in _HEALTHY_STATUSES
            or bool(room.reason_codes)
            or room.area_conflict is not None
        )
        if needs_review:
            flagged.append(
                FlaggedEntity("room", room.room_ref, room.status.value, room.reason_codes)
            )
    for host in opening_hosts:
        if host.host_status != "hosted":
            flagged.append(
                FlaggedEntity("opening_host", host.host_candidate_id, host.host_status, host.reason_codes)
            )

    integrity_issues = _referential_integrity_issues(walls, rooms, room_relationships, opening_hosts)

    return TopologyReconciliationSummary(
        viewport_id=viewport_id,
        status_counts=status_counts,
        flagged_entities=tuple(flagged),
        integrity_issues=tuple(integrity_issues),
    )


def _referential_integrity_issues(
    walls: Sequence[WallCandidate],
    rooms: Sequence[RoomCandidate],
    room_relationships: Sequence[RoomTopologyRelationship],
    opening_hosts: Sequence[OpeningHostCandidate],
) -> list:
    wall_ids = {w.candidate_id for w in walls}
    room_refs = {r.room_ref for r in rooms}
    walls_by_id = {w.candidate_id: w for w in walls}
    issues: list = []

    for room in rooms:
        for wall_id in room.bounding_wall_candidate_ids:
            if wall_id not in wall_ids:
                issues.append(f"dangling_wall_reference: room={room.room_ref} references missing wall={wall_id}")
        for adjacent_ref in room.adjacent_room_refs:
            if adjacent_ref not in room_refs:
                issues.append(
                    f"dangling_room_reference: room={room.room_ref} references missing adjacent room={adjacent_ref}"
                )

    for host in opening_hosts:
        for wall_id in host.candidate_wall_ids_considered:
            if wall_id not in wall_ids:
                issues.append(
                    f"dangling_wall_reference: opening_host={host.host_candidate_id} references missing wall={wall_id}"
                )

    for rel in room_relationships:
        wall_side, room_sides = _relationship_wall_and_room_refs(rel)
        if wall_side is not None and wall_side not in wall_ids:
            issues.append(
                f"dangling_wall_reference: relationship={rel.relationship_id} references missing wall={wall_side}"
            )
        for room_ref in room_sides:
            if room_ref not in room_refs:
                issues.append(
                    f"dangling_room_reference: relationship={rel.relationship_id} references missing room={room_ref}"
                )

    referenced_wall_ids = {wall_id for room in rooms for wall_id in room.bounding_wall_candidate_ids}
    for wall_id in referenced_wall_ids:
        wall = walls_by_id.get(wall_id)
        if wall is None:
            continue  # already reported above as a dangling reference
        if wall.interior_exterior == "unresolved" and REASON_ANOMALOUS_WALL_USAGE not in wall.reason_codes:
            issues.append(
                f"unresolved_without_anomaly_reason: wall={wall.candidate_id} is referenced by a room, "
                f"interior_exterior is unresolved, but carries no {REASON_ANOMALOUS_WALL_USAGE} reason code"
            )

    return issues


def _relationship_wall_and_room_refs(
    rel: RoomTopologyRelationship,
) -> Tuple[str, Tuple[str, ...]]:
    """Return (wall_id_or_None, room_refs) referenced by *rel*."""
    if rel.relationship_type == TopologyRelationshipType.BOUNDED_BY:
        return rel.object_ref, (rel.subject_ref,)
    if rel.relationship_type == TopologyRelationshipType.BOUNDS:
        return rel.subject_ref, (rel.object_ref,)
    if rel.relationship_type == TopologyRelationshipType.ADJACENT_TO:
        return None, (rel.subject_ref, rel.object_ref)
    if rel.relationship_type == TopologyRelationshipType.SEPARATES:
        other_room_refs = tuple(
            rc.split(":", 1)[1] for rc in rel.reason_codes if rc.startswith("other_side_room_ref:")
        )
        return rel.subject_ref, (rel.object_ref,) + other_room_refs
    return None, ()
