"""Adapt HostedOpeningSpan into anonymous F.9 OpeningInstances.

This module does not mint W1/W2/D1 identities, does not invent opening
height or scale, and does not claim a host wall. A hosted span becomes an
OpeningInstance whose opening_id is a deterministic span_id. height_m is
always None and bound_wall_id is None unless a caller supplies an
independently evidenced wall id. The adapter never defaults that id to
perimeter_walling.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from pb_hosted_opening_geometry import HostedOpeningSpan
from pb_opening_deduction_pipeline import OpeningInstance
from pb_opening_tag_normalization import normalize_opening_tag

SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY = "BLOCKED_ON_VIEWPORT_AUTHORITY"

def hosted_gap_authority_present(span: HostedOpeningSpan) -> bool:
    """True only for Claude's exact aligned-channel or hatch-channel contract.

    A swing arc may corroborate a real hatch-material gap. It can never
    create hosted-opening authority by itself.
    """
    flags = set(span.evidence_flags)
    aligned_authority = (
        "host_wall_band" in flags
        and "aligned_two_face_gap" in flags
        and "jamb_boundaries_confirmed" in flags
    )
    hatch_authority = (
        "host_wall_band" in flags
        and "diagonal_hatch_tick_gap" in flags
        and (
            "jamb_boundaries_confirmed" in flags
            or "jamb_anchored_door_swing" in flags
        )
    )
    return aligned_authority or hatch_authority


def hosted_opening_span_id(span: HostedOpeningSpan) -> str:
    """Stable anonymous id from page + host geometry. Never a W/D tag."""
    x0, y0 = span.jamb_start
    x1, y1 = span.jamb_end
    span_id = (
        f"hosted-span-p{int(span.page)}-"
        f"{span.host_orientation_deg:.0f}-"
        f"{x0:.2f}-{y0:.2f}-{x1:.2f}-{y1:.2f}"
    )
    if normalize_opening_tag(span_id) is not None:
        span_id = f"anon-{span_id}"
    return span_id


def _evidenced_width_m(span: HostedOpeningSpan) -> Optional[float]:
    width_m = span.width_m
    if width_m is None or width_m <= 0.0:
        return None
    return round(float(width_m), 4)


def _bounding_box(span: HostedOpeningSpan) -> List[float]:
    x0, y0 = span.jamb_start
    x1, y1 = span.jamb_end
    return [
        round(min(x0, x1), 4),
        round(min(y0, y1), 4),
        round(max(x0, x1), 4),
        round(max(y0, y1), 4),
    ]


def hosted_span_to_opening_instance(
    span: HostedOpeningSpan,
    *,
    bound_wall_id: Optional[str] = None,
) -> Optional[OpeningInstance]:
    """Convert one HostedOpeningSpan into an anonymous height-less instance.

    Returns None when the span is swing-arc evidence alone.
    """
    if not hosted_gap_authority_present(span):
        return None
    width_m = _evidenced_width_m(span)
    flags = ",".join(span.evidence_flags)
    notes = (
        "hosted_opening_span"
        f" page={span.page}"
        f" orientation_deg={span.host_orientation_deg}"
        f" span_pt={span.span_pt}"
        f" width_m={width_m}"
        f" wall_thickness_pt={span.wall_thickness_pt}"
        f" subtype={span.subtype}"
        f" flags={flags}"
        f" reason={span.reason}"
    )
    return OpeningInstance(
        opening_id=hosted_opening_span_id(span),
        trade_type="opening",
        width_m=width_m,
        height_m=None,
        quantity=1.0,
        bound_wall_id=bound_wall_id,
        source_page=span.page,
        bounding_box=_bounding_box(span),
        notes=notes,
    )


def hosted_spans_to_opening_instances(
    spans: Sequence[HostedOpeningSpan] | Iterable[HostedOpeningSpan],
    *,
    bound_wall_id: Optional[str] = None,
) -> List[OpeningInstance]:
    instances: List[OpeningInstance] = []
    for span in spans:
        inst = hosted_span_to_opening_instance(span, bound_wall_id=bound_wall_id)
        if inst is not None:
            instances.append(inst)
    return instances


def empty_hosted_opening_shadow(
    *,
    reason: str,
    viewport_census: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": "abstained", "reason": reason, "evidence": []}
    if viewport_census is not None:
        payload["viewport_census"] = viewport_census
    return payload


def summarize_viewport_authority(viewports: Sequence[Any], *, page_number: int) -> Dict[str, Any]:
    """Diagnostic census. Does not promote DERIVED/AMBIGUOUS into authority."""
    from pb_drawing_evidence_binding import DrawingViewType
    from pb_viewport_segmentation import ViewportSegmentationStatus

    status_counts: Dict[str, int] = {}
    view_type_counts: Dict[str, int] = {}
    rejected_floor_plans: List[Dict[str, Any]] = []
    authoritative = 0
    for viewport in viewports:
        status_counts[viewport.status] = status_counts.get(viewport.status, 0) + 1
        view_type_counts[viewport.view_type] = view_type_counts.get(viewport.view_type, 0) + 1
        is_floor_plan = viewport.view_type == DrawingViewType.FLOOR_PLAN.value
        is_resolved = viewport.status == ViewportSegmentationStatus.RESOLVED.value
        has_bbox = viewport.bounding_box is not None
        if is_floor_plan and is_resolved and has_bbox:
            authoritative += 1
            continue
        if is_floor_plan:
            if not is_resolved:
                reject_reason = "floor_plan_not_resolved"
            else:
                reject_reason = "floor_plan_missing_bbox"
            rejected_floor_plans.append(
                {
                    "page": page_number,
                    "status": viewport.status,
                    "has_bbox": has_bbox,
                    "label": viewport.label,
                    "reject_reason": reject_reason,
                }
            )
    return {
        "authoritative_floor_plan_count": authoritative,
        "status_counts": status_counts,
        "view_type_counts": view_type_counts,
        "rejected_floor_plans": rejected_floor_plans,
    }


def collect_viewport_authority_census(doc: Any, pages: Sequence[int]) -> Dict[str, Any]:
    """One-pass F.07 census for why hosted shadow stayed blocked."""
    from pb_viewport_segmentation import segment_page_viewports

    merged = {
        "authoritative_floor_plan_count": 0,
        "status_counts": {},
        "view_type_counts": {},
        "rejected_floor_plans": [],
    }
    for page_index in pages:
        if page_index < 0 or page_index >= len(doc):
            continue
        page_number = page_index + 1
        summary = summarize_viewport_authority(
            segment_page_viewports(doc[page_index], page_number=page_number),
            page_number=page_number,
        )
        merged["authoritative_floor_plan_count"] += summary["authoritative_floor_plan_count"]
        for key, value in summary["status_counts"].items():
            merged["status_counts"][key] = merged["status_counts"].get(key, 0) + value
        for key, value in summary["view_type_counts"].items():
            merged["view_type_counts"][key] = merged["view_type_counts"].get(key, 0) + value
        merged["rejected_floor_plans"].extend(summary["rejected_floor_plans"])
    merged["rejected_floor_plans"] = merged["rejected_floor_plans"][:24]
    return merged


def hosted_span_to_shadow_record(span: HostedOpeningSpan) -> Optional[Dict[str, Any]]:
    """Serialize one span for diagnostics. Arc-alone spans are dropped."""
    if not hosted_gap_authority_present(span):
        return None
    return {
        "span_id": hosted_opening_span_id(span),
        "page": span.page,
        "orientation": span.host_orientation_deg,
        "jamb_start": [span.jamb_start[0], span.jamb_start[1]],
        "jamb_end": [span.jamb_end[0], span.jamb_end[1]],
        "span_pt": span.span_pt,
        "width_m": _evidenced_width_m(span),
        "wall_thickness_pt": span.wall_thickness_pt,
        "subtype": span.subtype,
        "evidence_flags": list(span.evidence_flags),
        "reason": span.reason,
    }


def authoritative_floor_plan_viewports(page: Any, *, page_number: int) -> List[Any]:
    """Reuse F.07 RESOLVED floor-plan frames only. Never guess from page class."""
    from pb_drawing_evidence_binding import DrawingViewType
    from pb_viewport_segmentation import (
        ViewportSegmentationStatus,
        segment_page_viewports,
    )

    return [
        viewport
        for viewport in segment_page_viewports(page, page_number=page_number)
        if viewport.status == ViewportSegmentationStatus.RESOLVED.value
        and viewport.view_type == DrawingViewType.FLOOR_PLAN.value
        and viewport.bounding_box is not None
    ]


def collect_hosted_opening_shadow_evidence(
    doc: Any,
    pages: Sequence[int],
) -> Dict[str, Any]:
    """Detect hosted spans only inside authoritative floor-plan viewports.

    Never invents scale, never feeds F.9, never mints W/D identities.
    """
    from pb_hosted_opening_geometry import resolve_hosted_opening_spans

    evidence: List[Dict[str, Any]] = []
    had_viewport = False
    for page_index in pages:
        if page_index < 0 or page_index >= len(doc):
            continue
        page = doc[page_index]
        viewports = authoritative_floor_plan_viewports(page, page_number=page_index + 1)
        if not viewports:
            continue
        had_viewport = True
        for viewport in viewports:
            bbox = tuple(float(value) for value in viewport.bounding_box)
            result = resolve_hosted_opening_spans(
                page,
                viewport_bbox=bbox,
                scale_authority=None,
            )
            for span in result.openings:
                record = hosted_span_to_shadow_record(span)
                if record is not None:
                    evidence.append(record)
    if not had_viewport:
        return empty_hosted_opening_shadow(
            reason=SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY,
            viewport_census=collect_viewport_authority_census(doc, pages),
        )
    if not evidence:
        return empty_hosted_opening_shadow(
            reason="no_hosted_opening_span_in_authoritative_floor_plan_viewport"
        )
    return {
        "status": "found",
        "reason": f"{len(evidence)} hosted opening span(s) found",
        "evidence": evidence,
    }
