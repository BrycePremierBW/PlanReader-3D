"""Stage A segment preparation for wall/room topology reconstruction (W2).

Implements ``docs/planreader_wall_room_topology_spec.md`` Section 4's Stage A
and the specific extensions called for in Sections 6.5 and 6.11:

    A1. split_segments_at_intersections   (pb_accuracy_v13_engines_v145, reused
                                            unmodified)
    A2. snap_geometry                     (pb_vector_geometry_v130, reused
                                            unmodified)
    + a hatch/dimension-line pre-filter (Section 6.11) applied BEFORE splitting,
      while the original segment dicts still carry their stroke/dash/layer
      metadata (that metadata does not survive the tuple-pair round trip
      through ``split_segments_at_intersections``, so it must be consulted
      first, not after).
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

import math
from typing import Any, Dict, List, Sequence, Tuple

from pb_accuracy_v13_engines_v145 import split_segments_at_intersections
from pb_vector_geometry_v130 import snap_geometry

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
) -> List[Dict[str, Any]]:
    """Rebuild minimal segment dicts after intersection-splitting.

    Stroke/dash/layer/width metadata does not survive this round trip -- it
    was already consulted (Section 6.11's pre-filter) before splitting, and a
    post-split fragment's provenance is "derived from the pre-split
    structural-candidate segment set" rather than traced to one specific
    parent segment id. Deeper provenance, if ever needed, remains available
    by re-consulting the original (pre-split) segment list separately; this
    function does not lose that list, it simply does not thread it through a
    per-fragment id.
    """
    out = []
    for idx, (p1, p2) in enumerate(pairs):
        out.append(
            {
                "id": f"{id_prefix}_{idx}",
                "kind": "line",
                "x1": p1[0],
                "y1": p1[1],
                "x2": p2[0],
                "y2": p2[1],
                "width": 0.0,
                "stroke": None,
                "fill": None,
                "layer": "",
                "dashes": "",
            }
        )
    return out


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
    edges = [dict(e) for e in graph["edges"]]

    def other_endpoint(edge: Dict[str, Any], node_idx: int) -> int:
        return edge["b"] if edge["a"] == node_idx else edge["a"]

    def incident_edge_indices(node_idx: int) -> List[int]:
        return [i for i, e in enumerate(edges) if e.get("_removed") is not True and (e["a"] == node_idx or e["b"] == node_idx)]

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

            edges[e1_idx]["_removed"] = True
            edges[e2_idx]["_removed"] = True
            edges.append(merged_edge)
            node["degree"] = 0
            node["merged_into_edge"] = merged_id
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
    split_segment_dicts = _point_pairs_to_segment_dicts(split_pairs)
    snapped_graph = snap_geometry(split_segment_dicts, tolerance_pt=gap_snap_tolerance_pt)
    merged_graph = merge_collinear_degree_two_nodes(
        snapped_graph, angle_tolerance_deg=collinear_angle_tolerance_deg
    )
    merged_graph["excluded_segments"] = excluded_segments
    return merged_graph
