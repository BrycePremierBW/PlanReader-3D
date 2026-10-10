"""Preview source candidate identities with exactly adjacent lost terminal spans.

This consumes an original-source endpoint trace, never benchmark truth. A
preview is not physical equivalence, a new graph edge, a host or a quantity.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from pb_wall_room_topology_wall_identity_v2 import (
    canonical_wall_candidate_id_v2_from_components, canonical_path_fingerprint,
)


def _line(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("invalid original source fragment geometry")
    try:
        finite = all(type(v) in (int, float) and math.isfinite(v) for v in value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("nonfinite original source fragment geometry")
    a, b = tuple(value[:2]), tuple(value[2:])
    if a == b:
        raise ValueError("degenerate original source fragment geometry")
    return a, b


def _exact_path(lines):
    """A single connected path; no rounded-node join or nearest fallback."""
    adjacency = defaultdict(list)
    for index, (a, b) in enumerate(lines):
        adjacency[a].append((index, b))
        adjacency[b].append((index, a))
    if any(len(v) > 2 for v in adjacency.values()):
        return None
    ends = sorted(p for p, edges in adjacency.items() if len(edges) == 1)
    if len(ends) != 2:
        return None
    used, path = set(), [ends[0]]
    while True:
        edges = [(i, p) for i, p in adjacency[path[-1]] if i not in used]
        if not edges:
            break
        if len(edges) != 1:
            return None
        index, point = edges[0]
        used.add(index)
        path.append(point)
    return tuple(path) if len(used) == len(lines) else None


def _source_ids(value):
    if (not isinstance(value, (list, tuple))
            or any(not isinstance(s, str) or not s.strip() for s in value)
            or len(value) != len(set(value))):
        raise ValueError("invalid original source primitive identities")
    return tuple(value)


def _straight_outward_extension(path, shared, outer):
    """Conservative exact straight-line extension, never a backtrack or turn."""
    start, end = path[0], path[-1]
    direction = (end[0] - start[0], end[1] - start[1])
    for a, b in zip(path, path[1:]):
        offset = (a[0] - start[0], a[1] - start[1])
        step = (b[0] - a[0], b[1] - a[1])
        cross = direction[0] * offset[1] - direction[1] * offset[0]
        forward = direction[0] * step[0] + direction[1] * step[1]
        if not math.isfinite(cross) or not math.isfinite(forward) or cross != 0 or forward <= 0:
            return False
    neighbor = path[1] if shared == start else path[-2]
    outward = (shared[0] - neighbor[0], shared[1] - neighbor[1])
    proposed = (outer[0] - shared[0], outer[1] - shared[1])
    cross = outward[0] * proposed[1] - outward[1] * proposed[0]
    forward = outward[0] * proposed[0] + outward[1] * proposed[1]
    return math.isfinite(cross) and math.isfinite(forward) and cross == 0 and forward > 0


def preview_terminal_source_spans(records, audit):
    """Find unique exact terminal ownership within ONE authenticated wall scope.

    Caller must supply the records and W2 audit from the same original-source
    scope. This pure preview cannot authenticate that association itself and
    therefore never raises evidence or publication authority.
    """
    candidates = {}
    endpoint_owners = defaultdict(set)
    viewports = set()
    for record in records:
        cid = record["wall_candidate_id"]
        if not isinstance(cid, str) or not cid or cid in candidates:
            raise ValueError("missing or duplicate wall candidate identity")
        identity = record["physical_identity"]
        primitives = _source_ids(identity["source_primitive_ids"])
        viewport = record["wall_candidate"]["viewport_id"]
        if (not isinstance(viewport, str) or not viewport
                or identity["viewport_id"] != viewport
                or identity["wall_candidate_id"] != cid
                or record["wall_candidate"]["candidate_id"] != cid):
            raise ValueError("conflicting original wall candidate scope")
        viewports.add(viewport)
        if len(viewports) != 1:
            raise ValueError("mixed wall source viewports")
        fragments = record["source_edge_fragments"]
        edge_ids, lines = set(), []
        eligible = identity["status"] == "corroborated" and len(primitives) == 1
        for fragment in fragments:
            eid = fragment["edge_id"]
            if not isinstance(eid, str) or not eid or eid in edge_ids:
                raise ValueError("missing or duplicate original wall source edge")
            edge_ids.add(eid)
            a, b = _line(fragment["geometry"])
            lines.append((a, b))
            fragment_sources = _source_ids(fragment["source_primitive_ids"])
            eligible = eligible and fragment_sources == primitives
            # A competing unresolved or multiple-parent owner also blocks
            # uniqueness. Ignore no candidate merely because it lacks authority.
            for source in fragment_sources:
                endpoint_owners[(source, a)].add(cid)
                endpoint_owners[(source, b)].add(cid)
        candidates[cid] = (record, edge_ids, lines, _exact_path(lines), eligible)

    rows, dispositions, seen = [], Counter(), set()
    for fragment in audit["original_positive_source_short_fragments"]:
        fid = fragment["source_split_fragment_id"]
        if not isinstance(fid, str) or not fid or fid in seen:
            raise ValueError("missing or duplicate traced source fragment identity")
        seen.add(fid)
        if fragment["w2_observation"] != "SNAP_COLLAPSED":
            dispositions["not_proven_collapsed"] += 1
            continue
        nodes = fragment.get("snapped_endpoint_node_ids")
        if (not isinstance(nodes, (tuple, list)) or len(nodes) != 2
                or any(type(n) is not int for n in nodes) or nodes[0] != nodes[1]):
            raise ValueError("source collapse lacks actual common endpoint assignment")
        source = fragment["positive_source_primitive_id"]
        if not isinstance(source, str) or not source:
            raise ValueError("missing traced positive source primitive identity")
        a, b = _line(fragment["original_source_geometry_pt"])
        owners = endpoint_owners[(source, a)] | endpoint_owners[(source, b)]
        if len(owners) != 1:
            dispositions["source_endpoint_owner_unavailable_or_ambiguous"] += 1
            continue
        cid = next(iter(owners))
        record, edge_ids, lines, old_path, eligible = candidates[cid]
        if not eligible:
            dispositions["source_owner_not_corroborated_single_parent"] += 1
            continue
        if fid in edge_ids:
            raise ValueError("collapsed fragment is already a surviving wall edge")
        if old_path is None:
            dispositions["existing_source_path_not_exactly_connected"] += 1
            continue
        # Exactly one end must extend a source path terminal. An internal
        # missing interval, branch, duplicate or overlapping span is skipped.
        terminals = {old_path[0], old_path[-1]}
        shared = {a, b} & terminals
        points = {p for line in lines for p in line}
        if len(shared) != 1 or len({a, b} & points) != 1:
            dispositions["not_a_unique_terminal_extension"] += 1
            continue
        shared_point = next(iter(shared))
        outer = b if shared_point == a else a
        if not _straight_outward_extension(old_path, shared_point, outer):
            dispositions["not_an_exact_straight_outward_extension"] += 1
            continue
        path = _exact_path([*lines, (a, b)])
        if path is None:
            dispositions["proposed_source_path_not_exactly_connected"] += 1
            continue
        viewport = record["wall_candidate"]["viewport_id"]
        identity = canonical_wall_candidate_id_v2_from_components(
            viewport, canonical_path_fingerprint(path), (source,))
        dispositions["unique_terminal_source_path_preview"] += 1
        rows.append({
            "wall_candidate_id": cid,
            "current_source_candidate_identity_id": record["physical_identity"]["candidate_identity_id"],
            "lost_source_fragment_id": fid,
            "positive_source_primitive_id": source,
            "proposed_source_path_pt": path,
            "proposed_source_candidate_identity_id": identity,
            "physical_equivalence_proven": False,
            "graph_mutation_allowed": False,
            "host_count_quantity_publication_allowed": False,
        })
    return {
        "source_path_previews": sorted(rows, key=lambda row: (
            row["positive_source_primitive_id"], row["wall_candidate_id"],
            row["lost_source_fragment_id"])),
        "disposition_counts": dict(sorted(dispositions.items())),
        "source_scope_association_authenticated_by_this_preview": False,
        "physical_equivalence_proven": False,
        "graph_mutation_allowed": False,
        "host_count_quantity_publication_allowed": False,
        "benchmark_accuracy": None,
    }
