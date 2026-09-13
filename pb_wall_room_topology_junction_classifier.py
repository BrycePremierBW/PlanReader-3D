"""W3: junction classification over W2's segment graph.

Converts the cleaned/split wall-segment graph produced by
``pb_wall_room_topology_stage_a.build_wall_graph_for_viewport`` into explicit
``JunctionCandidate`` records (``pb_wall_room_topology_contracts``) and
deterministic ``TopologyRelationship`` records between the graph's edges.

Does NOT:
- wire into any live extraction path (``pb_planreader_pdf_extractor.py`` is
  untouched, and nothing here is imported by it);
- calculate any wall/room quantity;
- emit any ``QuantityEvidence``;
- introduce a second graph, authority, or status system -- every status value
  used here is ``pb_migration_contracts.EvidenceResolutionStatus``, every
  measurement-authority concept (there are none needed at this stage -- no
  metre-space value is computed here) would use
  ``pb_geometry_takeoff_model.MeasurementAuthorityType`` if it ever needed
  one, and every id is generated with ``pb_migration_contracts.
  stable_contract_id`` for consistency with the rest of the migration.

A geometric crossing is never automatically treated as a structural wall
junction. Three independent mechanisms enforce this, corresponding to the
three ways a false crossing can reach this stage:

1. A segment already excluded by W2's Stage A pre-filter (dashed/hatch/
   dimension/annotation-layer convention) never entered the graph at all --
   nothing to do here, but ``find_rejected_non_wall_crossings`` still records
   an explicit, auditable ``REJECTED_NON_WALL_CROSSING`` candidate wherever
   such an excluded segment geometrically crosses a real structural edge, so
   the rejection is visible rather than a silent absence.
2. Two distinct (unmerged) nodes sitting suspiciously close together (closer
   than a review band above the snap tolerance, but not close enough for W2's
   own endpoint-snap to have merged them) are flagged ``NEAR_JUNCTION_REVIEW``
   rather than silently left as two disconnected walls or silently merged.
3. A node whose incident-edge pattern would otherwise classify cleanly (an
   L/T/X/MULTI_WAY shape) but which carries a short, dead-end arm relative to
   its other incident edges -- the geometric signature shared by a genuine
   short wall return AND by furniture/decorative marks/text-box borders
   merely touching a wall -- is demoted to ``AMBIGUOUS`` rather than guessed
   either way. This is an honest limitation, not a solved problem: pure
   geometry cannot always distinguish these two cases; richer, later
   evidence (dimension/schedule corroboration, W9-11) is what should resolve
   it, not a confident guess made here.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_wall_room_topology_contracts import (
    JunctionCandidate,
    JunctionType,
    TopologyRelationship,
    TopologyRelationshipType,
)

# Reused for consistency with W2's own collinear-merge tolerance -- a node
# that reaches this classifier at degree 2 with a collinear angle pattern
# should be recognized the same way W2 would have merged it away, not
# reclassified under a different tolerance.
DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG = 3.0

# Two distinct nodes closer than this multiple of the Stage-A snap tolerance
# (but farther apart than the snap tolerance itself -- otherwise W2 would
# already have merged them into one node) are flagged for review rather than
# silently treated as two unrelated, disconnected wall ends.
DEFAULT_NEAR_MISS_REVIEW_MULTIPLIER = 3.0

# An unpaired ("single") incident arm shorter than this fraction of the
# longest incident edge at the same node, whose far endpoint is itself a bare
# degree-1 dead end, is treated as a suspicious short/isolated arm (spec
# false-positive protection: furniture, decorative marks, and a genuine short
# wall return are geometrically indistinguishable from each other by this
# signal alone -- see module docstring point 3). Expressed as a relative
# fraction, not an absolute length, so it is scale-independent: it does not
# require page scale to have resolved, and is not tuned to any one project's
# drawing units.
DEFAULT_SHORT_ARM_RELATIVE_THRESHOLD = 0.15

_CONFIDENCE_BY_TYPE: Dict[JunctionType, float] = {
    JunctionType.ENDPOINT: 0.95,
    JunctionType.COLLINEAR_CONTINUATION: 0.9,
    JunctionType.L_CORNER: 0.9,
    JunctionType.T_JUNCTION: 0.85,
    JunctionType.X_CROSSING: 0.85,
    JunctionType.MULTI_WAY: 0.75,
    JunctionType.AMBIGUOUS: 0.4,
    JunctionType.NEAR_JUNCTION_REVIEW: 0.3,
    JunctionType.UNRESOLVED: 0.0,
    JunctionType.REJECTED_NON_WALL_CROSSING: 0.0,
}

# Types the classifier itself commits to (single clean geometric source) vs.
# types where it explicitly abstains rather than committing -- see module
# docstring for the CANDIDATE/ABSTAINED split rationale.
_ABSTAINED_TYPES = frozenset(
    {
        JunctionType.AMBIGUOUS,
        JunctionType.NEAR_JUNCTION_REVIEW,
        JunctionType.UNRESOLVED,
        JunctionType.REJECTED_NON_WALL_CROSSING,
    }
)


def _angle_delta(a_deg: float, b_deg: float) -> float:
    d = abs(a_deg - b_deg) % 180.0
    return min(d, 180.0 - d)


def _status_for(junction_type: JunctionType) -> EvidenceResolutionStatus:
    if junction_type in _ABSTAINED_TYPES:
        return EvidenceResolutionStatus.ABSTAINED
    return EvidenceResolutionStatus.CANDIDATE


def deduplicate_coincident_edges(graph: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Collapse two-or-more edges that connect the exact same node pair.

    A duplicate is a drafting redundancy (a traced-over or copy-pasted line
    lying directly on top of a real wall) -- in a planar wall graph, two
    genuinely different physical walls never share both endpoints, since a
    double-line wall's two faces are offset by its thickness and therefore
    never map to the same node pair after snapping. Returns
    ``(deduplicated_graph, duplicate_edge_ids_removed)``.
    """
    edges = graph["edges"]
    seen: Dict[frozenset, Dict[str, Any]] = {}
    kept: List[Dict[str, Any]] = []
    removed_ids: List[str] = []
    for edge in edges:
        key = frozenset((edge["a"], edge["b"]))
        if key in seen:
            removed_ids.append(str(edge.get("id")))
            continue
        seen[key] = edge
        kept.append(edge)

    nodes = [dict(n) for n in graph["nodes"]]
    adjacency: Dict[int, List[int]] = {n["id"]: [] for n in nodes}
    for edge_index, edge in enumerate(kept):
        adjacency[edge["a"]].append(edge_index)
        adjacency[edge["b"]].append(edge_index)
    for node in nodes:
        if not node.get("merged_into_edge"):
            node["degree"] = len(adjacency[node["id"]])

    deduped_graph = {**graph, "nodes": nodes, "edges": kept, "adjacency": adjacency}
    return deduped_graph, removed_ids


