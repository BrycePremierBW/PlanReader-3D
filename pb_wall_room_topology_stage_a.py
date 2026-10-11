"""Stage A segment preparation for wall/room topology reconstruction (W2).

Implements ``docs/planreader_wall_room_topology_spec.md`` Section 4's Stage A
and the specific extensions called for in Sections 6.5 and 6.11:

    A1. split_segments_at_intersections   (pb_accuracy_v13_engines_v145, reused
                                            unmodified)
    A2. snap_geometry                     (pb_vector_geometry_v130, reused
                                            unmodified)
    + a hatch/dimension-line pre-filter (Section 6.11) applied BEFORE splitting,
      while the original segment dicts still carry their stroke/dash/layer
      metadata. Intersection splitting still uses the unmodified tuple-pair
      engine; additive ``primitive_lineage`` is reattached afterwards so live
      post-split fields stay the historical sentinels. The pre-filter must
      therefore still run on the original dicts, not after the rebuild.
    + a collinear degree-two merge pass (Section 6.5) applied AFTER snapping,
      to collapse a spurious mid-run junction left by a redundant shared
      vertex (e.g. a CAD export that splits one straight wall into two
      collinear segments at an arbitrary point). This is distinct from -- and
      does not replace -- ``snap_geometry``'s own endpoint-tolerance merging,
      which already closes small real gaps between fragments that do not
      share an endpoint at all (see the module-level note on tolerance_pt
      below).

Deliberately does NOT reuse ``pb_vector_geometry_v130.py`` by editing it in
place: that module is live in a separate, unrelated app entry point
(``pb_planreader_v126_app.py``) that this workstream does not own or want to
risk destabilizing. Its two functions are imported and called unmodified;
everything new lives here.

No PDF is opened by this module. No wall/room candidate, junction
classification, or canonical entity is produced here -- this is purely the
segment-graph preparation stage that later stages (W3 junction
classification, W4 wall-candidate assembly, W5 room-candidate assembly)
consume.
"""
from __future__ import annotations

import heapq
import math
import os
import re
from typing import Any, Dict, List, Sequence, Tuple

from pb_accuracy_v13_engines_v145 import split_segments_at_intersections
from pb_vector_geometry_v130 import snap_geometry
from pb_wall_room_topology_short_fragment_audit import audit_short_source_fragments
from pb_wall_room_topology_primitive_lineage import (
    LINEAGE_KEY,
    attach_lineage_to_split_fragments,
    collinear_merge_leaf_edge_ids,
    empty_lineage,
    fabricated_live_fields,
    isolate_graph_lineage,
    isolated_lineage,
    lineage_from_edges,
    observe_snap_collapsed_fragments,
)

# A gap this small between two collinear fragment endpoints is treated as a
# drafting artifact (rounding, a CAD export's own tolerance) rather than a
# real physical gap. This is passed to snap_geometry as its endpoint-snap
# tolerance -- it is NOT the same thing as the collinear degree-two merge
# pass below, which handles fragments that already share one exact node.
# 2.5pt mirrors the angle-tolerance magnitude already used elsewhere in this
# codebase for "reasonable drafting tolerance" (pb_vector_geometry_v130's own
# 2.5-degree parallel-line check) -- picked for consistency, not derived from
# any project-specific measurement.
DEFAULT_GAP_SNAP_TOLERANCE_PT = 2.5

# A degree-two node whose two incident edges' angles differ by less than this
# is "collinear enough" to merge -- see merge_collinear_degree_two_nodes.
DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG = 3.0

