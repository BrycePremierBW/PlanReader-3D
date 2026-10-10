"""W4: wall-chain / WallCandidate assembly from W2's graph and W3's junctions.

Converts:

    raw/cleaned Stage-A edges (W2)
    -> classified JunctionCandidate graph (W3)
    -> stable wall chains
    -> WallCandidate (W1 contract, reused unchanged)

Does NOT:
- produce room faces (that is W5 -- ``pb_accuracy_v13_engines_v145.
  extract_planar_faces`` is not imported or invoked here, only inspected
  during design, per the brief);
- compute or emit any quantity / ``QuantityEvidence``;
- wire into any live extraction path;
- touch benchmark gold, scoring, or tolerances;
- invent wall thickness -- every ``WallCandidate`` produced here carries
  ``thickness_m=None``, ``thickness_authority=MeasurementAuthorityType.
  PROVISIONAL``, exactly like a W1-constructed single-line candidate with no
  corroborating dimension evidence yet, because no prior stage (W1-W3)
  established real thickness evidence for these specific candidates. Double-
  line thickness pairing (``pb_vector_geometry_v130.detect_wall_pairs``) is a
  distinct, later concern, not attempted here;
- redesign ``pb_canonical_building.py``. No conflict was found requiring it:
  ``WallCandidate`` (W1) is already designed as the promotion source for a
  future ``CanonicalWall``, and that promotion itself remains a documented
  future stage (topology spec Section 14 / the architecture doc's W12), not
  something W4 needs to build.

CHAIN SEMANTICS (the core rule this module implements)
-------------------------------------------------------
Not every connected segment becomes one wall. Only edges linked by a
``CONTINUES_AS`` relationship (W3) **through a junction that itself permits
extension** are merged into one chain:

- ``COLLINEAR_CONTINUATION``, ``T_JUNCTION`` (its collinear bar pair only --
  a T's stem is linked to the bar by ``BRANCHES_FROM``, never
  ``CONTINUES_AS``, so it is never merged into the bar's chain),
  ``X_CROSSING``, and ``MULTI_WAY`` (each collinear through-pair) are the
  only junction types chain assembly ever extends through.
- ``L_CORNER`` never emits a ``CONTINUES_AS`` relationship at all (W3), so
  two walls meeting at a corner are never merged -- by construction, not by
  a special case added here.
- ``ENDPOINT`` has no partner to continue to -- a chain boundary.
- ``AMBIGUOUS``, ``NEAR_JUNCTION_REVIEW``, ``UNRESOLVED``, and
  ``REJECTED_NON_WALL_CROSSING`` are never extended through, even when a
  ``CONTINUES_AS`` relationship happens to exist for their underlying
  collinear pair (W3 emits that relationship unconditionally from the raw
  angle grouping -- it does not itself know the arm was later demoted, e.g.
  by the short-isolated-arm rule). Chain assembly re-checks the junction's
  actual type/status before ever using one of its relationships to merge,
  which is what makes this fail-closed in practice, not merely in principle.

This means: "do not promote chains containing unresolved critical
ambiguity" (the brief's Section G) is satisfied by *never merging across*
such a junction -- the edges on either side still each become their own
(real, evidenced) ``WallCandidate`` with ``status=CANDIDATE`` and a reason
code identifying the blocking junction, rather than either silently forming
a false combined wall or silently disappearing.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_wall_room_topology_junction_classifier import deduplicate_coincident_edges
from pb_wall_room_topology_primitive_lineage import LINEAGE_KEY
from pb_wall_room_topology_contracts import (
    JunctionCandidate,
    JunctionType,
    TopologyRelationship,
    TopologyRelationshipType,
    WallCandidate,
)
from pb_wall_room_topology_wall_identity_v2 import canonical_path_fingerprint

# Junction types through which chain assembly is permitted to merge two
# edges into one WallCandidate. Deliberately does not include L_CORNER (by
# design, per module docstring) or any of the four abstained/blocking types.
_CHAIN_EXTENSION_JUNCTION_TYPES = frozenset(
    {
        JunctionType.COLLINEAR_CONTINUATION,
        JunctionType.T_JUNCTION,
        JunctionType.X_CROSSING,
        JunctionType.MULTI_WAY,
    }
)


def _junction_allows_chain_extension(junction: JunctionCandidate) -> bool:
    return (
        junction.junction_type in _CHAIN_EXTENSION_JUNCTION_TYPES
        and junction.status == EvidenceResolutionStatus.CANDIDATE
    )


class _UnionFind:
    """Minimal union-find keyed by (string) edge id."""

    def __init__(self, keys: Sequence[str]) -> None:
        self._parent: Dict[str, str] = {k: k for k in keys}

    def find(self, key: str) -> str:
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, a: str, b: str) -> None:
        if a not in self._parent or b not in self._parent:
            return
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic tie-break so the resulting root -- and therefore
            # nothing observable -- never depends on union call order.
            lo, hi = sorted((ra, rb))
            self._parent[hi] = lo

    def groups(self) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = {}
        for key in self._parent:
            result.setdefault(self.find(key), set()).add(key)
        return result


def _junction_by_node_idx(
    graph: Dict[str, Any], junctions: Sequence[JunctionCandidate]
) -> Dict[int, JunctionCandidate]:
    """Map a Stage-A graph node index back to its classified JunctionCandidate.

    W3's public ``classify_junctions`` returns a flat list without the
    internal node-index mapping it used while building it, so this rebuilds
    the mapping the same way W3 itself does: by rounding each node's own
    position to 6 decimals, exactly as ``classify_junctions`` does when
    generating each junction's content-derived ``node_id``. This is a
    position match, not an identity match -- two distinct nodes sharing a
    position in genuinely degenerate input would collide here exactly as
    noted as a known limitation in W3's own docstring; not re-solved in W4.
    """
    by_position: Dict[Tuple[float, float], JunctionCandidate] = {
        tuple(round(c, 6) for c in j.position_pt): j for j in junctions
    }
    mapping: Dict[int, JunctionCandidate] = {}
    for node in graph["nodes"]:
        key = (round(node["x"], 6), round(node["y"], 6))
        junction = by_position.get(key)
        if junction is not None:
            mapping[node["id"]] = junction
    return mapping


def _canonical_fallback_edge_order(
    edge_ids: Set[str],
    edges_by_id: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Replay-stable iteration order for a non-simple chain's edges.

    ``edge_ids`` is an unordered set of strings, so iterating it directly makes
    the fallback point order -- and therefore the content-derived candidate id
    and the physical-identity path -- depend on the interpreter's string-hash
    seed. Order the edges by their own source coordinates instead (the edge id
    only breaks exact coordinate ties). This deliberately changes nothing but
    the order: the fallback still uses exactly the same points as before, and
    only their previously hash-dependent iteration order is fixed.
    """

    def key(edge_id: str) -> Tuple[float, float, float, float, str]:
        edge = edges_by_id[edge_id]
        return (
            float(edge["x1"]),
            float(edge["y1"]),
            float(edge["x2"]),
            float(edge["y2"]),
            str(edge_id),
        )

    return sorted(edge_ids, key=key)