def _incident_edge_infos(
    node_idx: int, edges: Sequence[Dict[str, Any]], adjacency: Dict[int, List[int]]
) -> List[Dict[str, Any]]:
    infos = []
    for edge_index in adjacency.get(node_idx, []):
        edge = edges[edge_index]
        far_node = edge["b"] if edge["a"] == node_idx else edge["a"]
        infos.append(
            {
                "edge_index": edge_index,
                "edge_id": str(edge.get("id")),
                "angle_deg": edge["angle_deg"],
                "length_pt": edge["length_pt"],
                "far_node": far_node,
            }
        )
    return infos


def _group_by_angle(
    infos: Sequence[Dict[str, Any]], angle_tolerance_deg: float
) -> List[List[Dict[str, Any]]]:
    groups: List[List[Dict[str, Any]]] = []
    used = [False] * len(infos)
    for i, info in enumerate(infos):
        if used[i]:
            continue
        group = [info]
        used[i] = True
        for j in range(i + 1, len(infos)):
            if used[j]:
                continue
            if _angle_delta(info["angle_deg"], infos[j]["angle_deg"]) <= angle_tolerance_deg:
                group.append(infos[j])
                used[j] = True
        groups.append(group)
    return groups


def _base_classification(
    groups: List[List[Dict[str, Any]]]
) -> Tuple[JunctionType, List[str]]:
    """Return (junction_type, reason_codes) from a node's angle-groups alone.

    Does not yet apply the short-isolated-arm demotion -- see
    ``_apply_short_arm_demotion``, applied by the caller afterward.
    """
    degenerate_groups = [g for g in groups if len(g) > 2]
    if degenerate_groups:
        return JunctionType.AMBIGUOUS, ["degenerate_angle_group_size_over_two"]

    pairs = [g for g in groups if len(g) == 2]
    singles = [g for g in groups if len(g) == 1]
    degree = sum(len(g) for g in groups)
    n_pairs, n_singles = len(pairs), len(singles)

    if degree == 0:
        return JunctionType.UNRESOLVED, ["no_incident_edges"]
    if degree == 1:
        return JunctionType.ENDPOINT, []
    if degree == 2 and n_pairs == 1:
        return JunctionType.COLLINEAR_CONTINUATION, []
    if degree == 2 and n_singles == 2:
        return JunctionType.L_CORNER, []
    if degree == 3 and n_pairs == 1 and n_singles == 1:
        return JunctionType.T_JUNCTION, []
    if degree == 3 and n_singles == 3:
        return JunctionType.UNRESOLVED, ["three_way_non_collinear_star"]
    if degree == 4 and n_pairs == 2:
        return JunctionType.X_CROSSING, []
    if degree == 4 and n_pairs == 1 and n_singles == 2:
        return JunctionType.AMBIGUOUS, ["through_pair_with_extra_branches"]
    if degree == 4 and n_singles == 4:
        return JunctionType.UNRESOLVED, ["four_way_non_collinear_star"]
    if degree >= 5:
        if n_singles == 0:
            return JunctionType.MULTI_WAY, []
        if n_pairs > 0:
            return JunctionType.AMBIGUOUS, ["partial_multi_way_pairing"]
        return JunctionType.UNRESOLVED, ["irregular_multi_way_meeting"]

    return JunctionType.UNRESOLVED, ["unclassified_incident_pattern"]


