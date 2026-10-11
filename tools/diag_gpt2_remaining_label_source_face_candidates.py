"""Read-only first face gate for a native room text bbox on an actual source plan.

These are UNTRUSTED native text candidates. Spatial coincidence with a
SourceRoomFace never authenticates text, face/label ownership, a metric
room dimension, or a quantity. Only SourceRoomLabelAuthority can do that.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

from pb_source_room_label_authority import _point_in_polygon


def source_label_face_candidates(
    native_bbox_pdf_pts: Iterable[float],
    source_faces: Iterable[Any],
) -> dict[str, object]:
    try:
        b=tuple(float(v) for v in native_bbox_pdf_pts)
    except (TypeError,ValueError,OverflowError):
        b=()
    if len(b)!=4 or not all(math.isfinite(v) for v in b) or b[2]<=b[0] or b[3]<=b[1]:
        return {"first_source_face_gate":"native_label_bbox_unavailable",
                "centre_face_record_ids":[],"sampled_box_face_record_ids":[],
                "source_room_label_authenticated":False,"metric_area_published":False}
    x0,y0,x1,y1=b
    samples=((x0,y0),(x1,y0),(x0,y1),(x1,y1),
             ((x0+x1)/2,y0),((x0+x1)/2,y1),
             (x0,(y0+y1)/2),(x1,(y0+y1)/2),
             ((x0+x1)/2,(y0+y1)/2))
    middle=samples[-1]
    center_ids=[]
    sampled_ids=[]
    invalid_ids=[]
    source_shapes_by_receipt={}
    conflicting_source_receipts=set()
    for face in source_faces:
        source_id=getattr(face,"record_id",None)
        identity=(
            source_id if isinstance(source_id,str) and source_id
            and source_id==source_id.strip() else ""
        )
        polygon=getattr(face,"polygon_pdf_pts",None)
        if not identity or not isinstance(polygon,(tuple,list)) or len(polygon)<3:
            invalid_ids.append(identity or "(missing)")
            continue
        try:
            vertices=tuple((float(p[0]),float(p[1])) for p in polygon)
        except (TypeError,ValueError,IndexError,OverflowError):
            invalid_ids.append(identity)
            continue
        if not all(math.isfinite(v) for point in vertices for v in point):
            invalid_ids.append(identity)
            continue
        previous=source_shapes_by_receipt.setdefault(identity,vertices)
        if previous!=vertices:
            conflicting_source_receipts.add(identity)
        if _point_in_polygon(middle,vertices):
            center_ids.append(identity)
        if all(_point_in_polygon(point,vertices) for point in samples):
            sampled_ids.append(identity)
    impacted_conflicts=sorted(
        conflicting_source_receipts.intersection(set(center_ids)|set(sampled_ids))
    )
    center_ids=sorted(set(center_ids)-conflicting_source_receipts)
    sampled_ids=sorted(set(sampled_ids)-conflicting_source_receipts)
    if impacted_conflicts:
        reason="source_face_receipt_geometry_conflict"
    elif len(sampled_ids)>1:
        reason="competing_source_faces_for_full_native_label_samples"
    elif len(sampled_ids)==1 and len(center_ids)==1:
        reason="single_source_face_spatial_candidate_only"
    elif center_ids:
        reason="native_label_centre_only_or_split_face_candidate"
    else:
        reason="native_label_outside_source_room_faces"
    return {
        "first_source_face_gate":reason,
        "centre_face_record_ids":center_ids,
        "sampled_box_face_record_ids":sampled_ids,
        "invalid_source_face_record_ids":sorted(set(invalid_ids)),
        "ambiguous_source_face_record_ids":impacted_conflicts,
        "source_room_label_authenticated":False,
        "source_face_to_label_ownership_proven":False,
        "metric_area_published":False,
    }