def _order_chain_path(
    edge_ids: Set[str],
    edges_by_id: Dict[str, Dict[str, Any]],
    node_lookup: Dict[int, Dict[str, float]],
) -> Tuple[List[Tuple[float, float]], int, int, bool]:
    """Order a chain's edges into one continuous polyline.

    Returns ``(ordered_points, start_node_idx, end_node_idx, is_simple_path)``.
    ``is_simple_path`` is False only for a degenerate input (a closed loop,
    which chain assembly's own merge rules should never actually produce --
    see module docstring -- but this does not raise on one; it falls back to
    a best-effort point list and lets the caller decide how to flag it).
    """
    if len(edge_ids) == 1:
        (only_id,) = tuple(edge_ids)
        edge = edges_by_id[only_id]
        return (
            [(edge["x1"], edge["y1"]), (edge["x2"], edge["y2"])],
            edge["a"],
            edge["b"],
            True,
        )

    adjacency: Dict[int, List[str]] = {}
    for edge_id in edge_ids:
        edge = edges_by_id[edge_id]
        adjacency.setdefault(edge["a"], []).append(edge_id)
        adjacency.setdefault(edge["b"], []).append(edge_id)

    endpoints = sorted(node_idx for node_idx, incident in adjacency.items() if len(incident) == 1)
    if len(endpoints) != 2:
        # Degenerate (closed loop, or a branch that should be impossible
        # given the merge rules above) -- best-effort fallback, flagged by
        # the caller via is_simple_path=False rather than raising.
        points: List[Tuple[float, float]] = []
        start = min(adjacency)
        for edge_id in _canonical_fallback_edge_order(edge_ids, edges_by_id):
            edge = edges_by_id[edge_id]
            points.append((edge["x1"], edge["y1"]))
        end = max(adjacency)
        return points, start, end, False

    start_node, end_node = endpoints
    points = [(node_lookup[start_node]["x"], node_lookup[start_node]["y"])]
    visited: Set[str] = set()
    current = start_node
    while True:
        remaining = [eid for eid in adjacency[current] if eid not in visited]
        if not remaining:
            break
        edge_id = min(remaining)  # deterministic when a node briefly has >1 unvisited option
        visited.add(edge_id)
        edge = edges_by_id[edge_id]
        nxt = edge["b"] if edge["a"] == current else edge["a"]
        points.append((node_lookup[nxt]["x"], node_lookup[nxt]["y"]))
        current = nxt
    return points, start_node, end_node, True


