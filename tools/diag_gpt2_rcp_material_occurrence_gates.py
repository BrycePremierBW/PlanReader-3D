"""Read-only source-authenticated RCP material occurrence first-failure summary.

Only the production SourceMaterialSemanticAuthority may authenticate a
material occurrence. This helper cannot turn a material definition or
untrusted native code into an occurrence, room-owned finish or quantity.
"""
from __future__ import annotations
import math
from typing import Any

from pb_viewport_segmentation import is_authoritative_derived_viewport

def scoped_rcp_material_occurrence_gate(viewport: Any, result: Any) -> dict[str,Any]:
    view_id=str(getattr(viewport,"view_id","") or "")
    view_type_field=getattr(viewport,"view_type","")
    kind=str(getattr(view_type_field,"value",view_type_field) or "")
    status=str(getattr(viewport,"status","") or "")
    bbox=getattr(viewport,"bounding_box",None)
    scope_status=str(getattr(result,"status",""))
    # EvidenceResolutionStatus is an Enum: str() alone produces
    # "EvidenceResolutionStatus.CORROBORATED", not its value.
    scope_token=str(getattr(getattr(result,"status",None),"value",getattr(result,"status","")) or "")
    reasons=list(getattr(result,"reason_codes",()) or ())
    complete=getattr(result,"scope_complete",False) is True
    records=tuple(getattr(result,"records",()) or ())
    # Diagnostic-only source viewport shape classification; production
    # source ownership is never granted by this diagnostic helper.
    view_token=str(getattr(getattr(viewport,"status",None),"value",getattr(viewport,"status","")) or "")
    try:
        native_bbox=tuple(float(value) for value in bbox)
        bbox_valid=(
            len(native_bbox)==4
            and all(math.isfinite(value) for value in native_bbox)
            and native_bbox[0]<native_bbox[2]
            and native_bbox[1]<native_bbox[3]
        )
    except (TypeError, ValueError, OverflowError):
        bbox_valid=False
    derived_authenticated = (
        view_token == "derived" and is_authoritative_derived_viewport(viewport)
    )
    supported=(
        kind=="reflected_ceiling_plan" and bbox_valid
        and (view_token=="resolved" or derived_authenticated)
    )
    # The occurrence producer authenticates ownership to an exact source
    # viewport. A valid occurrence on a *different* RCP cannot authenticate
    # this viewport (e.g. page9 proposed vs original drawing).
    owned_records=bool(records) and bool(view_id) and all(
        str(getattr(record,"viewport_id","") or "")==view_id
        and bool(str(getattr(record,"record_id","") or "").strip())
        for record in records
    )
    # Where the viewport producer exposes its exact source page, material
    # observations from another sheet cannot become this RCP's occurrences.
    material_ids = tuple(
        str(getattr(record, "record_id", "") or "").strip()
        for record in records
    )
    record_identities_unique = (
        bool(material_ids) and len(material_ids) == len(set(material_ids))
        and all(material_ids)
    )
    page_number = getattr(viewport, "page_number", None)
    record_pages_match = page_number is None or all(
        str(getattr(record, "page_id", "") or "") == str(page_number)
        for record in records
    )
    if kind!="reflected_ceiling_plan":
        gate="not_an_rcp_viewport"
    elif not supported:
        gate="source_rcp_viewport_unresolved"
    elif not complete:
        gate="producer_source_occurrence_universe_incomplete"
    elif scope_token!="corroborated":
        # A CANDIDATE, CONFLICT, or ABSTAINED producer may not be described
        # as having authenticated occurrences, regardless of stale rows.
        gate="producer_source_occurrence_scope_not_corroborated"
    elif not records:
        gate="producer_no_authenticated_occurrences"
    elif not owned_records:
        gate="producer_occurrence_viewport_lineage_mismatch"
    elif not record_pages_match:
        gate="producer_occurrence_source_page_mismatch"
    elif not record_identities_unique:
        gate="producer_occurrence_identity_ambiguous"
    else:
        gate="producer_authenticated_occurrences_require_room_owner_before_quantity"
    return {
        "source_viewport_id":view_id,
        "source_view_type":kind,
        "source_view_status":status,
        "source_view_native_bbox_pdf_pts":bbox,
        "producer_occurrence_scope_status":scope_status,
        "producer_scope_complete":complete,
        "producer_reason_codes":reasons,
        "producer_occurrence_record_ids":[str(getattr(r,"record_id","")) for r in records],
        "producer_occurrence_codes":[str(getattr(r,"code","")) for r in records],
        "producer_authenticated_record_ids":[
            str(getattr(r,"record_id",""))
            for r in records
        ] if supported and complete and scope_token=="corroborated" and owned_records and record_pages_match and record_identities_unique else [],
        "first_unclosed_gate":gate,
        "new_room_material_ownership_claim":False,
        "new_metric_quantity_claim":False,
    }