def _apply_short_arm_demotion(
    junction_type: JunctionType,
    reason_codes: List[str],
    groups: List[List[Dict[str, Any]]],
    node_degrees: Dict[int, int],
    threshold: float,
) -> Tuple[JunctionType, List[str]]:
    if junction_type in (JunctionType.ENDPOINT, JunctionType.UNRESOLVED, JunctionType.AMBIGUOUS):
        return junction_type, reason_codes

    all_infos = [info for group in groups for info in group]
    if not all_infos:
        return junction_type, reason_codes
    max_length = max(info["length_pt"] for info in all_infos)
    if max_length <= 0:
        return junction_type, reason_codes

    singles = [g[0] for g in groups if len(g) == 1]
    for info in singles:
        far_degree = node_degrees.get(info["far_node"], 0)
        if info["length_pt"] < threshold * max_length and far_degree <= 1:
            return JunctionType.AMBIGUOUS, [
                *reason_codes,
                "short_isolated_arm_present",
                f"suspect_edge_id:{info['edge_id']}",
            ]
    return junction_type, reason_codes


def classify_junctions(
    graph: Dict[str, Any],
    *,
    document_id: str,
    page_id: str,
    viewport_id: str,
    angle_tolerance_deg: float = DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG,
    short_arm_relative_threshold: float = DEFAULT_SHORT_ARM_RELATIVE_THRESHOLD,
    snap_tolerance_pt: float = 2.5,
    near_miss_review_multiplier: float = DEFAULT_NEAR_MISS_REVIEW_MULTIPLIER,
) -> Tuple[List[JunctionCandidate], List[TopologyRelationship]]:
    """Classify every node in a Stage-A graph and derive edge relationships.

    ``graph`` is expected to be the output of
    ``pb_wall_room_topology_stage_a.build_wall_graph_for_viewport`` (optionally
    already passed through ``deduplicate_coincident_edges`` -- this function
    also applies that pass itself, so callers do not need to remember to).
    """
    graph, _duplicate_edge_ids = deduplicate_coincident_edges(graph)
    nodes = graph["nodes"]
    edges = graph["edges"]
    adjacency = graph["adjacency"]

    node_degrees = {n["id"]: n.get("degree", 0) for n in nodes}

    base_results: Dict[int, Tuple[JunctionType, List[str], List[Dict[str, Any]]]] = {}
    for node in nodes:
        node_idx = node["id"]
        if node.get("merged_into_edge"):
            merged_edge = next(
                (e for e in edges if e.get("id") == node["merged_into_edge"]), None
            )
            if merged_edge is None:
                # Fail closed: this node's Stage-A collinear merge produced
                # a new edge that deduplicate_coincident_edges (called
                # above, in this same function) then discarded as a
                # duplicate of another edge sharing the same node pair --
                # found running this pipeline against real Baghau drawing
                # data, where a wall drawn as two collinear fragments plus a
                # separate, undivided line spanning the same two far
                # endpoints hits exactly this case. The edge that survives
                # dedup in that situation shares the merged edge's node
                # pair but is not guaranteed to actually pass through this
                # node's own location, so this node abstains rather than
                # emit a COLLINEAR_CONTINUATION referencing an edge that may
                # not spatially touch it.
                base_results[node_idx] = (
                    JunctionType.UNRESOLVED,
                    ["collinear_merge_target_edge_missing"],
                    [],
                )
                continue
            base_results[node_idx] = (
                JunctionType.COLLINEAR_CONTINUATION,
                ["collinear_merge_applied"],
                [{"edge_id": str(merged_edge.get("id")), "angle_deg": merged_edge["angle_deg"]}],
            )
            continue
        infos = _incident_edge_infos(node_idx, edges, adjacency)
        groups = _group_by_angle(infos, angle_tolerance_deg)
        jtype, reasons = _base_classification(groups)
        jtype, reasons = _apply_short_arm_demotion(
            jtype, reasons, groups, node_degrees, short_arm_relative_threshold
        )
        base_results[node_idx] = (jtype, reasons, infos)

    near_miss_pairs = detect_near_miss_node_pairs(
        graph, snap_tolerance_pt=snap_tolerance_pt, review_multiplier=near_miss_review_multiplier
    )
    near_miss_partner: Dict[int, Tuple[int, float]] = {}
    for a_idx, b_idx, distance in near_miss_pairs:
        near_miss_partner[a_idx] = (b_idx, distance)
        near_miss_partner[b_idx] = (a_idx, distance)

    junctions: List[JunctionCandidate] = []
    junctions_by_node_idx: Dict[int, JunctionCandidate] = {}
    for node in nodes:
        node_idx = node["id"]
        jtype, reasons, infos = base_results[node_idx]
        incident_ids = tuple(info["edge_id"] for info in infos if info.get("edge_id"))
        incident_angles = tuple(info["angle_deg"] for info in infos)

        if node_idx in near_miss_partner:
            partner_idx, distance = near_miss_partner[node_idx]
            reasons = [
                *reasons,
                f"base_classification_would_have_been:{jtype.value}",
                f"near_miss_partner_node_id:{partner_idx}",
                f"near_miss_distance_pt:{distance:.4f}",
            ]
            jtype = JunctionType.NEAR_JUNCTION_REVIEW

        position = (node["x"], node["y"])
        node_id = stable_contract_id(
            "junc",
            {
                "page_id": page_id,
                "viewport_id": viewport_id,
                "node_idx": node_idx,
                "x": round(position[0], 6),
                "y": round(position[1], 6),
            },
        )
        candidate = JunctionCandidate(
            node_id=node_id,
            document_id=document_id,
            page_id=page_id,
            viewport_id=viewport_id,
            position_pt=position,
            junction_type=jtype,
            incident_wall_candidate_ids=incident_ids,
            incident_angles_deg=incident_angles,
            status=_status_for(jtype),
            confidence=_CONFIDENCE_BY_TYPE[jtype],
            reason_codes=tuple(reasons),
        )
        junctions.append(candidate)
        junctions_by_node_idx[node_idx] = candidate

    relationships = derive_topology_relationships(graph, junctions_by_node_idx)
    return junctions, relationships