def _canonical_wall_candidate_id(
    viewport_id: str, points: Sequence[Tuple[float, float]]
) -> str:
    """Content-derived, direction-invariant, path-sensitive wall candidate id.

    Priority-2 fix: the previous endpoint-only hash collided for geometrically
    different chains that shared the same outer endpoints. Identity now hashes
    the direction-canonical, collinear-collapsed centerline fingerprint so:

    - reversed traversal keeps the same id;
    - collinear re-chunking of one physical path keeps the same id;
    - genuinely different interior paths get different ids;
    - input list order never participates (fingerprint is geometric).

    Provenance / U1 source-primitive ids are intentionally NOT part of this
    assembly id. They remain in the physical-wall identity sidecar
    (``canonical_wall_candidate_id_v2``), which separates candidate identity
    from publication equivalence. Mixing provenance into assembly ids would
    break legitimate re-chunking when fragment source ids differ while the
    physical centerline is unchanged.

    This module still does not publish quantities or raise firm authority.
    """
    fingerprint = canonical_path_fingerprint(points)
    return stable_contract_id(
        "wall",
        {"viewport_id": viewport_id, "path_fingerprint": fingerprint},
    )


class W4SourceCandidateAddressCollision(ValueError):
    """Producer-proven W4 address ambiguity; never select a last-writer wall."""