# Segments shorter than this are exempt from hatch-density suspicion by
# construction: this workstream does not attempt density-based hatch
# detection at all (see module docstring and the topology spec Section 6.11)
# specifically because a genuine short wall return (spec Section 6.8) is also
# a short segment, and the two must not be confused. Only deterministic
# metadata (dash pattern, layer name) is used to reject a segment here.
_HATCH_LAYER_KEYWORDS = ("hatch", "pattern", "fill", "shading")
_DIMENSION_LAYER_KEYWORDS = ("dim", "dimension", "annotation", "note")
# Added for W3's false-positive protection: a text box, callout, or leader
# line frame is not wall linework even when solid/undashed. Matched the same
# way as the hatch/dimension keywords above -- by layer name only, never by
# length or position -- and only catches a text-box border when the source
# PDF actually tags it with an identifiable layer name. A text/annotation
# frame with no identifying layer metadata at all is a known, honest gap left
# to later corroboration stages (see docs/planreader_wall_room_topology_spec.md
# Section 12/W9-11) -- not silently claimed as solved here.
_TEXT_FRAME_LAYER_KEYWORDS = ("text", "frame", "border", "leader", "callout", "label")
# Positive source metadata for an explicitly structural grid family. A bare
# "GRID" name is deliberately insufficient: only a layer that states both the
# structural domain and a grid role is excluded here.
_STRUCTURAL_GRID_LAYER_ROLES = {"grid", "grids", "gridline", "gridlines"}
_EXPLICIT_NON_WALL_LAYER_TOKEN_SETS = (
    frozenset({"marker", "section"}),
    frozenset({"shell", "roof"}),
)


def _angle_delta(a_deg: float, b_deg: float) -> float:
    d = abs(a_deg - b_deg) % 180.0
    return min(d, 180.0 - d)


