"""Read-only exact producer-owned wall separators for split source-room labels.

Exact wall geometry may prove that TWO face polygons share a physical wall.
It NEVER proves they represent one room or permits dropping the wall.
No nearest-label, PDF scale, inferred area, or topology mutation occurs here.
"""
from __future__ import annotations
import math
from typing import Any

_EPS_PDF_PT=1e-6


def _finite_native_edge(raw: Any):
    try:
        if len(raw)!=2:
            return None
        a,b=raw
        if len(a)!=2 or len(b)!=2:
            return None
        pts=((float(a[0]),float(a[1])),(float(b[0]),float(b[1])))
    except (TypeError,ValueError,IndexError):
        return None
    if not all(math.isfinite(v) for point in pts for v in point):
        return None
    if math.dist(pts[0],pts[1])<=_EPS_PDF_PT:
        return None
    return pts


def _edge_reverse_equal(first,second) -> bool:
    return all(
        math.dist(first[i],second[1-i])<=_EPS_PDF_PT
        for i in range(2)
    )


def _opposite_collinear_positive_overlap(first, second):
    """Observe original collinear opposite source strokes without joining them.

    Only exact collinearity is considered. Endpoint touching, offset parallel
    lines, same-direction lines, and near-collinear snapped guesses do not pass.
    This is a read-only first-failure observation, never wall equivalence.
    """
    a,b=first
    c,d=second
    ux,uy=b[0]-a[0],b[1]-a[1]
    vx,vy=d[0]-c[0],d[1]-c[1]
    if ux*vy-uy*vx != 0.0 or ux*vx+uy*vy >= 0.0:
        return False
    if ux*(c[1]-a[1])-uy*(c[0]-a[0]) != 0.0:
        return False
    norm=ux*ux+uy*uy
    if not math.isfinite(norm) or norm <= _EPS_PDF_PT*_EPS_PDF_PT:
        return False
    t1=((c[0]-a[0])*ux+(c[1]-a[1])*uy)/norm
    t2=((d[0]-a[0])*ux+(d[1]-a[1])*uy)/norm
    overlap=min(1.0,max(t1,t2))-max(0.0,min(t1,t2))
    return overlap > _EPS_PDF_PT/math.sqrt(norm)


def split_face_source_wall_separator_gate(
    candidate: Any,
    faces_by_record_id: dict[str,Any],
) -> dict[str,Any]:
    """CANDIDATE-only pairwise source-wall separator provenance."""
    raw_ids=getattr(candidate,"source_room_face_record_ids",()) or ()
    if not isinstance(raw_ids,(tuple,list)):
        raw_ids=()
    ids=tuple(
        value if isinstance(value,str) and value and value==value.strip() else ""
        for value in raw_ids
    )
    raw_label=getattr(candidate,"label",None)
    label=raw_label if isinstance(raw_label,str) and raw_label.strip() else ""
    result={
        "label":label,
        "source_split_candidate_record_id":str(getattr(candidate,"record_id","") or ""),
        "source_room_face_record_ids":list(ids),
        "pairwise_source_wall_gates":[],
        "merge_source_faces_authorized":False,
        "source_room_label_published":False,
        "metric_quantity_published":False,
    }
    if not label or len(ids)<2 or any(not value for value in ids) or len(set(ids))!=len(ids):
        result["first_gate"]="split_source_face_identity_invalid"
        return result
    actual=[]
    for face_id in ids:
        face=faces_by_record_id.get(face_id)
        if face is None or str(getattr(face,"record_id",""))!=face_id:
            result["first_gate"]="split_source_face_record_missing"
            return result
        if any(
            not isinstance(getattr(candidate,field,None),str)
            or not getattr(candidate,field,None)
            or getattr(candidate,field,None) != getattr(candidate,field,None).strip()
            or getattr(face,field,None) != getattr(candidate,field,None)
            for field in ("document_id","revision_id","source_sha256",
                          "snapshot_id","page_id","decision_scope_id")
        ):
            result["first_gate"]="split_source_face_lineage_mismatch"
            return result
        actual.append(face)

    for i in range(len(actual)):
        for j in range(i+1,len(actual)):
            fa,fb=actual[i],actual[j]
            edge_a=[]
            edge_b=[]
            malformed=False
            for face,bag in ((fa,edge_a),(fb,edge_b)):
                for row in getattr(face,"boundary_wall_edges",()) or ():
                    if not isinstance(row,(tuple,list)) or len(row)!=2:
                        malformed=True
                        continue
                    wall_id,raw=row
                    parsed=_finite_native_edge(raw)
                    if not str(wall_id).strip() or parsed is None:
                        malformed=True
                        continue
                    bag.append((str(wall_id),parsed))
            shared=[]
            competing=[]
            partial_same_wall=[]
            partial_competing=[]
            for wall_a,geom_a in edge_a:
                for wall_b,geom_b in edge_b:
                    exact_reverse=_edge_reverse_equal(geom_a,geom_b)
                    partial_collinear=(
                        not exact_reverse
                        and _opposite_collinear_positive_overlap(geom_a,geom_b)
                    )
                    if not exact_reverse and not partial_collinear:
                        continue
                    source={
                        "source_face_a":str(fa.record_id),
                        "source_face_b":str(fb.record_id),
                        "source_wall_id_a":wall_a,
                        "source_wall_id_b":wall_b,
                        "native_edge_pdf_pts":[list(p) for p in geom_a],
                    }
                    if exact_reverse:
                        if wall_a==wall_b:
                            shared.append(source)
                        else:
                            competing.append(source)
                    elif wall_a==wall_b:
                        partial_same_wall.append(source)
                    else:
                        partial_competing.append(source)
            pair={
                "first_source_face_record_id":str(fa.record_id),
                "second_source_face_record_id":str(fb.record_id),
                "matching_authenticated_wall_segments":shared,
                "same_geometry_competing_wall_owners":competing,
                "partial_collinear_source_spans_observed_only":partial_same_wall,
                "partial_span_competing_wall_owners_observed_only":partial_competing,
            }
            if malformed:
                pair["first_gate"]="malformed_source_wall_subedges"
            elif competing:
                pair["first_gate"]="competing_wall_owners_on_shared_source_edge"
            elif shared:
                pair["first_gate"]="source_proven_wall_separator_do_not_merge"
            elif partial_competing:
                pair["first_gate"]="partial_source_span_competing_wall_owners_unresolved"
            elif partial_same_wall:
                pair["first_gate"]="partial_collinear_source_span_requires_w4_proof"
            else:
                pair["first_gate"]="no_exact_shared_source_wall_separator"
            result["pairwise_source_wall_gates"].append(pair)
    result["first_gate"]="split_label_face_wall_adjacency_diagnostic_only"
    return result