def detect_near_miss_node_pairs(
    graph: Dict[str, Any],
    *,
    snap_tolerance_pt: float,
    review_multiplier: float = DEFAULT_NEAR_MISS_REVIEW_MULTIPLIER,
) -> List[Tuple[int, int, float]]:
    """Return (node_a_id, node_b_id, distance_pt) for every close-but-distinct
    pair of dangling (degree-1) wall ends.

    Only compares degree-1 "loose end" nodes against each other -- a node
    already joined to the graph (degree >= 2, i.e. already part of some
    junction) is not a near-miss candidate merely because another node
    happens to sit within the review band of it; it is already properly
    connected to whatever it is connected to. Restricting to degree-1 pairs
    is also what keeps this check from ever firing on a T/L/X junction's own
    internal node spacing at small drawing scale (those nodes are degree
    >= 2 by construction).

    A pair within ``snap_tolerance_pt`` would already have been merged into
    one node by Stage A's own endpoint snapping -- if such a pair somehow
    still exists here, it is treated as coincidental (e.g. exactly at the
    tolerance boundary due to floating point) and is not flagged again. Only
    genuinely distinct nodes within the review band
    (``snap_tolerance_pt``, ``snap_tolerance_pt * review_multiplier``] are
    reported.
    """
    nodes = [
        n for n in graph["nodes"] if not n.get("merged_into_edge") and n.get("degree") == 1
    ]
    review_band = snap_tolerance_pt * review_multiplier
    pairs: List[Tuple[int, int, float]] = []
    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            distance = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
            if snap_tolerance_pt < distance <= review_band:
                pairs.append((a["id"], b["id"], distance))
    return pairs


