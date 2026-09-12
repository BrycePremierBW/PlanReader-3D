"""Adapt Claude's HostedOpeningSpan into anonymous F.9 OpeningInstances.

This module does not mint W1/W2/D1 identities, does not invent opening
height, and does not bind WxH callouts. A hosted span becomes an
OpeningInstance whose opening_id is a deterministic span_id. height_m is
always None, so the existing deduction pipeline must fail closed with
UNRESOLVED_MISSING_DIMENSIONS and deduct 0 m².
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from pb_hosted_opening_geometry import HostedOpeningSpan
from pb_opening_deduction_pipeline import OpeningInstance
from pb_opening_tag_normalization import normalize_opening_tag

_DEFAULT_BOUND_WALL_ID = "perimeter_walling"


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
    bound_wall_id: str = _DEFAULT_BOUND_WALL_ID,
) -> OpeningInstance:
    """Convert one HostedOpeningSpan into an anonymous height-less instance."""
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
    bound_wall_id: str = _DEFAULT_BOUND_WALL_ID,
) -> List[OpeningInstance]:
    return [
        hosted_span_to_opening_instance(span, bound_wall_id=bound_wall_id)
        for span in spans
    ]


def hosted_opening_instances_from_document(
    doc,
    pages: Sequence[int],
    *,
    bound_wall_id: str = _DEFAULT_BOUND_WALL_ID,
    scale_authority: Optional[float] = None,
) -> List[OpeningInstance]:
    """Detect hosted spans on ``pages`` and adapt them. Never invents scale."""
    from pb_hosted_opening_geometry import resolve_hosted_opening_spans

    spans: List[HostedOpeningSpan] = []
    for page_index in pages:
        if page_index < 0 or page_index >= len(doc):
            continue
        evidence = resolve_hosted_opening_spans(
            doc[page_index],
            scale_authority=scale_authority,
        )
        spans.extend(evidence.openings)
    return hosted_spans_to_opening_instances(spans, bound_wall_id=bound_wall_id)
