"""Adapt HostedOpeningSpan into anonymous F.9 OpeningInstances.

This module does not mint W1/W2/D1 identities, does not invent opening
height or scale, and does not claim a host wall. A hosted span becomes an
OpeningInstance whose opening_id is a deterministic span_id. height_m is
always None and bound_wall_id is None unless a caller supplies an
independently evidenced wall id. The adapter never defaults that id to
perimeter_walling.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from pb_hosted_opening_geometry import HostedOpeningSpan
from pb_opening_deduction_pipeline import OpeningInstance
from pb_opening_tag_normalization import normalize_opening_tag

# A swing/leaf arc may classify an already-hosted gap. It is not enough
# on its own to create an opening. These flags are the hosted-gap contract.
_HOSTED_GAP_AUTHORITY_FLAGS = frozenset(
    {
        "host_wall_band",
        "aligned_two_face_gap",
        "jamb_boundaries_confirmed",
    }
)


def hosted_gap_authority_present(span: HostedOpeningSpan) -> bool:
    """True only when the span carries hosted-gap evidence, not arc-alone."""
    return bool(set(span.evidence_flags) & _HOSTED_GAP_AUTHORITY_FLAGS)


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
