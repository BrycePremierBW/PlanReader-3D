"""Spatial dimension-chain reconstruction from real PDF evidence (F.15 / F.13 / F.07).

F.13's constraint graph operates on ``DimensionObservation`` records. The
original F.15 wiring reconstructed horizontal chains from native PDF word
positions only. It remains the conservative wall-thickness entry point, but
now consumes the typed/raw F.13 evidence layer so that:

- drafting identities such as room/grid/revision/sheet numbers are rejected by
  grammar/context rather than numeric value blacklists;
- native vector dimension/witness lines can enrich observations with anchors;
- vector-anchor ambiguity fails closed for *anchor-dependent geometry* without
  destructively deleting an otherwise valid printed dimension constraint;
- F.15's proven horizontal-row behavior remains compatible when F.07 cannot
  resolve trustworthy viewport ownership;
- when F.07 *does* resolve viewports, production page-wide callers consume only
  resolved floor-plan regions for wall-thickness corroboration. Elevation and
  section dimensions cannot leak into the floor-plan wall-thickness path.

This distinction matters: a clearly printed dimension may remain valid textual
constraint evidence even when dense CAD linework prevents a unique association
to one vector dimension line. Losing that text constraint would make a lower-
authority graphical association overwrite stronger documented evidence.

The richer all-orientation evidence API lives in ``pb_figured_dimension_evidence``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from pb_dimension_graph_constraint_engine import (
    DimensionChain,
    DimensionObservation,
    DimensionOrientation,
    _PLAUSIBLE_DIMENSION_RANGE_MM,
    classify_chain_segments,
)
from pb_drawing_evidence_binding import DrawingViewType
from pb_figured_dimension_evidence import (
    BindingStatus,
    apply_anchor_binding,
    bind_observation_to_vector_geometry,
    calibrate_dimension_layout,
    classify_dimension_token,
    extract_native_dimension_observations,
    extract_vector_segments,
)


def _parse_dimension_word_mm(word: str, *, preceding_context: str = "") -> Optional[float]:
    """Parse one typed dimension token to millimetres for legacy F.15 callers.

    The typed grammar handles identity/noise rejection. This adapter preserves
    F.15's broad plausible-building-dimension bound before a value may enter the
    wall-thickness corroboration path.
    """
    token = classify_dimension_token(word, preceding_context=preceding_context)
    if not token.is_linear_dimension or token.value is None or token.unit is None:
        return None
    if token.unit == "mm":
        value_mm = token.value
    elif token.unit == "m":
        value_mm = token.value * 1000.0
    elif token.unit == "in":
        value_mm = token.value * 25.4
    else:
        return None
    lo, hi = _PLAUSIBLE_DIMENSION_RANGE_MM
    return value_mm if lo <= value_mm <= hi else None


def _bbox_fully_inside(
    inner: Sequence[float],
    outer: Sequence[float],
    *,
    tolerance: float = 0.0,
) -> bool:
    """Require complete containment for authority-sensitive text evidence."""
    return (
        float(inner[0]) >= float(outer[0]) - tolerance
        and float(inner[1]) >= float(outer[1]) - tolerance
        and float(inner[2]) <= float(outer[2]) + tolerance
        and float(inner[3]) <= float(outer[3]) + tolerance
    )


def _point_inside(point: Sequence[float], bbox: Sequence[float], *, tolerance: float = 0.0) -> bool:
    return (
        float(bbox[0]) - tolerance <= float(point[0]) <= float(bbox[2]) + tolerance
        and float(bbox[1]) - tolerance <= float(point[1]) <= float(bbox[3]) + tolerance
    )


def _extract_horizontal_chains_core(
    page: Any,
    *,
    page_num: int,
    view_id: str,
    view_type: str,
    y_tolerance_pt: float,
    viewport_bbox: Optional[Sequence[float]] = None,
) -> List[DimensionChain]:
    """F.15-compatible horizontal extraction, optionally bounded to one viewport."""
    native = extract_native_dimension_observations(
        page,
        page_num=page_num,
        view_id=view_id,
        view_type=view_type,
    )
    layout = calibrate_dimension_layout(page)
    segments = extract_vector_segments(page, page_num=page_num, view_id=view_id)

    if viewport_bbox is not None:
        # Authority-sensitive viewport ownership is strict: a text bbox must be
        # wholly inside the viewport, and a vector segment must have both
        # endpoints inside. Midpoint-only ownership would allow a long line
        # crossing another view to contaminate anchor binding.
        native = [
            observation
            for observation in native
            if observation.bbox is not None
            and _bbox_fully_inside(observation.bbox, viewport_bbox)
        ]
        segments = [
            segment
            for segment in segments
            if _point_inside(segment.start, viewport_bbox)
            and _point_inside(segment.end, viewport_bbox)
        ]

    usable: List[DimensionObservation] = []
    for observation in native:
        value_mm = observation.value_m * 1000.0
        lo, hi = _PLAUSIBLE_DIMENSION_RANGE_MM
        if not (lo <= value_mm <= hi):
            continue

        binding = bind_observation_to_vector_geometry(observation, segments, layout)

        if binding.status == BindingStatus.WITNESS_BOUND.value:
            # A complete two-witness association is strong enough to establish
            # axis orientation. Preserve horizontal enrichment; keep confirmed
            # vertical evidence out of this legacy horizontal-only consumer.
            enriched = apply_anchor_binding(observation, binding)
            if enriched.orientation == DimensionOrientation.VERTICAL.value:
                continue
            if enriched.orientation == DimensionOrientation.UNKNOWN.value:
                enriched.orientation = DimensionOrientation.HORIZONTAL.value
            usable.append(enriched)
            continue

        # LINE_BOUND/PARTIAL_WITNESS have no resolved endpoints in the current
        # binder, so they cannot safely override the text-row orientation.
        # AMBIGUOUS/UNSUPPORTED are explicitly non-authoritative for anchoring.
        # In all four cases preserve the printed figured dimension as text-only
        # constraint evidence rather than destructively suppressing it.
        text_observation = DimensionObservation(
            dimension_id=observation.dimension_id,
            source_page=observation.source_page,
            sheet=observation.sheet,
            view_id=observation.view_id,
            view_type=observation.view_type,
            bbox=observation.bbox,
            raw_text=observation.raw_text,
            value=observation.value,
            unit=observation.unit,
            orientation=DimensionOrientation.HORIZONTAL.value,
            endpoints=None,
            witness_targets=(),
            candidate_geometry_ids=observation.candidate_geometry_ids,
            bound_geometry_id=None,
            authority=observation.authority,
            confidence=observation.confidence,
            conflict_state=observation.conflict_state,
            extraction_method=observation.extraction_method,
        )
        usable.append(text_observation)

    rows: Dict[float, List[DimensionObservation]] = {}
    for observation in usable:
        if observation.bbox is None:
            continue
        key = round(observation.bbox[1] / y_tolerance_pt) * y_tolerance_pt
        rows.setdefault(key, []).append(observation)

    chains: List[DimensionChain] = []
    for idx, y_key in enumerate(sorted(rows)):
        row = sorted(
            rows[y_key],
            key=lambda observation: observation.bbox[0] if observation.bbox else 0.0,
        )
        chains.append(
            DimensionChain(
                chain_id=f"chain_p{page_num}_{view_id or 'page'}_{idx}",
                view_id=view_id,
                source_page=page_num,
                orientation=DimensionOrientation.HORIZONTAL.value,
                observations=row,
            )
        )
    return chains


def extract_dimension_chains_from_page(
    page: Any,
    *,
    page_num: int,
    view_id: str = "",
    y_tolerance_pt: float = 3.0,
    viewport_bbox: Optional[Sequence[float]] = None,
    view_type: str = DrawingViewType.UNKNOWN.value,
) -> List[DimensionChain]:
    """Reconstruct conservative horizontal dimension chains from one page.

    Direct/legacy callers remain backwards-compatible. Production extraction
    already supplies ``view_id='page_N'``; that explicit page-wide provenance
    marker now activates F.07 viewport ownership when trustworthy RESOLVED
    regions exist:

    * no RESOLVED viewport -> preserve the proven legacy page-wide path;
    * one or more RESOLVED floor-plan viewports -> extract independently inside
      those floor-plan regions only;
    * RESOLVED viewports exist but none is a floor plan -> return no wall-
      thickness chains rather than borrowing elevation/section dimensions.

    ``viewport_bbox`` is an explicit lower-level escape hatch used by tests and
    future scoped consumers. It never invokes segmentation recursively.
    """
    if viewport_bbox is not None or not view_id.startswith("page_"):
        return _extract_horizontal_chains_core(
            page,
            page_num=page_num,
            view_id=view_id,
            view_type=view_type,
            y_tolerance_pt=y_tolerance_pt,
            viewport_bbox=viewport_bbox,
        )

    # F.07 is imported lazily so the long-standing F.15 helper remains usable
    # in isolation and there is no module-level dependency cycle.
    from pb_viewport_segmentation import (
        ViewportSegmentationStatus,
        segment_page_viewports,
    )

    viewports = segment_page_viewports(page, page_number=page_num)
    resolved = [
        viewport
        for viewport in viewports
        if viewport.status == ViewportSegmentationStatus.RESOLVED.value
        and viewport.bounding_box is not None
    ]

    if not resolved:
        return _extract_horizontal_chains_core(
            page,
            page_num=page_num,
            view_id=view_id,
            view_type=view_type,
            y_tolerance_pt=y_tolerance_pt,
        )

    plan_viewports = [
        viewport
        for viewport in resolved
        if viewport.view_type == DrawingViewType.FLOOR_PLAN.value
    ]
    if not plan_viewports:
        # Once F.07 has strong evidence that the available framed views are not
        # floor plans, the wall-thickness consumer must not silently fall back
        # to page-wide elevation/section dimensions.
        return []

    chains: List[DimensionChain] = []
    for viewport in plan_viewports:
        chains.extend(
            _extract_horizontal_chains_core(
                page,
                page_num=page_num,
                view_id=viewport.view_id,
                view_type=viewport.view_type,
                y_tolerance_pt=y_tolerance_pt,
                viewport_bbox=viewport.bounding_box,
            )
        )
    return chains


def _is_degenerate_repeat(chain: DimensionChain) -> bool:
    """Reject repeated equal-value detail/spacing rows as wall brackets."""
    values = {round(o.value_m, 4) for o in chain.observations}
    return len(values) <= 1


def resolve_corroborated_wall_thickness_m(
    chains: Sequence[DimensionChain],
    *,
    agreement_tolerance_m: float = 0.02,
) -> Optional[float]:
    """Resolve wall thickness only when independent chain candidates agree."""
    candidates: List[float] = []
    for chain in chains:
        if _is_degenerate_repeat(chain):
            continue
        thickness = classify_chain_segments(chain).get("wall_thickness_m")
        if thickness is None:
            continue
        first_v, last_v = thickness
        if abs(first_v - last_v) <= agreement_tolerance_m:
            candidates.append((first_v + last_v) / 2.0)
        else:
            candidates.append(first_v)
            candidates.append(last_v)

    if len(candidates) < 2:
        return None

    best_cluster: List[float] = []
    for candidate in candidates:
        cluster = [x for x in candidates if abs(x - candidate) <= agreement_tolerance_m]
        if len(cluster) > len(best_cluster):
            best_cluster = cluster

    if len(best_cluster) < 2:
        return None
    return round(sum(best_cluster) / len(best_cluster), 4)