def _source_owned_collision_candidate_addresses(
    walls: Sequence[WallCandidate],
    edges_by_id: Dict[str, Dict[str, Any]],
    edge_to_wall: Dict[str, str],
) -> tuple[list[WallCandidate], dict[str, str]]:
    """Disambiguate only W4 *addresses* whose geometric hashes collided.

    A new address is NOT evidence that walls are physically different.
    Incomplete or indistinguishable original source evidence fails closed;
    never choose one conflicting row by iteration order.
    """
    by_id: dict[str, list[WallCandidate]] = defaultdict(list)
    for wall in walls:
        by_id[wall.candidate_id].append(wall)
    collisions = {cid: group for cid, group in by_id.items() if len(group) > 1}
    if not collisions:
        return list(walls), dict(edge_to_wall)

    replacements: dict[int, WallCandidate] = {}
    new_ids: set[str] = set()
    unchanged_ids = set(by_id) - set(collisions)
    for old_id, group in sorted(collisions.items()):
        group_keys: set[str] = set()
        group_edges: set[str] = set()
        for wall in group:
            edges = tuple(wall.face_a_segment_ids) + tuple(wall.face_b_segment_ids or ())
            if not edges or len(set(edges)) != len(edges):
                raise W4SourceCandidateAddressCollision("W4 collision has absent or duplicated source edges")
            if group_edges.intersection(edges):
                raise W4SourceCandidateAddressCollision("W4 collision has competing owners of one source edge")
            group_edges.update(edges)
            source_parts = []
            for eid in edges:
                edge = edges_by_id.get(str(eid))
                if not isinstance(edge, dict):
                    raise W4SourceCandidateAddressCollision("W4 collision has missing original source edge")
                lineage = edge.get(LINEAGE_KEY) or {}
                raw = lineage.get("source_primitive_ids") if isinstance(lineage, dict) else None
                if (not isinstance(raw, (list, tuple)) or not raw
                        or any(not isinstance(v, str) or not v.strip() for v in raw)): 
                    raise W4SourceCandidateAddressCollision("W4 collision lacks positive source ancestry")
                try:
                    a = (float(edge["x1"]), float(edge["y1"]))
                    b = (float(edge["x2"]), float(edge["y2"]))
                except (KeyError, ValueError, TypeError, OverflowError):
                    raise W4SourceCandidateAddressCollision("W4 collision lacks original source geometry") from None
                if (not all(math.isfinite(x) for x in (*a, *b)) or a == b):
                    raise W4SourceCandidateAddressCollision("W4 collision has invalid source geometry")
                source_parts.append({
                    "positive_source_primitive_ids": sorted(set(raw)),
                    "source_line": tuple(sorted((a, b))),
                })
            terminals = tuple(wall.end_node_ids)
            if len(terminals) != 2 or any(not isinstance(x, str) or not x for x in terminals):
                raise W4SourceCandidateAddressCollision("W4 collision lacks junction ownership")
            new_id = stable_contract_id("wall", {
                "geometric_candidate_id": old_id,
                "viewport_id": wall.viewport_id,
                "original_source_segments": sorted(source_parts, key=lambda p: str(p)),
                "terminal_source_junction_ids": sorted(terminals),
            })
            if new_id in unchanged_ids or new_id in group_keys or new_id in new_ids:
                raise W4SourceCandidateAddressCollision("W4 collision not uniquely source-disambiguated")
            group_keys.add(new_id)
            new_ids.add(new_id)
            marked = replace(
                wall, candidate_id=new_id,
                metadata={**dict(wall.metadata), "precollision_w4_candidate_id": old_id},
                reason_codes=tuple((*wall.reason_codes, "source_owned_w4_candidate_address_collision")),
            )
            replacements[id(wall)] = marked

    revised = []
    remapped = dict(edge_to_wall)
    for wall in walls:
        if wall.candidate_id not in collisions:
            revised.append(wall)
            continue
        edges = tuple(wall.face_a_segment_ids) + tuple(wall.face_b_segment_ids or ())
        converted = replacements.get(id(wall))
        if converted is None:
            raise W4SourceCandidateAddressCollision("W4 collided wall lost source edge ownership")
        revised.append(converted)
        for eid in edges:
            if edge_to_wall.get(eid) != wall.candidate_id:
                raise W4SourceCandidateAddressCollision("W4 source edge owner unexpectedly changed")
            remapped[eid] = converted.candidate_id
    if len({wall.candidate_id for wall in revised}) != len(revised):
        raise W4SourceCandidateAddressCollision("W4 source candidate addresses remain duplicated")
    return revised, remapped


