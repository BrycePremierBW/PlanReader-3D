"""Spatial dimension-chain reconstruction from real PDF evidence (F.15 / F.13).

F.13's constraint graph operates on ``DimensionObservation`` records. The
original F.15 wiring reconstructed horizontal chains from native PDF word
positions only. It remains the conservative wall-thickness entry point, but
now consumes the typed/raw F.13 evidence layer so that:

- drafting identities such as room/grid/revision/sheet numbers are rejected by
  grammar/context rather than numeric value blacklists;
- native vector dimension/witness lines can enrich observations with anchors;
- vector-anchor ambiguity fails closed for *anchor-dependent geometry* without
  destructively deleting an otherwise valid printed dimension constraint;
- F.15's proven horizontal-row behavior remains compatible until F.07 can
  provide trustworthy viewport segmentation for unscoped vertical chains.

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


def extract_dimension_chains_from_page(
    page: Any,
    *,
    page_num: int,
    view_id: str = "",
    y_tolerance_pt: float = 3.0,
) -> List[DimensionChain]:
    """Reconstruct conservative horizontal dimension chains from one page.

    This function remains deliberately horizontal-only. F.13 can extract and
    bind vertical observations, but consuming confidently vertical chains
    without viewport ownership would let an elevation/section dimension leak
    into a floor-plan wall-thickness decision. F.07 viewport segmentation is
    the dependency that can safely remove that restriction later.

    Anchor binding is *additive*. A full witness-bound vertical observation is
    excluded from this horizontal-only consumer. An ambiguous, unsupported, or
    partial graphical association does not erase the documented text value; the
    original observation remains eligible for F.15's row-based corroboration.
    The rich F.13 bundle still exposes the anchor ambiguity separately.

    ``y_tolerance_pt`` is retained for backwards compatibility with F.15's
    existing callers/tests. Vector line/witness search tolerances are derived
    from the current page's typography by ``calibrate_dimension_layout``.
    """
    native = extract_native_dimension_observations(
        page,
        page_num=page_num,
        view_id=view_id,
    )
    layout = calibrate_dimension_layout(page)
    segments = extract_vector_segments(page, page_num=page_num, view_id=view_id)

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
                chain_id=f"chain_p{page_num}_{idx}",
                view_id=view_id,
                source_page=page_num,
                orientation=DimensionOrientation.HORIZONTAL.value,
                observations=row,
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
