"""Read-only G17 flank -> source primitive -> W2 fragment -> W4 endpoint audit.

Every relationship here is observational. The existing host/equivalence
authorities retain exclusive promotion authority; no graph is repaired here.
"""
from __future__ import annotations

from collections import defaultdict
import math

from pb_opening_host_binding_authority import (
    _COORD_TOL, _RASTER_WHOLE_WALL_CENTER_TOL_PT,
    _endpoints, _project, _source_line_axis_data,
)
from pb_wall_room_topology_primitive_lineage import fragment_contained_in_segment
from pb_wall_room_topology_stage_a import DEFAULT_GAP_SNAP_TOLERANCE_PT


def _id(value):
    return isinstance(value, str) and bool(value.strip())


def _line(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("missing source line geometry")
    if any(type(x) not in (float, int) for x in value):
        raise ValueError("untyped source line geometry")
    try:
        line = tuple(float(x) for x in value)
        length = math.dist(line[:2], line[2:])
    except (ValueError, TypeError, OverflowError):
        raise ValueError("unmeasurable source line geometry") from None
    if not all(math.isfinite(x) for x in line) or not math.isfinite(length):
        raise ValueError("nonfinite source line geometry")
    if length <= _COORD_TOL:
        raise ValueError("degenerate source line geometry")
    return line


def _validate_opening_geometry(opening):
    values = (*opening.origin, *opening.axis, *opening.normal,
              opening.length, opening.thickness)
    try:
        finite = all(type(x) in (int,float) and math.isfinite(x) for x in values)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("nonfinite opening coordinate frame")
    if (len(opening.origin) != 2 or len(opening.axis) != 2 or len(opening.normal) != 2
            or opening.length <= 0 or opening.thickness <= 0
            or abs(math.hypot(*opening.axis) - 1) > _COORD_TOL
            or abs(math.hypot(*opening.normal) - 1) > _COORD_TOL
            or abs(sum(a*b for a,b in zip(opening.axis, opening.normal))) > _COORD_TOL):
        raise ValueError("invalid opening coordinate frame")


def _axis(line, opening):
    data = _source_line_axis_data(_line(line), opening)
    if data is not None and not all(math.isfinite(x) for x in data):
        raise ValueError("nonfinite source projection")
    return data


def source_flanks(support, opening_record, opening):
    """Validate receipts then mirror the existing host's face/end predicates.

    The caller re-resolves each receipt through the source visibility
    authority. This pure function cannot authenticate arbitrary caller data.
    """
    _validate_opening_geometry(opening)
    required = tuple(opening_record.source_observation_ids)
    actual = tuple(row.observation_id for row in support)
    if (not required or any(not _id(x) for x in (*required, *actual))
            or len(set(required)) != len(required)
            or len(set(actual)) != len(actual) or set(actual) != set(required)):
        raise ValueError("missing, duplicate or substituted G17 support receipts")
    for row in support:
        if any(getattr(row, field) != getattr(opening_record, field) for field in (
                "document_id", "revision_id", "source_sha256", "snapshot_id", "page_id")):
            raise ValueError("foreign G17 source support lineage")
    faces = [r for r in support if r.observation_kind == "raster_wall_band_face"]
    ends = [r for r in support if r.observation_kind == "raster_wall_band_end"]
    if len(faces) != 4 or len(ends) != 2:
        raise ValueError("G17 face/end support incomplete")
    intervals = defaultdict(list)
    for face in faces:
        data = _axis(face.geometry, opening)
        if data is None:
            raise ValueError("G17 face not parallel to aperture")
        lo, hi, offset = data
        intervals[(lo, hi)].append((offset, face.observation_id))
    if len(intervals) != 2 or any(len(v) != 2 for v in intervals.values()):
        raise ValueError("G17 face intervals ambiguous")
    flanks = []
    pixel_tol = _RASTER_WHOLE_WALL_CENTER_TOL_PT + _COORD_TOL
    for (lo, hi), offsets in sorted(intervals.items()):
        cross_lo, cross_hi = sorted(x[0] for x in offsets)
        if (cross_hi - cross_lo <= _COORD_TOL
                or cross_lo > pixel_tol or cross_hi < -pixel_tol):
            raise ValueError("G17 face band invalid")
        if lo < -pixel_tol and abs(hi) <= pixel_tol:
            role, edge = "left", hi
        elif hi > opening.length + pixel_tol and abs(lo - opening.length) <= pixel_tol:
            role, edge = "right", lo
        else:
            raise ValueError("G17 flank endpoint not on aperture")
        matching = []
        for end in ends:
            pts = _endpoints(_line(end.geometry))
            along = tuple(_project(p, opening.origin, opening.axis) for p in pts)
            cross = sorted(_project(p, opening.origin, opening.normal) for p in pts)
            if (all(math.isfinite(x) for x in (*along, *cross))
                    and all(abs(x-edge) <= _COORD_TOL for x in along)
                    and abs(cross[0]-cross_lo) <= _COORD_TOL
                    and abs(cross[1]-cross_hi) <= _COORD_TOL):
                matching.append(end.observation_id)
        if len(matching) != 1 or any(f["role"] == role for f in flanks):
            raise ValueError("G17 flank end ownership ambiguous")
        flanks.append({"role":role, "axis_span_pt":[lo,hi],
                       "normal_band_pt":[cross_lo,cross_hi], "endpoint_pt":edge,
                       "face_observation_ids":sorted(x[1] for x in offsets),
                       "end_observation_id":matching[0]})
    if {f["role"] for f in flanks} != {"left", "right"}:
        raise ValueError("G17 opposite flank support unavailable")
    return sorted(flanks, key=lambda f:f["role"])


def _flank_metrics(line, opening, flank):
    data = _axis(line, opening)
    if data is None:
        return {"parallel_to_aperture":False, "flank_predicates_pass":False}
    lo, hi, offset = data
    endpoint = hi if flank["role"] == "left" else lo
    distance = abs(endpoint-flank["endpoint_pt"])
    overlap = min(hi,flank["axis_span_pt"][1])-max(lo,flank["axis_span_pt"][0])
    if not all(math.isfinite(x) for x in (distance,overlap)):
        raise ValueError("nonfinite flank endpoint or overlap projection")
    pixel_tol = _RASTER_WHOLE_WALL_CENTER_TOL_PT + _COORD_TOL
    snap_tol = DEFAULT_GAP_SNAP_TOLERANCE_PT + _COORD_TOL
    inside_band=(flank["normal_band_pt"][0]-pixel_tol <= offset
                 <= flank["normal_band_pt"][1]+pixel_tol)
    return {"parallel_to_aperture":True, "axis_span_pt":[lo,hi],
            "normal_offset_pt":offset, "flank_endpoint_distance_pt":distance,
            "flank_overlap_pt":overlap,
            "endpoint_within_existing_snap_tolerance":distance<=snap_tol,
            "normal_inside_existing_flank_band":inside_band,
            "positive_existing_flank_overlap":overlap>pixel_tol,
            "flank_predicates_pass":bool(distance<=snap_tol and overlap>pixel_tol and inside_band)}


def _candidate_first_gate(usable, fragments, chain):
    """Observed gates in dependency order; never rank competing wall owners."""
    if not usable:
        return "w4_source_identity_unavailable"
    if not fragments:
        return "actual_w2_source_edge_receipt_missing"
    if any(f["edge_receipt_conflicted"] for f in fragments):
        return "w2_source_edge_receipt_ownership_conflict"
    contained=[f for f in fragments if f["source_parent_containment_observed"]]
    if not contained:
        return "w2_geometry_not_contained_in_source_parent"
    if not any(f["w2_flank_metrics"]["flank_predicates_pass"] for f in contained):
        return "local_w2_fragment_misses_sealed_flank"
    if not any(s["w4_flank_metrics"]["flank_predicates_pass"] for s in chain):
        return "local_w4_snapped_chain_misses_sealed_flank"
    return "physical_equivalence_and_host_authority_still_required"


def audit_raster_flank_ownership(records, source_lines, support, opening_record, opening):
    """Keep all exact source owners, remote edges and disappearance negatives."""
    flanks = source_flanks(support, opening_record, opening)
    by_source = defaultdict(list)
    by_edge = defaultdict(list)
    collapsed = defaultdict(list)
    seen = set()
    parent_conflicts = []
    for record in records:
        cid = record.wall_candidate_id
        if not _id(cid) or cid in seen:
            raise ValueError("missing or duplicate W4 candidate address")
        seen.add(cid)
        identity = record.physical_identity
        if (identity.wall_candidate_id != cid or record.wall_candidate.candidate_id != cid
                or identity.viewport_id != record.wall_candidate.viewport_id):
            raise ValueError("contradictory W4 identity address or viewport")
        parents = tuple(identity.source_primitive_ids)
        if any(not _id(x) for x in parents) or len(set(parents)) != len(parents):
            raise ValueError("malformed W4 source parent inventory")
        for parent in parents:
            by_source[parent].append(record)
        for fragment in record.source_edge_fragments:
            if not _id(fragment.edge_id):
                raise ValueError("missing W2 edge address")
            fragment_parents = tuple(fragment.source_primitive_ids)
            if (not fragment_parents or any(not _id(x) for x in fragment_parents)
                    or len(set(fragment_parents)) != len(fragment_parents)):
                raise ValueError("missing or malformed W2 source parents")
            foreign = sorted(set(fragment_parents)-set(parents))
            if foreign:
                parent_conflicts.append({"source_edge_id":fragment.edge_id,
                    "wall_candidate_id":cid,"unowned_source_parent_ids":foreign})
            by_edge[fragment.edge_id].append((record, fragment))
        for fragment in record.source_snap_collapsed_fragments:
            if not _id(fragment.edge_id):
                raise ValueError("missing collapsed W2 source address")
            for parent in fragment.source_primitive_ids:
                if not _id(parent):
                    raise ValueError("invalid collapsed W2 source parent")
                collapsed[parent].append((record,fragment))

    conflicts = []
    for eid, receipts in sorted(by_edge.items()):
        if len(receipts) > 1:
            conflicts.append({"source_edge_id":eid,
                              "w4_candidate_addresses":sorted(r.wall_candidate_id for r,_ in receipts),
                              "reason":"multiple_surviving_source_edge_receipts"})
    conflicting_ids = {c["source_edge_id"] for c in conflicts}
    rows = []
    for flank in flanks:
        primitives = []
        unmatched = []
        for parent,line in sorted(source_lines.items()):
            if not _id(parent):
                raise ValueError("invalid authenticated source primitive address")
            metrics = _flank_metrics(line,opening,flank)
            if not metrics["flank_predicates_pass"]:
                if (metrics["parallel_to_aperture"]
                        and metrics["normal_inside_existing_flank_band"]
                        and metrics["positive_existing_flank_overlap"]):
                    unmatched.append({"source_primitive_id":parent,
                        "original_source_line_pt":list(_line(line)),
                        "source_flank_metrics":metrics,
                        "ancestry_candidate_ids":sorted(r.wall_candidate_id for r in by_source.get(parent,())),
                        "host_contact_proven":False})
                continue
            owners = []
            for record in sorted(by_source.get(parent,()),key=lambda r:r.wall_candidate_id):
                owner_identity = record.physical_identity
                fragments = []
                for fragment in sorted(record.source_edge_fragments,key=lambda f:f.edge_id):
                    if parent not in fragment.source_primitive_ids:
                        continue
                    raw = _line(fragment.geometry)
                    contained = fragment_contained_in_segment(
                        (raw[:2],raw[2:]), dict(zip(("x1","y1","x2","y2"),_line(line))))
                    fragments.append({"source_edge_id":fragment.edge_id,
                        "w2_original_line_pt":list(raw),
                        "source_parent_containment_observed":contained,
                        "edge_receipt_conflicted":fragment.edge_id in conflicting_ids,
                        "w2_flank_metrics":_flank_metrics(raw,opening,flank)})
                points = record.wall_candidate.centerline_pts
                chain = []
                for a,b in zip(points,points[1:]):
                    raw = _line((*a,*b))
                    chain.append({"w4_snapped_line_pt":list(raw),
                                  "w4_flank_metrics":_flank_metrics(raw,opening,flank)})
                owners.append({"wall_candidate_id":record.wall_candidate_id,
                    "identity_usable":owner_identity.usable, "source_edge_fragments":fragments,
                    "w4_chain_segments":sorted(chain,key=lambda x:x["w4_snapped_line_pt"]),
                    "first_observed_candidate_failure":_candidate_first_gate(owner_identity.usable,fragments,chain),
                    "host_contact_proven":False})
            lost = []
            for record, fragment in sorted(collapsed.get(parent,()),key=lambda x:(x[0].wall_candidate_id,x[1].edge_id)):
                lost.append({"wall_candidate_id":record.wall_candidate_id,
                    "source_edge_id":fragment.edge_id,
                    "original_collapsed_line_pt":list(_line(fragment.geometry)),
                    "producer_reason_code":fragment.reason_code,
                    "appears_in_surviving_edge_inventory":fragment.edge_id in by_edge,
                    "surviving_edge_or_host_evidence":False})
            primitives.append({"source_primitive_id":parent,
                "original_source_line_pt":list(_line(line)), "source_flank_metrics":metrics,
                "w4_ancestry_candidates":owners, "collapsed_source_fragments":lost})
        rows.append({**flank,"matching_original_source_primitives":primitives,
            "original_source_lines_missing_flank_endpoint":unmatched,
            "all_observed_candidate_failures":sorted({
                owner["first_observed_candidate_failure"] for p in primitives
                for owner in p["w4_ancestry_candidates"]}),
            "first_observed_failure":("source_primitive_endpoint_misses_sealed_flank" if not primitives and unmatched
                else "no_source_primitive_at_sealed_flank" if not primitives
                else "source_primitive_without_w4_parent" if not any(p["w4_ancestry_candidates"] for p in primitives)
                else "local_w2_w4_and_equivalence_authority_still_required")})
    return {"flanks":rows,"edge_receipt_conflicts":conflicts,
        "source_edge_parent_identity_contradictions":sorted(parent_conflicts,
            key=lambda x:(x["source_edge_id"],x["wall_candidate_id"])),
        "source_scope_authenticated_by_this_audit":False,
        "host_publication_allowed":False,"opening_count_publication_allowed":False,
        "metric_quantity_publication_allowed":False,"physical_equivalence_proven":False,
        "benchmark_accuracy":None}