def _segment_intersection(
    p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float], p4: Tuple[float, float]
) -> Optional[Tuple[float, float]]:
    """Standard bounded line-segment intersection; None if they do not cross."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def find_rejected_non_wall_crossings(
    graph: Dict[str, Any],
    excluded_segments: Sequence[Dict[str, Any]],
    *,
    document_id: str,
    page_id: str,
    viewport_id: str,
) -> List[JunctionCandidate]:
    """Record an explicit, auditable rejection wherever an excluded segment
    would otherwise have crossed a real structural edge.

    This is the direct implementation of "a geometric crossing is not
    automatically a structural wall junction": rather than an excluded
    segment (hatch, dimension line, annotation) simply vanishing with no
    trace, this makes the rejection visible at exactly the point it would
    have mattered.
    """
    edges = graph["edges"]
    rejected: List[JunctionCandidate] = []
    for excluded in excluded_segments:
        p1 = (float(excluded["x1"]), float(excluded["y1"]))
        p2 = (float(excluded["x2"]), float(excluded["y2"]))
        exclusion_reasons = list(excluded.get("reason_codes") or [])
        for edge in edges:
            if edge.get("_removed"):
                continue
            e1 = (edge["x1"], edge["y1"])
            e2 = (edge["x2"], edge["y2"])
            point = _segment_intersection(p1, p2, e1, e2)
            if point is None:
                continue
            node_id = stable_contract_id(
                "junc_rejected",
                {
                    "page_id": page_id,
                    "viewport_id": viewport_id,
                    "x": round(point[0], 6),
                    "y": round(point[1], 6),
                    "excluded_segment_id": str(excluded.get("id")),
                },
            )
            rejected.append(
                JunctionCandidate(
                    node_id=node_id,
                    document_id=document_id,
                    page_id=page_id,
                    viewport_id=viewport_id,
                    position_pt=point,
                    junction_type=JunctionType.REJECTED_NON_WALL_CROSSING,
                    incident_wall_candidate_ids=(str(edge.get("id")),),
                    incident_angles_deg=(edge["angle_deg"],),
                    status=EvidenceResolutionStatus.ABSTAINED,
                    confidence=0.0,
                    reason_codes=tuple(
                        [*exclusion_reasons, f"crossed_structural_edge:{edge.get('id')}"]
                    ),
                )
            )
    return rejected


def derive_topology_relationships(
    graph: Dict[str, Any], junctions_by_node_idx: Dict[int, JunctionCandidate]
) -> List[TopologyRelationship]:
    """Derive CONNECTED_TO/CONTINUES_AS/TERMINATES_AT/INTERSECTS/BRANCHES_FROM
    relationships between edges, one junction's incident edges at a time.

    ``junctions_by_node_idx`` maps a Stage-A graph node index to the
    ``JunctionCandidate`` already classified for it (as produced by
    ``classify_junctions``) -- keyed by node index rather than position, since
    two distinct nodes could in principle share a position in degenerate
    input and a position-keyed lookup would then silently collide.
    """
    edges = graph["edges"]
    adjacency = graph["adjacency"]
    relationships: List[TopologyRelationship] = []

    for node in graph["nodes"]:
        node_idx = node["id"]
        junction = junctions_by_node_idx.get(node_idx)
        if junction is None:
            continue
        infos = _incident_edge_infos(node_idx, edges, adjacency)
        if not infos:
            continue

        if junction.junction_type == JunctionType.ENDPOINT and len(infos) == 1:
            relationships.append(
                TopologyRelationship(
                    relationship_id=stable_contract_id(
                        "topo", {"junction": junction.node_id, "edge": infos[0]["edge_id"], "rel": "terminates_at"}
                    ),
                    from_edge_id=infos[0]["edge_id"],
                    to_edge_id=None,
                    relationship_type=TopologyRelationshipType.TERMINATES_AT,
                    via_junction_id=junction.node_id,
                    confidence=junction.confidence,
                )
            )
            continue

        groups = _group_by_angle(infos, DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG)
        pairs = [g for g in groups if len(g) == 2]
        singles = [g[0] for g in groups if len(g) == 1]

        for pair in pairs:
            a, b = pair[0], pair[1]
            rel_type = (
                TopologyRelationshipType.CONTINUES_AS
                if junction.junction_type == JunctionType.COLLINEAR_CONTINUATION
                else TopologyRelationshipType.CONTINUES_AS
            )
            relationships.append(
                TopologyRelationship(
                    relationship_id=stable_contract_id(
                        "topo", {"junction": junction.node_id, "a": a["edge_id"], "b": b["edge_id"], "rel": "continues_as"}
                    ),
                    from_edge_id=a["edge_id"],
                    to_edge_id=b["edge_id"],
                    relationship_type=rel_type,
                    via_junction_id=junction.node_id,
                    confidence=junction.confidence,
                )
            )

        if junction.junction_type == JunctionType.T_JUNCTION and pairs and singles:
            bar_edge_ids = {info["edge_id"] for info in pairs[0]}
            for stem in singles:
                for bar_edge_id in bar_edge_ids:
                    relationships.append(
                        TopologyRelationship(
                            relationship_id=stable_contract_id(
                                "topo",
                                {
                                    "junction": junction.node_id,
                                    "stem": stem["edge_id"],
                                    "bar": bar_edge_id,
                                    "rel": "branches_from",
                                },
                            ),
                            from_edge_id=stem["edge_id"],
                            to_edge_id=bar_edge_id,
                            relationship_type=TopologyRelationshipType.BRANCHES_FROM,
                            via_junction_id=junction.node_id,
                            confidence=junction.confidence,
                        )
                    )
        elif junction.junction_type in (JunctionType.X_CROSSING, JunctionType.MULTI_WAY) and len(pairs) >= 2:
            for i, pair_a in enumerate(pairs):
                for pair_b in pairs[i + 1 :]:
                    for edge_a in pair_a:
                        for edge_b in pair_b:
                            relationships.append(
                                TopologyRelationship(
                                    relationship_id=stable_contract_id(
                                        "topo",
                                        {
                                            "junction": junction.node_id,
                                            "a": edge_a["edge_id"],
                                            "b": edge_b["edge_id"],
                                            "rel": "intersects",
                                        },
                                    ),
                                    from_edge_id=edge_a["edge_id"],
                                    to_edge_id=edge_b["edge_id"],
                                    relationship_type=TopologyRelationshipType.INTERSECTS,
                                    via_junction_id=junction.node_id,
                                    confidence=junction.confidence,
                                )
                            )
        elif junction.junction_type == JunctionType.L_CORNER and len(singles) == 2:
            a, b = singles[0], singles[1]
            relationships.append(
                TopologyRelationship(
                    relationship_id=stable_contract_id(
                        "topo", {"junction": junction.node_id, "a": a["edge_id"], "b": b["edge_id"], "rel": "connected_to"}
                    ),
                    from_edge_id=a["edge_id"],
                    to_edge_id=b["edge_id"],
                    relationship_type=TopologyRelationshipType.CONNECTED_TO,
                    via_junction_id=junction.node_id,
                    confidence=junction.confidence,
                )
            )

    return relationships
