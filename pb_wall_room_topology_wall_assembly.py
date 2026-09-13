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

import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_wall_room_topology_junction_classifier import deduplicate_coincident_edges
from pb_wall_room_topology_contracts import (
    JunctionCandidate,
    JunctionType,
    TopologyRelationship,
    TopologyRelationshipType,
    WallCandidate,
)

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
        for edge_id in edge_ids:
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


def _polyline_length(points: Sequence[Tuple[float, float]]) -> float:
    return sum(
        math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        for i in range(len(points) - 1)
    )


def _point_at_arc_length(points: Sequence[Tuple[float, float]], target: float) -> Tuple[float, float]:
    """Point at arc-length ``target`` along the piecewise-linear ``points``
    path (clamped to the path's own extent)."""
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


# Deciles (10%..90% of the path's own arc length) -- a fixed, round sample
# count chosen for the fingerprint below, not tuned to any one project's
# geometry. See _shape_fingerprint's own docstring for why this, rather than
# the chain's raw interior vertices, is what gets hashed.
_SHAPE_FINGERPRINT_SAMPLE_FRACTIONS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def _shape_fingerprint(points: Sequence[Tuple[float, float]]) -> Tuple[float, ...]:
    """Direction-canonical, re-chunking-stable fingerprint of a polyline's
    own SHAPE, expressed as each fixed-arc-length sample point's
    perpendicular deviation from the straight chord joining the path's two
    endpoints.

    Why not just hash the endpoints (the previous behaviour), and why not
    hash the raw interior vertices directly:

    - Endpoints alone is what caused a real, confirmed defect: on real
      Baghau p36 data, two geometrically DISTINCT diagonal traces (different
      constituent Stage-A edges, different interior paths) happened to share
      both outer endpoints and collided onto the same candidate_id, which
      then crashed a downstream evidence-ranking pass expecting per-object
      identity uniqueness.
    - Hashing the raw interior vertices directly would break the
      long-standing, deliberately-tested invariant that the SAME straight
      wall drawn as one segment vs. pre-split into three fragments must
      yield the IDENTICAL id (``test_12_split_merge_invariance_same_wall_id``)
      -- re-chunking changes which points exist along the path without
      changing the path's own shape.

    Sampling the path's own shape at FIXED arc-length fractions (rather than
    at its raw, chunking-dependent vertices) resolves both: interpolating a
    piecewise-linear path at a fixed fraction of its own length gives the
    same point regardless of how many vertices define the straight sections
    between real shape changes, so harmless re-chunking is still invariant;
    two chains that are genuinely different shapes (even ones whose
    consecutive-segment angle deltas are each individually small -- as the
    real Baghau collision's own two colliding chains were) accumulate a
    measurably different deviation from their shared chord, so they are no
    longer treated as the same id merely for sharing two endpoints.

    Deterministic and pure: no randomness, no dependency on dict/set
    iteration order (the caller is responsible for supplying ``points`` in
    one canonical direction -- see ``_canonical_wall_candidate_id``).
    """
    if len(points) < 3:
        return ()
    ax, ay = points[0]
    bx, by = points[-1]
    chord_dx, chord_dy = bx - ax, by - ay
    chord_len = math.hypot(chord_dx, chord_dy)
    if chord_len <= 0.0:
        return ()
    ux, uy = chord_dx / chord_len, chord_dy / chord_len
    total_len = _polyline_length(points)
    samples = []
    for fraction in _SHAPE_FINGERPRINT_SAMPLE_FRACTIONS:
        px, py = _point_at_arc_length(points, fraction * total_len)
        # Perpendicular (cross-product) offset of this sample from the chord.
        offset = (px - ax) * (-uy) + (py - ay) * ux
        samples.append(round(offset, 6))
    return tuple(samples)


def _canonical_wall_candidate_id(
    viewport_id: str, points: Sequence[Tuple[float, float]]
) -> str:
    """Content-derived, direction- and re-chunking-invariant wall candidate id.

    Hashes the chain's two boundary endpoints (canonically ordered, as
    before) PLUS a direction-canonical shape fingerprint of the path between
    them (see ``_shape_fingerprint``) -- so two chains sharing both endpoints
    but following genuinely different interior paths (the real, confirmed
    Baghau collision this fixes) receive DIFFERENT ids, while the same
    physical wall re-chunked into a different number of collinear fragments
    still receives the IDENTICAL id (the same physical wall's own shape,
    resampled at the same fixed arc-length fractions, does not change merely
    because it has more or fewer defining vertices).

    Both the endpoint pair and the fingerprint are computed in whichever of
    the two traversal directions sorts first (matching the endpoint-only
    ordering this function already used), so reversing the input polyline's
    own direction does not change the id.
    """
    forward_key = tuple(round(c, 6) for c in points[0])
    backward_key = tuple(round(c, 6) for c in points[-1])
    if backward_key < forward_key:
        points = tuple(reversed(points))
    p1 = tuple(round(c, 6) for c in points[0])
    p2 = tuple(round(c, 6) for c in points[-1])
    fingerprint = _shape_fingerprint(points)
    return stable_contract_id(
        "wall", {"viewport_id": viewport_id, "p1": p1, "p2": p2, "shape": fingerprint}
    )


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

    return wall_candidates, edge_id_to_wall_candidate_id


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
