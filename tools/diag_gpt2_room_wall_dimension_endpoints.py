"""Read-only native figured-dimension endpoint-to-source-wall first-gate ledger.

This checks exact same-page PDF-point endpoint coincidences against
producer-authenticated source room face subedges. It is NOT dimension
ownership, metric area, scale calibration or QuantityEvidence publication.
"""
from __future__ import annotations

import math
from typing import Any

def _point_on_native_source_subedge(point: Any, edge: Any, *, tolerance: float) -> bool:
    """Exact contact candidate, never dimension/area authority.

    Unit-vector projection avoids an intermediate edge-length-squared product,
    which can underflow for short PDF primitives or overflow for extreme
    coordinates. Malformed, degenerate, and nonfinite cases fail closed.
    """
    try:
        x, y = tuple(float(value) for value in point)
        (ax, ay), (bx, by) = tuple(
            tuple(float(value) for value in pair) for pair in edge
        )
    except (TypeError, ValueError, OverflowError):
        return False
    if not all(math.isfinite(value) for value in (x, y, ax, ay, bx, by)):
        return False
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if (
        not math.isfinite(tolerance)
        or tolerance <= 0.0
        or not math.isfinite(length)
        or length <= tolerance
    ):
        return False

    ux, uy = dx / length, dy / length
    along = (x - ax) * ux + (y - ay) * uy
    if not math.isfinite(along) or along < -tolerance or along > length + tolerance:
        return False
    along = min(length, max(0.0, along))
    nearest_x, nearest_y = ax + along * ux, ay + along * uy
    return math.hypot(x - nearest_x, y - nearest_y) <= tolerance

def _native_point_to_source_subedge_distance(point: Any, edge: Any) -> float | None:
    """Finite native-PDF-point separation for read-only first-failure diagnosis.

    This is *not* a binding tolerance, nearest wall selector, scaling
    authority, or proof that dimension witness extensions reach a room.
    """
    try:
        x, y = tuple(float(value) for value in point)
        (ax, ay), (bx, by) = tuple(
            tuple(float(value) for value in pair) for pair in edge
        )
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(value) for value in (x, y, ax, ay, bx, by)):
        return None
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 0.0:
        return None
    ux, uy = dx / length, dy / length
    along = (x - ax) * ux + (y - ay) * uy
    if not math.isfinite(along):
        return None
    along = min(length, max(0.0, along))
    distance = math.hypot(x - (ax + along * ux), y - (ay + along * uy))
    return distance if math.isfinite(distance) else None


def source_native_dimension_text_room_locality(face: Any, observation: Any) -> dict[str, Any]:
    """Classify source text bbox centre against an original source room face.

    Read-only observation. This is not a figured dimension owner, wall span,
    scale proof, room metric area, or QuantityEvidence. Missing/ambiguous
    source geometry is not a negative factual assertion about a dimension.
    """
    from pb_source_room_label_authority import _point_in_polygon
    result = {
        "observation_id":getattr(observation,"dimension_id",None),
        "first_spatial_gate":"native_dimension_text_geometry_unavailable",
        "native_room_text_spatial_candidate_only":False,
        "room_dimension_owned":False,
        "metric_area_published":False,
    }
    try:
        bbox=tuple(float(v) for v in getattr(observation,"bbox",()) or ())
        verts=tuple(
            (float(v[0]),float(v[1]))
            for v in (getattr(face,"polygon_pdf_pts",()) or ())
        )
    except (ValueError,TypeError,OverflowError,IndexError):
        return result
    if (
        len(bbox)!=4 or not all(math.isfinite(v) for v in bbox)
        or bbox[2]<=bbox[0] or bbox[3]<=bbox[1]
        or len(verts)<3
        or not all(math.isfinite(v) for vertex in verts for v in vertex)
    ):
        return result
    center=((bbox[0]+bbox[2])/2.0,(bbox[1]+bbox[3])/2.0)
    if not all(math.isfinite(v) for v in center):
        return result
    inside=bool(_point_in_polygon(center,verts))
    result["first_spatial_gate"]=(
        "native_dimension_text_centre_inside_source_room_candidate_only"
        if inside else "native_dimension_text_outside_source_room"
    )
    result["native_room_text_spatial_candidate_only"]=inside
    return result


def inspect_source_face_dimension_endpoints(
    face: Any,
    binding: Any,
    *,
    tolerance_pdf_pt: float=0.0001,
) -> dict[str,Any]:
    """Publish diagnostic contact candidates, never claim a room dimension."""
    if not math.isfinite(tolerance_pdf_pt) or not 0 < tolerance_pdf_pt <= 0.001:
        raise ValueError("precision must remain exact-PDF-point level")
    face_owner=str(getattr(face,"record_id","") or "")
    observation=str(getattr(binding,"observation_id","") or "")
    edges=tuple(getattr(face,"boundary_wall_edges",()) or ())
    endpoints=getattr(binding,"endpoints",None)
    output={
        "source_face_record_id":face_owner,
        "source_dimension_observation_id":observation,
        "binding_status":str(getattr(binding,"status","")),
        "source_line_id":str(getattr(binding,"dimension_line_id","") or ""),
        "source_witness_line_ids":list(getattr(binding,"witness_line_ids",()) or ()),
        "endpoint_wall_owner_ids":[],
        "endpoint_nearest_source_wall_distance_pdf_pts_diagnostic_only":[],
        "metric_area_published":False,
        "room_dimension_owned":False,
    }
    if not face_owner or not observation:
        status="source_identity_missing"
    elif not edges:
        status="source_owned_wall_subedges_missing"
    elif not isinstance(endpoints,(tuple,list)) or len(endpoints)!=2:
        status="source_dimension_endpoints_unbound"
    elif any(
        not isinstance(edge_row,(tuple,list)) or len(edge_row)!=2
        for edge_row in edges
    ):
        status="source_owned_wall_subedges_malformed"
    else:
        contacts=[]
        for point in endpoints:
            distances=[
                distance for wall_id, edge in edges
                if isinstance(wall_id, str) and wall_id.strip()
                for distance in (_native_point_to_source_subedge_distance(point, edge),)
                if distance is not None
            ]
            output[
                "endpoint_nearest_source_wall_distance_pdf_pts_diagnostic_only"
            ].append(min(distances) if distances else None)
            ids=sorted({
                str(wall_id) for wall_id,edge in edges
                if str(wall_id).strip() and _point_on_native_source_subedge(
                    point,edge,tolerance=tolerance_pdf_pt
                )
            })
            contacts.append(ids)
        output["endpoint_wall_owner_ids"]=contacts
        if any(not ids for ids in contacts):
            status="figured_endpoint_not_on_source_room_wall"
        elif any(len(ids)!=1 for ids in contacts):
            status="figured_endpoint_competing_source_wall_owners"
        elif contacts[0][0]==contacts[1][0]:
            status="figured_endpoints_same_wall_no_span"
        else:
            # Even two exact edge contacts do NOT establish source dimension
            # attribution: witness semantics and span/axis must still prove it.
            status="two_source_wall_endpoint_contacts_candidate_only"
    output["first_authority_gate"]=status
    return output
