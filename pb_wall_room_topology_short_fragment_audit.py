"""Read-only W2 short-source-fragment retention and snap-displacement ledger.

The input is the official pre-snap split fragment inventory plus the actual
W2 snapped graph and collinear-merged graph. This does NOT rebuild, resurrect,
connect, bind or publish a fragment. In particular, source-parent coverage
does not imply that a neighboring unpainted gap is source-supported.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping, Sequence

from pb_wall_room_topology_primitive_lineage import (
    LINEAGE_KEY, fragment_contained_in_segment,
)


def _positive_single_parent(fragment: Mapping[str, Any]):
    payload = fragment.get(LINEAGE_KEY) or {}
    if not isinstance(payload, Mapping):
        return None
    ids = payload.get("source_primitive_ids") or ()
    records = payload.get("source_records") or ()
    if (not isinstance(ids, (tuple,list)) or len(ids)!=1
            or not isinstance(ids[0],str) or not ids[0]
            or not isinstance(records,(tuple,list)) or len(records)!=1
            or not isinstance(records[0],Mapping)):
        return None
    record=records[0]
    if record.get("id")!=ids[0] or record.get("page_coords_present") is not True:
        return None
    try:
        if not fragment_contained_in_segment(
                ((float(fragment["x1"]),float(fragment["y1"])),
                 (float(fragment["x2"]),float(fragment["y2"]))),
                record):
            return None
    except (ValueError,TypeError,KeyError,OverflowError):
        return None
    return ids[0]


def _snapped_trace(snapped_graph):
    """Validate the actual node/edge trace instead of treating absence as proof."""
    nodes = {}
    for node in snapped_graph["nodes"]:
        nid = node.get("id")
        if type(nid) is not int or nid in nodes:
            raise ValueError("invalid or duplicate W2 snapped node id")
        try:
            position = (float(node["x"]), float(node["y"]))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("invalid W2 snapped node geometry") from None
        if not all(math.isfinite(v) for v in position):
            raise ValueError("nonfinite W2 snapped node geometry")
        nodes[nid] = position
    edges = {}
    for edge in snapped_graph["edges"]:
        eid = edge.get("id")
        pair = (edge.get("a"), edge.get("b"))
        if not isinstance(eid, str) or not eid or eid in edges:
            raise ValueError("invalid or duplicate W2 snapped edge id")
        if (any(type(nid) is not int or nid not in nodes for nid in pair)
                or pair[0] == pair[1]):
            raise ValueError("invalid W2 snapped edge endpoints")
        edges[eid] = pair
    assignments = snapped_graph.get("endpoint_snap_assignments", {})
    if not isinstance(assignments, Mapping):
        raise ValueError("invalid W2 endpoint assignment trace")
    for fid, pair in assignments.items():
        if (not isinstance(fid, str) or not fid
                or not isinstance(pair, (tuple, list)) or len(pair) != 2
                or any(type(nid) is not int or nid not in nodes for nid in pair)):
            raise ValueError("invalid W2 endpoint assignment")
        if fid in edges:
            if tuple(pair) != edges[fid]:
                raise ValueError("W2 endpoint trace disagrees with surviving edge")
        elif pair[0] != pair[1]:
            raise ValueError("missing W2 edge has distinct traced endpoints")
    return nodes, edges, assignments


def audit_short_source_fragments(
    split_fragments: Sequence[Mapping[str, Any]],
    snapped_graph: Mapping[str, Any],
    merged_graph: Mapping[str, Any],
    *,
    max_length_pt: float,
    producer_reported_collapsed_fragments: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Account for each *positive-source* short split fragment exactly once.

    "SNAP_COLLAPSED" requires W2's actual endpoint trace to assign both
    endpoints to one node. Absence without that trace remains unresolved.
    Collapse is not evidence of a missing physical wall or permission to
    extend geometry. "COLLINEAR_MERGED" means the original split-edge id is
    retained in the later edge's leaf ancestry, not that its raw length was
    metrically preserved. A displacement is observational only.
    """
    if (type(max_length_pt) not in (int,float)
            or not math.isfinite(max_length_pt)
            or max_length_pt <= 0):
        raise ValueError("invalid observational source fragment length")
    if not isinstance(split_fragments,(tuple,list)):
        raise ValueError("source split inventory must be a sequence")
    nodes, snapped_edges, assignments = _snapped_trace(snapped_graph)
    if not isinstance(producer_reported_collapsed_fragments, (tuple, list)):
        raise ValueError("invalid producer disappearance ledger")
    reported = set()
    for row in producer_reported_collapsed_fragments:
        if (not isinstance(row, Mapping) or not isinstance(row.get("id"), str)
                or not row["id"].strip() or row["id"] in reported):
            raise ValueError("invalid or duplicated producer disappearance receipt")
        reported.add(row["id"])
    if reported.intersection(snapped_edges):
        raise ValueError("producer disappearance ledger conflicts with surviving graph")
    merged_edges = merged_graph["edges"]
    final_leaf_ids=set()
    direct_ids=set()
    for edge in merged_edges:
        eid=edge.get("id")
        if not isinstance(eid,str) or not eid.strip():
            raise ValueError("final source edge lacks original identity")
        if eid in direct_ids:
            raise ValueError("duplicate final source edge id")
        direct_ids.add(eid)
        leaves=edge.get("collinear_merge_leaf_edge_ids") or (eid,)
        if not isinstance(leaves,(tuple,list)) or any(
            not isinstance(k,str) or not k.strip() for k in leaves
        ):
            raise ValueError("invalid W2 merge leaf provenance")
        if (len(set(leaves)) != len(leaves)
                or any(k not in snapped_edges for k in leaves)
                or final_leaf_ids.intersection(leaves)):
            raise ValueError("duplicate or foreign W2 merge leaf provenance")
        final_leaf_ids.update(leaves)
    out=[]
    seen=set()
    counts=Counter()
    for fragment in split_fragments:
        if not isinstance(fragment,Mapping):
            raise ValueError("untyped source split fragment")
        fid=fragment.get("id")
        if not isinstance(fid,str) or not fid.strip() or fid in seen:
            raise ValueError("missing or repeated original split-fragment id")
        seen.add(fid)
        try:
            a=(float(fragment["x1"]),float(fragment["y1"]))
            b=(float(fragment["x2"]),float(fragment["y2"]))
        except (TypeError,ValueError,KeyError,OverflowError):
            raise ValueError("unmeasurable original split source geometry") from None
        if not all(math.isfinite(x) for x in (*a,*b)):
            raise ValueError("nonfinite original split source geometry")
        length=math.dist(a,b)
        # Individually finite original PDF coordinates can overflow
        # Pythagorean distance. Silently skipping that fragment would make
        # the source fragment census look complete when it cannot be measured.
        if not math.isfinite(length):
            raise ValueError("nonfinite original split source length")
        if not (1e-7<length<=max_length_pt):
            continue
        primitive_id = _positive_single_parent(fragment)
        if primitive_id is None:
            counts["UNPROVEN_SOURCE_PARENT_SKIPPED"]+=1
            continue
        pair = snapped_edges.get(fid)
        if pair is None:
            pair = assignments.get(fid)
            status = ("SNAP_COLLAPSED" if pair is not None
                      else "PRODUCER_REPORTED_EDGE_ABSENT" if fid in reported
                      else "EDGE_ABSENT_UNRESOLVED")
            if fid in final_leaf_ids:
                raise ValueError("absent W2 fragment appears in final merge ancestry")
        else:
            if fid in direct_ids:
                status="RETAINED_RAW_EDGE"
            elif fid in final_leaf_ids:
                status="COLLINEAR_MERGED"
            else:
                status="UNRESOLVED_MERGE_ANCESTRY"
        positions = [nodes[pair[0]], nodes[pair[1]]] if pair is not None else None
        displacement = (max(math.dist(a, positions[0]), math.dist(b, positions[1]))
                        if positions is not None else None)
        # Finite individual W2 node coordinates can still overflow math.dist
        # when they are very far apart. Observation is not licence to serialize
        # inf as a real endpoint displacement or a recoverable source span.
        if displacement is not None and not math.isfinite(displacement):
            raise ValueError("nonfinite W2 endpoint displacement")
        counts[status]+=1
        out.append({
            "source_split_fragment_id":fid,
            "positive_source_primitive_id":primitive_id,
            "original_source_geometry_pt":[*a,*b],
            "original_source_length_pt":length,
            "w2_observation":status,
            "snapped_endpoint_node_ids":list(pair) if pair is not None else None,
            "snapped_endpoint_geometry_pt":positions,
            "max_endpoint_snap_displacement_pt":displacement,
            "wall_host_authority":"NOT_PROVEN_BY_THIS_AUDIT",
            "source_gap_closure":"NOT_PROVEN_BY_THIS_AUDIT",
            "count_and_quantity_authority":"NOT_PROVEN_BY_THIS_AUDIT",
        })
    if set(assignments) - seen:
        raise ValueError("W2 endpoint assignment lacks original split fragment")
    if reported - seen:
        raise ValueError("producer disappearance ledger conflicts with source inventory")
    return {
        "observational_max_raw_fragment_length_pt":float(max_length_pt),
        "observed_positive_source_short_fragment_count":len(out),
        "w2_retention_reason_counts":dict(sorted(counts.items())),
        "original_positive_source_short_fragments":out,
        "physical_host_publication_allowed":False,
        "opening_count_publication_allowed":False,
        "metric_quantity_publication_allowed":False,
        "benchmark_accuracy":None,
    }