def assemble_wall_candidates(
    graph: Dict[str, Any],
    junctions: Sequence[JunctionCandidate],
    relationships: Sequence[TopologyRelationship],
    *,
    viewport_id: str,
) -> Tuple[List[WallCandidate], Dict[str, str]]:
    """Assemble WallCandidates from a Stage-A graph and its W3 classification.

    ``graph`` should be the same (already deduplicated) graph that produced
    ``junctions``/``relationships`` -- ``classify_junctions`` already applies
    ``deduplicate_coincident_edges`` internally, so pass it the same raw
    Stage-A graph you gave to that function, not a separately-deduplicated
    copy (a second, independent dedup pass would not be wrong, merely
    redundant and a potential source of edge-id drift).

    Returns ``(wall_candidates, edge_id_to_wall_candidate_id)`` -- the second
    value is the mapping ``rekey_junctions_to_wall_candidates`` needs.
    """
    # classify_junctions applies this same dedup internally before deriving
    # junctions/relationships -- applying it again here (idempotent) keeps
    # this function's own edge set consistent with what those relationships
    # actually reference. Without this, a duplicate edge that W3 already
    # excluded from every relationship would still appear in this function's
    # own edge set, never get unioned with anything, and surface as a
    # spurious extra single-edge WallCandidate identical to the real one.
    graph, _ = deduplicate_coincident_edges(graph)
    edges_by_id = {str(e.get("id")): e for e in graph["edges"] if not e.get("_removed")}
    node_lookup = {n["id"]: {"x": n["x"], "y": n["y"]} for n in graph["nodes"]}
    junction_by_node_idx = _junction_by_node_idx(graph, junctions)

    uf = _UnionFind(edges_by_id.keys())
    for relationship in relationships:
        if relationship.relationship_type != TopologyRelationshipType.CONTINUES_AS:
            continue
        via = next(
            (j for j in junctions if j.node_id == relationship.via_junction_id), None
        )
        if via is not None and _junction_allows_chain_extension(via):
            if relationship.to_edge_id is not None:
                uf.union(relationship.from_edge_id, relationship.to_edge_id)

    groups = uf.groups()

    wall_candidates: List[WallCandidate] = []
    edge_id_to_wall_candidate_id: Dict[str, str] = {}

    for edge_ids in groups.values():
        points, start_idx, end_idx, is_simple_path = _order_chain_path(
            edge_ids, edges_by_id, node_lookup
        )
        candidate_id = _canonical_wall_candidate_id(viewport_id, points)

        start_junction = junction_by_node_idx.get(start_idx)
        end_junction = junction_by_node_idx.get(end_idx)

        reason_codes: List[str] = [f"assembled_from_{len(edge_ids)}_stage_a_edges"]
        if not is_simple_path:
            reason_codes.append("non_simple_chain_topology_fallback_ordering")
        for label, junction in (("start", start_junction), ("end", end_junction)):
            if junction is not None and junction.junction_type not in (
                JunctionType.ENDPOINT,
                *_CHAIN_EXTENSION_JUNCTION_TYPES,
                JunctionType.L_CORNER,
            ):
                reason_codes.append(
                    f"chain_extension_blocked_by:{junction.junction_type.value}_at_{label}"
                )

        boundary_confidences = [
            j.confidence for j in (start_junction, end_junction) if j is not None
        ]
        confidence = min(boundary_confidences) if boundary_confidences else 0.5

        end_node_ids = (
            start_junction.node_id if start_junction is not None else f"node_{start_idx}",
            end_junction.node_id if end_junction is not None else f"node_{end_idx}",
        )
        junction_types = (
            start_junction.junction_type if start_junction is not None else JunctionType.UNRESOLVED,
            end_junction.junction_type if end_junction is not None else JunctionType.UNRESOLVED,
        )

        # face_a_segment_ids must preserve chain order for provenance
        # traceability, not just be an unordered set.
        ordered_edge_ids = tuple(
            eid
            for eid in (
                [min(edge_ids)] if len(edge_ids) == 1 else _chain_order_edge_ids(edge_ids, edges_by_id)
            )
        )

        wall = WallCandidate(
            candidate_id=candidate_id,
            viewport_id=viewport_id,
            representation="single_line",
            centerline_pts=tuple(points),
            face_a_segment_ids=ordered_edge_ids,
            face_b_segment_ids=None,
            is_curved=False,
            curve_control_pts=None,
            thickness_m=None,
            thickness_authority=MeasurementAuthorityType.PROVISIONAL,
            length_m=None,
            end_node_ids=end_node_ids,
            junction_types=junction_types,
            interior_exterior="unresolved",
            level_id=None,
            status=EvidenceResolutionStatus.CANDIDATE,
            confidence=confidence,
            reason_codes=tuple(reason_codes),
        )
        wall_candidates.append(wall)
        for edge_id in edge_ids:
            edge_id_to_wall_candidate_id[edge_id] = candidate_id

    return _source_owned_collision_candidate_addresses(
        wall_candidates, edges_by_id, edge_id_to_wall_candidate_id
    )


