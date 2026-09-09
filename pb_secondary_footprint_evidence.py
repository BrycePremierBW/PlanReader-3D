"""Viewport-scoped secondary-footprint width evidence (PlanReader F.23).

The legacy verandah-width parser (``pb_planreader_pdf_extractor``'s
``global_verandah_width``) matches a page-wide regex such as
``"1,800mm wide verandah"``. That works when the label and its width sit in
one sentence, but it has no notion of *viewport* — on a composite sheet it
would just as happily bind a number from an unrelated elevation or section
if the wording ever lined up, and it cannot recover a width that is spelled
out as a separate dimension-chain segment near an unrelated label instead of
inline prose.

This module adds a stricter, additive alternative: resolve a secondary
footprint component's (e.g. a verandah's) width only from a real horizontal
figured-dimension chain that shares the *same* F.07-resolved floor-plan
viewport as the component's own text label, sits adjacent to one edge of
that viewport (a secondary space runs along one side of the building, not
through its interior), and is not contradicted by any other candidate.

Explicitly out of scope, by design:
- OCR / raster evidence. A scanned plan sheet with no extractable vector
  text or vector dimension geometry yields no evidence here, and this
  module must not guess from pixels to manufacture a result.
- Vertical, section, elevation, schedule, detail or title-block dimensions.
  Only observations inside a viewport already classified
  ``DrawingViewType.FLOOR_PLAN`` are ever considered, and only horizontal
  chains are ever produced by ``extract_dimension_chains_from_page``.
- Guessing across multiple plausible candidates. Any ambiguity (the label
  in more than one viewport, more than one label instance in one viewport,
  more than one nearby chain with disagreeing values, a label not adjacent
  to any viewport edge) fails closed to ``None`` rather than picking one.

Callers combine this with the existing page-wide regex as a fallback, never
a replacement: this module can only add evidence when it is confident, it
never disproves the legacy path's own findings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pb_dimension_chain_evidence_extractor import extract_dimension_chains_from_page
from pb_dimension_graph_constraint_engine import DimensionChain, classify_chain_segments
from pb_drawing_evidence_binding import DrawingViewType
from pb_figured_dimension_evidence import calibrate_dimension_layout
from pb_viewport_segmentation import (
    SegmentedViewport,
    ViewportSegmentationStatus,
    segment_page_viewports,
)

# Generic secondary-space vocabulary. Deliberately narrow (matches the exact
# vocabulary the legacy page-wide parser already recognizes) -- this module's
# job is to make *existing* evidence safer to bind, not to invent new object
# types to search for.
_SECONDARY_SPACE_LABELS = ("verandah", "veranda")

# A secondary space runs along one side of the building: its label must sit
# within this fraction of the viewport's span from the nearest edge. This is
# a generic geometric proxy for "adjacent to the main footprint", not a
# per-document tuning constant -- it is evaluated against the viewport's own
# resolved extent, never an absolute coordinate.
_EDGE_BAND_FRACTION = 0.25


def _bbox_center(bbox: Sequence[float]) -> Tuple[float, float]:
    return (float(bbox[0]) + float(bbox[2])) / 2.0, (float(bbox[1]) + float(bbox[3])) / 2.0


def _bbox_fully_inside(inner: Sequence[float], outer: Sequence[float], *, tolerance: float = 0.0) -> bool:
    return (
        float(inner[0]) >= float(outer[0]) - tolerance
        and float(inner[1]) >= float(outer[1]) - tolerance
        and float(inner[2]) <= float(outer[2]) + tolerance
        and float(inner[3]) <= float(outer[3]) + tolerance
    )


@dataclass(frozen=True)
class SecondaryFootprintEvidence:
    """A resolved secondary-footprint width, fully traceable to its source."""

    label_text: str
    width_m: float
    view_id: str
    view_status: str
    source_page: int
    edge: str  # "top" | "bottom" | "left" | "right"
    chain_id: str
    label_bbox: Tuple[float, float, float, float]
    notes: Tuple[str, ...] = field(default_factory=tuple)


def _label_words(page: Any) -> List[Tuple[Tuple[float, float, float, float], str]]:
    out: List[Tuple[Tuple[float, float, float, float], str]] = []
    for word in page.get_text("words"):
        text = str(word[4]).strip().lower().strip(".,:;")
        if text in _SECONDARY_SPACE_LABELS:
            out.append(((float(word[0]), float(word[1]), float(word[2]), float(word[3])), text))
    return out


def _eligible_plan_viewports(
    viewports: Sequence[SegmentedViewport], *, allow_derived: bool
) -> List[SegmentedViewport]:
    allowed = {ViewportSegmentationStatus.RESOLVED.value}
    if allow_derived:
        allowed.add(ViewportSegmentationStatus.DERIVED.value)
    return [
        v
        for v in viewports
        if v.status in allowed
        and v.view_type == DrawingViewType.FLOOR_PLAN.value
        and v.bounding_box is not None
    ]


def _chain_row_center(chain: DimensionChain) -> Optional[Tuple[float, float]]:
    boxes = [o.bbox for o in chain.observations if o.bbox is not None]
    if not boxes:
        return None
    centers = [_bbox_center(b) for b in boxes]
    return (sum(c[0] for c in centers) / len(centers), sum(c[1] for c in centers) / len(centers))


def _resolve_for_viewports(
    page: Any,
    *,
    page_num: int,
    plan_viewports: Sequence[SegmentedViewport],
) -> Optional[SecondaryFootprintEvidence]:
    if not plan_viewports:
        return None

    labels = _label_words(page)
    if not labels:
        return None

    anchors: List[Tuple[Tuple[float, float, float, float], str, SegmentedViewport]] = []
    for label_bbox, label_text in labels:
        owners = [v for v in plan_viewports if _bbox_fully_inside(label_bbox, v.bounding_box)]
        if len(owners) == 1:
            anchors.append((label_bbox, label_text, owners[0]))
        # 0 owners: label is outside every trustworthy plan viewport (e.g. in
        # an elevation, or in an unresolved/ambiguous region) -- not usable.
        # >1 owners cannot happen for non-overlapping viewports, but would be
        # itself ambiguous if it ever did; excluding it here is deliberate.

    if not anchors:
        return None

    distinct_view_ids = {viewport.view_id for _bbox, _text, viewport in anchors}
    if len(distinct_view_ids) > 1:
        return None  # ambiguous: label evidenced in more than one plan viewport
    if len(anchors) > 1:
        return None  # ambiguous: more than one label instance in the same viewport

    label_bbox, label_text, viewport = anchors[0]
    assert viewport.bounding_box is not None

    chains = extract_dimension_chains_from_page(
        page,
        page_num=page_num,
        view_id=viewport.view_id,
        viewport_bbox=viewport.bounding_box,
        view_type=viewport.view_type,
    )
    if not chains:
        return None

    layout = calibrate_dimension_layout(page)
    row_tolerance = max(layout.median_word_height_pt * 3.0, layout.chain_axis_tolerance_pt)
    label_center = _bbox_center(label_bbox)

    nearby: List[DimensionChain] = []
    for chain in chains:
        center = _chain_row_center(chain)
        if center is not None and abs(center[1] - label_center[1]) <= row_tolerance:
            nearby.append(chain)
    if not nearby:
        return None  # the label exists but nothing corroborates its width

    resolved: List[Tuple[DimensionChain, float]] = []
    for chain in nearby:
        span_m = classify_chain_segments(chain).get("internal_span_m")
        if span_m is not None and span_m > 0:
            resolved.append((chain, float(span_m)))
    if not resolved:
        return None

    distinct_spans = {round(value, 3) for _chain, value in resolved}
    if len(distinct_spans) > 1:
        return None  # disagreeing candidate widths near the same label

    chain, width_m = resolved[0]

    vx0, vy0, vx1, vy1 = viewport.bounding_box
    v_width = vx1 - vx0
    v_height = vy1 - vy0
    if v_width <= 0 or v_height <= 0:
        return None

    edge_fractions: Dict[str, float] = {
        "top": (label_center[1] - vy0) / v_height,
        "bottom": (vy1 - label_center[1]) / v_height,
        "left": (label_center[0] - vx0) / v_width,
        "right": (vx1 - label_center[0]) / v_width,
    }
    edge, fraction = min(edge_fractions.items(), key=lambda item: item[1])
    if fraction > _EDGE_BAND_FRACTION:
        return None  # label sits in the plan's interior, not adjacent to an edge

    return SecondaryFootprintEvidence(
        label_text=label_text,
        width_m=round(width_m, 3),
        view_id=viewport.view_id,
        view_status=viewport.status,
        source_page=page_num,
        edge=edge,
        chain_id=chain.chain_id,
        label_bbox=label_bbox,
        notes=(
            f"resolved from viewport {viewport.view_id} "
            f"(status={viewport.status}, view_type={viewport.view_type})",
        ),
    )


def resolve_secondary_footprint_width_m(
    page: Any,
    *,
    page_num: int,
) -> Optional[SecondaryFootprintEvidence]:
    """Resolve one secondary-footprint width from same-viewport evidence.

    Tries only ``RESOLVED`` (vector-frame-backed) floor-plan viewports first.
    Only if that finds no usable anchor does it retry against ``DERIVED``
    (title-partition) floor-plan viewports too -- mirroring
    ``pb_viewport_dimension_binding``'s own conservative-by-default,
    opt-in-wider-second-pass pattern. A result anchored to a ``DERIVED``
    viewport is real evidence, just lower authority than one anchored to a
    ``RESOLVED`` one; the returned ``view_status`` records which applied.

    Returns ``None`` on any ambiguity or missing evidence -- callers must
    treat that as "no additional evidence found", not as an error, and must
    keep their own existing (weaker) evidence path as a fallback rather than
    have this function's absence of a result erase it.
    """
    viewports = segment_page_viewports(page, page_number=page_num)

    strict = _resolve_for_viewports(
        page,
        page_num=page_num,
        plan_viewports=_eligible_plan_viewports(viewports, allow_derived=False),
    )
    if strict is not None:
        return strict

    return _resolve_for_viewports(
        page,
        page_num=page_num,
        plan_viewports=_eligible_plan_viewports(viewports, allow_derived=True),
    )
