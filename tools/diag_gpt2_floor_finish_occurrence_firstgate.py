"""Read-only source occurrence lineage first gates for room floor finishes.

An authenticated source material *occurrence* is not evidence that a
particular closed physical room owns that finish. Never publish areas here.
"""
from __future__ import annotations

from collections import Counter
import math
from typing import Any


def _owned_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _native_bbox(value: Any):
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    try:
        bbox=tuple(float(v) for v in value)
    except (TypeError, ValueError, OverflowError):
        return None
    return bbox if all(math.isfinite(v) for v in bbox) and bbox[2]>bbox[0] and bbox[3]>bbox[1] else None


def inspect_floor_finish_occurrence_first_gates(scope: Any, viewport: Any, *, sha: str, page_id: str) -> dict[str, Any]:
    records=tuple(getattr(scope,"records",()) or ())
    expected_view=getattr(viewport,"view_id",None)
    expected_page=page_id
    view_bbox=_native_bbox(getattr(viewport,"bounding_box",None))
    owner_valid=(
        _owned_text(expected_view) and _owned_text(expected_page)
        and _owned_text(sha)
        and getattr(viewport,"status",None)=="resolved"
        and getattr(viewport,"view_type",None)=="floor_plan"
        and view_bbox is not None
    )
    receipt_counts=Counter(
        getattr(rec,"record_id",None) for rec in records
        if _owned_text(getattr(rec,"record_id",None))
    )
    observation_counts=Counter(
        obs for rec in records
        for obs in (getattr(rec,"source_text_observation_ids",()) or ())
        if _owned_text(obs)
    )
    rows=[]
    for record in records:
        record_id=getattr(record,"record_id",None)
        obs=getattr(record,"source_text_observation_ids",()) or ()
        own_box=_native_bbox(getattr(record,"bbox_pdf_pts",None))
        reason=(
            "source_floor_plan_viewport_unresolved"
            if not owner_valid else
            "material_occurrence_source_scope_conflict"
            if (
                getattr(record,"source_sha256",None)!=sha
                or getattr(record,"page_id",None)!=expected_page
                or getattr(record,"viewport_id",None)!=expected_view
            ) else
            "material_occurrence_record_id_ambiguous"
            if not _owned_text(record_id) or receipt_counts[record_id]!=1 else
            "material_occurrence_observation_receipt_ambiguous"
            if (
                not isinstance(obs,(tuple,list)) or not obs
                or any(not _owned_text(x) or observation_counts[x]!=1 for x in obs)
                or len(obs)!=len(set(obs))
            ) else
            "material_occurrence_definition_receipt_unavailable"
            if not _owned_text(getattr(record,"definition_record_id",None))
            or not _owned_text(getattr(record,"source_evidence_id",None)) else
            "material_occurrence_native_bbox_unavailable"
            if own_box is None else
            "material_occurrence_outside_source_floor_viewport"
            if not (
                view_bbox[0]<=own_box[0] and view_bbox[1]<=own_box[1]
                and own_box[2]<=view_bbox[2] and own_box[3]<=view_bbox[3]
            ) else
            "material_occurrence_authenticated_room_owner_unresolved"
        )
        rows.append({
            "source_occurrence_record_id":record_id if _owned_text(record_id) else None,
            "source_code":getattr(record,"code",None),
            "first_gate":reason,
            "native_bbox_candidate_only":list(own_box) if own_box else None,
            "physical_room_owner_id":None,
            "room_floor_finish_area_published":False,
        })
    return {
        "source_floor_viewport_id":expected_view,
        "producer_occurrence_count":len(records),
        "ambiguous_source_receipt_ids":sorted(k for k,v in receipt_counts.items() if v>1),
        "ambiguous_source_text_observation_ids":sorted(k for k,v in observation_counts.items() if v>1),
        "first_failure_counts":dict(sorted(Counter(row["first_gate"] for row in rows).items())),
        "source_occurrence_first_gates":rows,
        "room_finish_ownership_published":False,
        "floor_finish_quantity_published":False,
        "diagnostic_only":True,
    }