def _chain_order_edge_ids(
    edge_ids: Set[str], edges_by_id: Dict[str, Dict[str, Any]]
) -> List[str]:
    adjacency: Dict[int, List[str]] = {}
    for edge_id in edge_ids:
        edge = edges_by_id[edge_id]
        adjacency.setdefault(edge["a"], []).append(edge_id)
        adjacency.setdefault(edge["b"], []).append(edge_id)
    endpoints = sorted(n for n, incident in adjacency.items() if len(incident) == 1)
    if len(endpoints) != 2:
        return sorted(edge_ids)
    ordered: List[str] = []
    visited: Set[str] = set()
    current = endpoints[0]
    while True:
        remaining = [eid for eid in adjacency[current] if eid not in visited]
        if not remaining:
            break
        edge_id = min(remaining)
        visited.add(edge_id)
        ordered.append(edge_id)
        edge = edges_by_id[edge_id]
        current = edge["b"] if edge["a"] == current else edge["a"]
    return ordered


def rekey_junctions_to_wall_candidates(
    junctions: Sequence[JunctionCandidate],
    edge_id_to_wall_candidate_id: Dict[str, str],
) -> List[JunctionCandidate]:
    """Return NEW JunctionCandidate records with wall-candidate-keyed ids.

    Never mutates the original (frozen/immutable) records -- these are
    additional, superseding derived records, consistent with the migration
    contracts' own layered-derivation philosophy. The original W3 output
    remains valid and inspectable; this is what a caller wanting the W4-aware
    view should use instead.

    A junction whose several original arms turn out to belong to the SAME
    merged wall (e.g. a T-junction's two collinear bar arms) is re-keyed to
    ONE deduplicated entry for that wall, with one representative angle --
    not two duplicate entries for the same wall id, which would violate
    JunctionCandidate's own uniqueness contract for a field that is supposed
    to enumerate *distinct* incident walls, not raw arms.
    """
    rekeyed: List[JunctionCandidate] = []
    for junction in junctions:
        if not junction.incident_wall_candidate_ids:
            rekeyed.append(junction)
            continue

        seen_wall_ids: List[str] = []
        angle_for_wall: Dict[str, float] = {}
        unresolved_edge_ids: List[str] = []
        for edge_id, angle in zip(junction.incident_wall_candidate_ids, junction.incident_angles_deg):
            wall_id = edge_id_to_wall_candidate_id.get(edge_id)
            if wall_id is None:
                # Should not happen -- every real edge is assigned to exactly
                # one wall candidate by assemble_wall_candidates. Defensive,
                # not silently dropped: recorded and flagged below.
                unresolved_edge_ids.append(edge_id)
                continue
            if wall_id not in angle_for_wall:
                seen_wall_ids.append(wall_id)
                angle_for_wall[wall_id] = angle

        reason_codes = list(junction.reason_codes)
        if unresolved_edge_ids:
            reason_codes.append(
                "rekey_incomplete_missing_wall_candidate_for:" + ",".join(unresolved_edge_ids)
            )

        rekeyed.append(
            JunctionCandidate(
                node_id=junction.node_id,
                document_id=junction.document_id,
                page_id=junction.page_id,
                viewport_id=junction.viewport_id,
                position_pt=junction.position_pt,
                junction_type=junction.junction_type,
                incident_wall_candidate_ids=tuple(seen_wall_ids),
                incident_angles_deg=tuple(angle_for_wall[w] for w in seen_wall_ids),
                status=junction.status,
                confidence=junction.confidence,
                evidence_ids=junction.evidence_ids,
                conflict_evidence_ids=junction.conflict_evidence_ids,
                reason_codes=tuple(reason_codes),
            )
        )
    return rekeyed


def assemble_wall_topology(
    graph: Dict[str, Any],
    junctions: Sequence[JunctionCandidate],
    relationships: Sequence[TopologyRelationship],
    *,
    viewport_id: str,
) -> Tuple[List[WallCandidate], List[JunctionCandidate]]:
    """Main W4 entry point: WallCandidate assembly + junction re-keying.

    ``graph``/``junctions``/``relationships`` are exactly W3's
    ``classify_junctions(...)`` inputs/outputs for one viewport.
    """
    wall_candidates, edge_id_to_wall_candidate_id = assemble_wall_candidates(
        graph, junctions, relationships, viewport_id=viewport_id
    )
    rekeyed_junctions = rekey_junctions_to_wall_candidates(
        junctions, edge_id_to_wall_candidate_id
    )
    return wall_candidates, rekeyed_junctions