def is_structural_candidate_segment(segment: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (keep, reason_codes) for a single raw segment dict (Section 6.11).

    Conservative by design: only excludes a segment when its own captured
    metadata (dashes, layer) matches a known non-structural drafting
    convention. Never excludes on length or position alone -- that risks
    discarding a genuine short wall return (Section 6.8), which this function
    must never do.
    """
    reason_codes: List[str] = []
    dashes = str(segment.get("dashes") or "").strip()
    # PyMuPDF's "dashes" field for a solid line is typically "[] 0" or empty;
    # any other non-trivial pattern indicates a dashed convention (hidden
    # line, centerline, dimension extension line) rather than solid wall
    # linework.
    if dashes and dashes not in ("", "[] 0", "[]"):
        reason_codes.append("dashed_line_excluded")

    layer = str(segment.get("layer") or "").strip().lower()
    if layer:
        if any(keyword in layer for keyword in _HATCH_LAYER_KEYWORDS):
            reason_codes.append("hatch_layer_excluded")
        if any(keyword in layer for keyword in _DIMENSION_LAYER_KEYWORDS):
            reason_codes.append("dimension_layer_excluded")
        if any(keyword in layer for keyword in _TEXT_FRAME_LAYER_KEYWORDS):
            reason_codes.append("text_frame_layer_excluded")
        layer_tokens = {
            token for token in re.findall(r"[a-z0-9]+", layer) if token
        }
        if (
            "structural" in layer_tokens
            and layer_tokens & _STRUCTURAL_GRID_LAYER_ROLES
        ):
            reason_codes.append("structural_grid_source_layer_excluded")
        if any(
            required_tokens <= layer_tokens
            for required_tokens in _EXPLICIT_NON_WALL_LAYER_TOKEN_SETS
        ):
            reason_codes.append("explicit_non_wall_source_layer_excluded")

    return (len(reason_codes) == 0, reason_codes)


def filter_structural_segments(
    segments: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split raw segments into (structural_candidates, excluded_with_reasons).

    ``excluded_with_reasons`` entries are the original segment dict plus a
    ``"reason_codes"`` key, kept for observability rather than silently
    dropped from the return value entirely.
    """
    kept: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for segment in segments:
        keep, reason_codes = is_structural_candidate_segment(segment)
        if keep:
            kept.append(segment)
        else:
            excluded.append({**segment, "reason_codes": reason_codes})
    return kept, excluded


def _segments_to_point_pairs(
    segments: Sequence[Dict[str, Any]],
) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
    pairs = []
    for seg in segments:
        pairs.append(
            ((float(seg["x1"]), float(seg["y1"])), (float(seg["x2"]), float(seg["y2"])))
        )
    return pairs


def _point_pairs_to_segment_dicts(
    pairs: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],
    *,
    id_prefix: str = "split",
    source_segments: Sequence[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Rebuild historical split dicts, plus additive plural lineage when sources exist.

    Live ``width`` / ``stroke`` / ``fill`` / ``layer`` / ``dashes`` remain the
    fabricated sentinels so existing consumers do not start treating unknown
    graphic state as supplied. Source evidence is in ``primitive_lineage``.
    """
    if source_segments is None:
        live = fabricated_live_fields()
        return [
            {
                "id": f"{id_prefix}_{idx}",
                "x1": p1[0],
                "y1": p1[1],
                "x2": p2[0],
                "y2": p2[1],
                **live,
                LINEAGE_KEY: empty_lineage(),
            }
            for idx, (p1, p2) in enumerate(pairs)
        ]
    return attach_lineage_to_split_fragments(pairs, source_segments, id_prefix=id_prefix)


def _snap_geometry_indexed(
    segments: Sequence[Dict[str, Any]],
    tolerance_pt: float = DEFAULT_GAP_SNAP_TOLERANCE_PT,
    *,
    include_endpoint_assignments: bool = False,
) -> Dict[str, Any]:
    """Exact Stage-A equivalent of snap_geometry with a local endpoint index.

    Candidate membership is unchanged: a node is eligible iff its current
    centroid is within tolerance_pt. The same lowest-distance / lowest-existing
    node index wins because candidates are visited in ascending node id and the
    historical strict distance comparison is retained. Node centroids still
    move by the same running mean after every accepted endpoint.
    """
    if tolerance_pt <= 0:
        return snap_geometry(segments, tolerance_pt=tolerance_pt)

    nodes: List[Dict[str, Any]] = []
    endpoint_assignments: Dict[str, Tuple[int, int]] = {}
    cell_size = float(tolerance_pt)
    grid: Dict[Tuple[int, int], set[int]] = {}

    def cell_for(x: float, y: float) -> Tuple[int, int]:
        return (
            math.floor(float(x) / cell_size),
            math.floor(float(y) / cell_size),
        )

    def add_to_grid(node_idx: int) -> None:
        node = nodes[node_idx]
        grid.setdefault(cell_for(node["x"], node["y"]), set()).add(node_idx)

    def move_in_grid(node_idx: int, old_cell: Tuple[int, int]) -> None:
        new_cell = cell_for(nodes[node_idx]["x"], nodes[node_idx]["y"])
        if new_cell == old_cell:
            return
        members = grid.get(old_cell)
        if members is not None:
            members.discard(node_idx)
            if not members:
                grid.pop(old_cell, None)
        grid.setdefault(new_cell, set()).add(node_idx)

    def locate(pt: Tuple[float, float]) -> int:
        cx, cy = cell_for(pt[0], pt[1])
        candidate_indexes: set[int] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidate_indexes.update(grid.get((cx + dx, cy + dy), ()))

        best = -1
        best_d = tolerance_pt + 1.0
        for idx in sorted(candidate_indexes):
            node = nodes[idx]
            d = math.hypot(node["x"] - pt[0], node["y"] - pt[1])
            if d <= tolerance_pt and d < best_d:
                best, best_d = idx, d

        if best >= 0:
            node = nodes[best]
            old_cell = cell_for(node["x"], node["y"])
            count = node["samples"] + 1
            node["x"] = (node["x"] * node["samples"] + pt[0]) / count
            node["y"] = (node["y"] * node["samples"] + pt[1]) / count
            node["samples"] = count
            move_in_grid(best, old_cell)
            return best

        nodes.append(
            {"id": len(nodes), "x": pt[0], "y": pt[1], "samples": 1}
        )
        add_to_grid(len(nodes) - 1)
        return len(nodes) - 1

    edges = []
    for seg in segments:
        a = locate((float(seg["x1"]), float(seg["y1"])))
        b = locate((float(seg["x2"]), float(seg["y2"])))
        if include_endpoint_assignments:
            segment_id = seg.get("id")
            if (not isinstance(segment_id, str) or not segment_id
                    or segment_id in endpoint_assignments):
                raise ValueError("missing or duplicate split id in W2 endpoint trace")
            endpoint_assignments[segment_id] = (a, b)
        if a == b:
            continue
        edge = dict(seg)
        edge.update({"a": a, "b": b})
        edge["length_pt"] = math.hypot(
            float(seg["x2"]) - float(seg["x1"]),
            float(seg["y2"]) - float(seg["y1"]),
        )
        edge["angle_deg"] = math.degrees(
            math.atan2(
                float(seg["y2"]) - float(seg["y1"]),
                float(seg["x2"]) - float(seg["x1"]),
            )
        ) % 180.0
        edges.append(edge)

    adjacency: Dict[int, List[int]] = {idx: [] for idx in range(len(nodes))}
    for edge_index, edge in enumerate(edges):
        adjacency[edge["a"]].append(edge_index)
        adjacency[edge["b"]].append(edge_index)
    for node in nodes:
        node["degree"] = len(adjacency[node["id"]])
    result = {"nodes": nodes, "edges": edges, "adjacency": adjacency}
    if include_endpoint_assignments:
        result["endpoint_snap_assignments"] = endpoint_assignments
    return result


def merge_collinear_degree_two_nodes(
    graph: Dict[str, Any],
    angle_tolerance_deg: float = DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG,
) -> Dict[str, Any]:
    """Collapse a degree-two node whose two incident edges are collinear.

    Fixes the case (topology spec Section 6.5 / test T9) where a single
    straight wall was drawn -- or exported -- as two segments sharing one
    exact endpoint with nothing else connecting there: after
    ``snap_geometry``, that shared endpoint is a real graph node with
    degree 2, which is not a genuine junction (Section 7's junction
    classifier would otherwise have to special-case it as a spurious
    L_CORNER). This pass removes it and produces one logical edge spanning
    both original segments' far endpoints instead.

    Does not merge a degree-two node whose two incident edges are NOT
    collinear (a real corner) -- that is a genuine L_CORNER, left untouched
    for Section 7's junction classifier.

    Operates on ``snap_geometry``'s own output shape unchanged: returns a new
    graph dict with the same ``{"nodes", "edges", "adjacency"}`` keys. Nodes
    that were merged away are retained in ``nodes`` (so any external
    ``node_id`` reference already collected elsewhere stays resolvable) but
    have their ``degree`` set to ``0`` and gain a ``"merged_into_edge"`` key
    naming the id of the edge that replaced their two incident edges.
    """
    nodes = [dict(n) for n in graph["nodes"]]
    edges = []
    for edge in graph["edges"]:
        copied = dict(edge)
        copied[LINEAGE_KEY] = isolated_lineage(edge.get(LINEAGE_KEY))
        edges.append(copied)

    def other_endpoint(edge: Dict[str, Any], node_idx: int) -> int:
        return edge["b"] if edge["a"] == node_idx else edge["a"]

    def incident_edge_indices(node_idx: int) -> List[int]:
        return [i for i, e in enumerate(edges) if e.get("_removed") is not True and (e["a"] == node_idx or e["b"] == node_idx)]

    # Tracks, for an edge id that later gets superseded by a further merge
    # (a chain of 3+ collinear fragments merges pairwise, so an intermediate
    # merged edge can itself be merged again), what it was replaced by. A
    # node whose "merged_into_edge" was set to an id that is later
    # superseded must have that reference redirected to the FINAL surviving
    # edge id at the end -- otherwise it points to an edge this function
    # itself already removed from its own output, which is not resolvable
    # by any caller. See docs/planreader_wall_room_topology_spec.md's W4
    # notes for the real 3-fragment case this was found against.
    redirect: Dict[str, str] = {}

    changed = True
    safety_cap = len(edges) + 1
    iterations = 0
    while changed and iterations < safety_cap:
        changed = False
        iterations += 1
        for node in nodes:
            node_idx = node["id"]
            if node.get("degree", 0) != 2 or node.get("merged_into_edge"):
                continue
            incident = incident_edge_indices(node_idx)
            if len(incident) != 2:
                continue
            e1_idx, e2_idx = incident
            e1, e2 = edges[e1_idx], edges[e2_idx]
            if _angle_delta(e1["angle_deg"], e2["angle_deg"]) > angle_tolerance_deg:
                continue

            far1 = other_endpoint(e1, node_idx)
            far2 = other_endpoint(e2, node_idx)
            if far1 == far2:
                # A collinear pair that forms a loop back to the same far
                # node (degenerate geometry) -- do not merge, leave as-is.
                continue

            n_far1, n_far2 = nodes[far1], nodes[far2]
            merged_id = f"merged_{e1.get('id', e1_idx)}_{e2.get('id', e2_idx)}"
            merged_edge = {
                **e1,
                "id": merged_id,
                "a": far1,
                "b": far2,
                "x1": n_far1["x"],
                "y1": n_far1["y"],
                "x2": n_far2["x"],
                "y2": n_far2["y"],
            }
            merged_edge["length_pt"] = math.hypot(
                merged_edge["x2"] - merged_edge["x1"], merged_edge["y2"] - merged_edge["y1"]
            )
            merged_edge["angle_deg"] = math.degrees(
                math.atan2(merged_edge["y2"] - merged_edge["y1"], merged_edge["x2"] - merged_edge["x1"])
            ) % 180.0
            merged_edge["collinear_merge_source_edge_ids"] = [
                e1.get("id", e1_idx),
                e2.get("id", e2_idx),
            ]
            # Immediate ids stay as above for existing callers. Leaf ids and
            # primitive lineage union recursively so A+B then AB+C keeps A,B,C.
            # Live graphic fields remain e1's historical sentinels; conflicts
            # are recorded on primitive_lineage, not resolved by picking e1.
            merged_edge["collinear_merge_leaf_edge_ids"] = collinear_merge_leaf_edge_ids(e1, e2)
            merged_edge[LINEAGE_KEY] = isolated_lineage(lineage_from_edges(e1, e2))

            edges[e1_idx]["_removed"] = True
            edges[e2_idx]["_removed"] = True
            edges.append(merged_edge)
            node["degree"] = 0
            node["merged_into_edge"] = merged_id
            redirect[str(e1.get("id", e1_idx))] = merged_id
            redirect[str(e2.get("id", e2_idx))] = merged_id
            changed = True
            break  # restart the node scan against the updated edge list

    final_edges = [e for e in edges if not e.get("_removed")]
    adjacency: Dict[int, List[int]] = {n["id"]: [] for n in nodes}
    for edge_index, edge in enumerate(final_edges):
        adjacency[edge["a"]].append(edge_index)
        adjacency[edge["b"]].append(edge_index)
    for node in nodes:
        if not node.get("merged_into_edge"):
            node["degree"] = len(adjacency[node["id"]])
            continue
        # Resolve through the redirect chain to the final surviving edge --
        # a node's own recorded target may itself have been superseded by a
        # later merge round (see the "redirect" comment above).
        target = node["merged_into_edge"]
        seen_targets = {target}
        while target in redirect:
            target = redirect[target]
            if target in seen_targets:
                break  # defensive: never spin on a malformed redirect cycle
            seen_targets.add(target)
        node["merged_into_edge"] = target

    return {"nodes": nodes, "edges": final_edges, "adjacency": adjacency}


def _merge_collinear_degree_two_nodes_indexed(
    graph: Dict[str, Any],
    angle_tolerance_deg: float = DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG,
) -> Dict[str, Any]:
    """Exact active-incidence equivalent of merge_collinear_degree_two_nodes."""
    nodes = [dict(n) for n in graph["nodes"]]
    edges = []
    for edge in graph["edges"]:
        copied = dict(edge)
        copied[LINEAGE_KEY] = isolated_lineage(edge.get(LINEAGE_KEY))
        edges.append(copied)

    def other_endpoint(edge: Dict[str, Any], node_idx: int) -> int:
        return edge["b"] if edge["a"] == node_idx else edge["a"]

    active_incident: Dict[int, set[int]] = {node["id"]: set() for node in nodes}
    for edge_index, edge in enumerate(edges):
        active_incident.setdefault(edge["a"], set()).add(edge_index)
        active_incident.setdefault(edge["b"], set()).add(edge_index)

    node_position = {node["id"]: pos for pos, node in enumerate(nodes)}
    queue = [
        pos
        for pos, node in enumerate(nodes)
        if node.get("degree", 0) == 2 and not node.get("merged_into_edge")
    ]
    heapq.heapify(queue)
    queued = set(queue)
    redirect: Dict[str, str] = {}
    merge_count = 0
    safety_cap = len(edges) + 1

    def requeue(node_idx: int) -> None:
        pos = node_position.get(node_idx)
        if pos is None or pos in queued:
            return
        node = nodes[pos]
        if node.get("degree", 0) != 2 or node.get("merged_into_edge"):
            return
        heapq.heappush(queue, pos)
        queued.add(pos)

    while queue and merge_count < safety_cap:
        pos = heapq.heappop(queue)
        queued.discard(pos)
        node = nodes[pos]
        node_idx = node["id"]
        if node.get("degree", 0) != 2 or node.get("merged_into_edge"):
            continue

        incident = sorted(active_incident.get(node_idx, ()))
        if len(incident) != 2:
            continue
        e1_idx, e2_idx = incident
        e1, e2 = edges[e1_idx], edges[e2_idx]
        if _angle_delta(e1["angle_deg"], e2["angle_deg"]) > angle_tolerance_deg:
            continue

        far1 = other_endpoint(e1, node_idx)
        far2 = other_endpoint(e2, node_idx)
        if far1 == far2:
            continue

        n_far1, n_far2 = nodes[far1], nodes[far2]
        merged_id = f"merged_{e1.get('id', e1_idx)}_{e2.get('id', e2_idx)}"
        merged_edge = {
            **e1,
            "id": merged_id,
            "a": far1,
            "b": far2,
            "x1": n_far1["x"],
            "y1": n_far1["y"],
            "x2": n_far2["x"],
            "y2": n_far2["y"],
        }
        merged_edge["length_pt"] = math.hypot(
            merged_edge["x2"] - merged_edge["x1"],
            merged_edge["y2"] - merged_edge["y1"],
        )
        merged_edge["angle_deg"] = math.degrees(
            math.atan2(
                merged_edge["y2"] - merged_edge["y1"],
                merged_edge["x2"] - merged_edge["x1"],
            )
        ) % 180.0
        merged_edge["collinear_merge_source_edge_ids"] = [
            e1.get("id", e1_idx),
            e2.get("id", e2_idx),
        ]
        merged_edge["collinear_merge_leaf_edge_ids"] = (
            collinear_merge_leaf_edge_ids(e1, e2)
        )
        merged_edge[LINEAGE_KEY] = isolated_lineage(lineage_from_edges(e1, e2))

        edges[e1_idx]["_removed"] = True
        edges[e2_idx]["_removed"] = True
        active_incident[e1["a"]].discard(e1_idx)
        active_incident[e1["b"]].discard(e1_idx)
        active_incident[e2["a"]].discard(e2_idx)
        active_incident[e2["b"]].discard(e2_idx)

        new_index = len(edges)
        edges.append(merged_edge)
        active_incident.setdefault(far1, set()).add(new_index)
        active_incident.setdefault(far2, set()).add(new_index)

        node["degree"] = 0
        node["merged_into_edge"] = merged_id
        redirect[str(e1.get("id", e1_idx))] = merged_id
        redirect[str(e2.get("id", e2_idx))] = merged_id
        merge_count += 1

        # The legacy implementation restarts the whole node scan after a merge.
        # Only the two far endpoints can have changed eligibility, so requeue
        # them; the min-heap preserves the same earliest-node merge order.
        requeue(far1)
        requeue(far2)

    final_edges = [edge for edge in edges if not edge.get("_removed")]
    adjacency: Dict[int, List[int]] = {node["id"]: [] for node in nodes}
    for edge_index, edge in enumerate(final_edges):
        adjacency[edge["a"]].append(edge_index)
        adjacency[edge["b"]].append(edge_index)
    for node in nodes:
        if not node.get("merged_into_edge"):
            node["degree"] = len(adjacency[node["id"]])
            continue
        target = node["merged_into_edge"]
        seen_targets = {target}
        while target in redirect:
            target = redirect[target]
            if target in seen_targets:
                break
            seen_targets.add(target)
        node["merged_into_edge"] = target

    return {"nodes": nodes, "edges": final_edges, "adjacency": adjacency}


def build_wall_graph_for_viewport(
    segments: Sequence[Dict[str, Any]],
    *,
    gap_snap_tolerance_pt: float = DEFAULT_GAP_SNAP_TOLERANCE_PT,
    collinear_angle_tolerance_deg: float = DEFAULT_COLLINEAR_ANGLE_TOLERANCE_DEG,
) -> Dict[str, Any]:
    """Run the full Stage A pipeline for one viewport's already-scoped segments.

    ``segments`` must already be scoped to a single viewport (topology spec
    Section 4 -- viewport ownership is this function's caller's
    responsibility, not this function's). Returns a graph dict shaped exactly
    like ``pb_vector_geometry_v130.snap_geometry``'s own output
    (``{"nodes", "edges", "adjacency"}``), after intersection-splitting,
    endpoint-snapping, and collinear-merge have all been applied, plus an
    ``"excluded_segments"`` key recording what Section 6.11's pre-filter
    removed and why (never silently dropped from observability).
    """
    structural_segments, excluded_segments = filter_structural_segments(segments)
    point_pairs = _segments_to_point_pairs(structural_segments)
    split_pairs = split_segments_at_intersections(point_pairs)
    split_segment_dicts = _point_pairs_to_segment_dicts(
        split_pairs, source_segments=structural_segments
    )
    audit_short_source = os.environ.get("GPTMAX_W2_SHORT_SOURCE_AUDIT") == "1"
    snapped_graph = _snap_geometry_indexed(
        split_segment_dicts,
        tolerance_pt=gap_snap_tolerance_pt,
        include_endpoint_assignments=audit_short_source,
    )
    isolate_graph_lineage(snapped_graph)
    snap_collapsed_fragments = observe_snap_collapsed_fragments(
        split_segment_dicts, snapped_graph
    )
    merged_graph = _merge_collinear_degree_two_nodes_indexed(
        snapped_graph, angle_tolerance_deg=collinear_angle_tolerance_deg
    )
    merged_graph["excluded_segments"] = excluded_segments
    merged_graph["snap_collapsed_fragments"] = snap_collapsed_fragments
    # Explicit opt-in diagnostic only. This is an observational source
    # provenance ledger; it never changes the wall graph or creates hosts.
    if audit_short_source:
        merged_graph["short_source_fragment_retention_audit"] = (
            audit_short_source_fragments(
                split_segment_dicts, snapped_graph, merged_graph,
                max_length_pt=gap_snap_tolerance_pt,
                producer_reported_collapsed_fragments=snap_collapsed_fragments,
            )
        )
    return merged_graph
