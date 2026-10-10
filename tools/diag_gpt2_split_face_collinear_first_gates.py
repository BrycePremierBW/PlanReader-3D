"""Read-only collinear source wall subedge audit for split room faces.

Exact reversed-edge equality is intentionally kept as the only positive wall
separator proof elsewhere. This tool identifies *why* it fails, never grants
source-face ownership, room unions, scale or quantities.
"""
from __future__ import annotations

import math
from typing import Any

from tools.diag_gpt2_split_label_wall_separators import (
    _finite_native_edge,
    _opposite_collinear_positive_overlap,
)

EPS = 1e-6


def _overlap(a: Any, b: Any) -> float:
    """Return candidate common span in PDF points, 0 unless collinear."""
    p = _finite_native_edge(a)
    q = _finite_native_edge(b)
    if p is None or q is None:
        return 0.0
    (x0, y0), (x1, y1) = p
    vx, vy = x1 - x0, y1 - y0
    length = math.hypot(vx, vy)
    if length <= EPS:
        return 0.0
    for x, y in q:
        if abs(vx * (y - y0) - vy * (x - x0)) / length > EPS:
            return 0.0
    ux, uy = vx / length, vy / length
    t0, t1 = sorted(((q[i][0] - x0) * ux + (q[i][1] - y0) * uy for i in (0, 1)))
    return max(0.0, min(length, t1) - max(0.0, t0))


def audit_collinear_candidates(candidate: Any, faces_by_record_id: dict[str, Any]) -> dict[str, Any]:
    """Inspect only pairs already named by a source producer split candidate."""
    raw_ids = getattr(candidate, "source_room_face_record_ids", ()) or ()
    ids = tuple(raw_ids) if isinstance(raw_ids, (tuple, list)) else ()
    label = getattr(candidate, "label", None)
    result = {"label": label if isinstance(label, str) else "",
              "source_face_record_ids": list(ids),
              "candidate_shared_spans": [],
              "source_room_label_published": False,
              "merge_source_faces_authorized": False,
              "metric_quantity_published": False}
    if (
        len(ids) < 2 or not result["label"].strip()
        or any(not isinstance(value, str) or not value
               or value != value.strip() for value in ids)
        or len(set(ids)) != len(ids)
    ):
        result["first_gate"] = "invalid_split_candidate"
        return result
    fields = ("document_id", "revision_id", "source_sha256", "snapshot_id",
              "page_id", "decision_scope_id")
    faces = []
    for face_id in ids:
        face = faces_by_record_id.get(face_id)
        if face is None or str(getattr(face, "record_id", "")) != str(face_id):
            result["first_gate"] = "missing_source_face"
            return result
        if any(
            not isinstance(getattr(candidate, key, None), str)
            or not getattr(candidate, key, None)
            or getattr(candidate, key, None) != getattr(candidate, key, None).strip()
            or getattr(face, key, None) != getattr(candidate, key, None)
            for key in fields
        ):
            result["first_gate"] = "source_lineage_conflict"
            return result
        faces.append(face)
    for i, left in enumerate(faces):
        for right in faces[i+1:]:
            for left_row in getattr(left, "boundary_wall_edges", ()) or ():
                if not isinstance(left_row, (tuple, list)) or len(left_row) != 2:
                    result["first_gate"] = "malformed_source_wall_edge"
                    result["candidate_shared_spans"] = []
                    return result
                lid, ledge = left_row
                if not str(lid).strip() or _finite_native_edge(ledge) is None:
                    result["first_gate"] = "malformed_source_wall_edge"
                    result["candidate_shared_spans"] = []
                    return result
                for right_row in getattr(right, "boundary_wall_edges", ()) or ():
                    if not isinstance(right_row, (tuple, list)) or len(right_row) != 2:
                        result["first_gate"] = "malformed_source_wall_edge"
                        result["candidate_shared_spans"] = []
                        return result
                    rid, redge = right_row
                    if not str(rid).strip() or _finite_native_edge(redge) is None:
                        result["first_gate"] = "malformed_source_wall_edge"
                        result["candidate_shared_spans"] = []
                        return result
                    span = _overlap(ledge, redge)
                    if span <= EPS:
                        continue
                    result["candidate_shared_spans"].append({
                        "face_a": str(left.record_id), "face_b": str(right.record_id),
                        "wall_a": str(lid), "wall_b": str(rid),
                        "wall_id_agrees": bool(str(lid) and str(lid) == str(rid)),
                        "overlap_pdf_points": round(span, 9),
                        "opposite_exact_source_stroke_observed": (
                            _opposite_collinear_positive_overlap(ledge, redge)
                        ),
                        "gate": "collinear_subedge_candidate_only",
                    })
    result["first_gate"] = ("collinear_candidates_untrusted"
                            if result["candidate_shared_spans"]
                            else "no_collinear_source_wall_candidate")
    return result
