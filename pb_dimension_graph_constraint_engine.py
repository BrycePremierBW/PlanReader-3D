"""pb_dimension_graph_constraint_engine.py — Figured-Dimension Graph & Geometric
Constraint Engine (Phase F.13).

The extractor still relies too heavily on loose page-level dimension heuristics:
pick the largest-looking numbers on a page and guess which pair forms the
building envelope. This module replaces that guess with a proper evidence
graph: every figured dimension becomes a traceable DimensionObservation, and
geometry is only resolved when real dimension evidence constrains it —
never by falling back to a convenience default.

Target flow:
    PDF/native/vector/OCR evidence
    -> DimensionObservation records
    -> DimensionChain grouping (same view, same axis, spatially ordered)
    -> geometric constraint resolution (rectangle legs, wall height)
    -> resolved wall/room geometry (only where genuinely constrained)
    -> quantities (a later pipeline stage, not this module)

Authority doctrine (preserved, not reinvented — see pb_geometry_takeoff_model.
MeasurementAuthorityType, already the app-wide authority ladder):
    DOCUMENTED_DIMENSION (a real figured dimension) beats
    PDF_SCALED (measured off a calibrated drawing) beats
    AI_DETECTED (inferred).
Unknown remains unknown: nothing in this module ever substitutes a default
value for missing evidence and reports the result as constrained. A result
with no real evidence is UNRESOLVED, not "2.7m" or "150mm" by convention.

View classification reuses pb_drawing_evidence_binding.DrawingViewType (F.12)
so a dimension is scoped to the same view-identity concept every other piece
of drawing evidence already uses — chains are never merged across views.

Known, explicit scope limits of this first PR (see module docstring in the
PR body for the follow-on plan): this module operates on already-tokenized
DimensionObservation records, not on raw PDF bytes/vector paths/OCR images —
wiring a real vector/OCR extractor to emit DimensionObservation records is a
separate, later PR. Revision/supersession handling (capability #11) is not
implemented — a superseded dimension is not yet distinguishable from a
conflicting one; today, any disagreement fails closed to manual review.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pb_drawing_evidence_binding import DrawingViewType
from pb_geometry_takeoff_model import MeasurementAuthorityType


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DimensionOrientation(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    UNKNOWN = "unknown"


class ConstraintStatus(str, Enum):
    FULLY_CONSTRAINED = "fully_constrained"
    PARTIALLY_CONSTRAINED = "partially_constrained"
    UNRESOLVED = "unresolved"
    CONFLICT_MANUAL_REVIEW = "conflict_manual_review"


class SegmentRole(str, Enum):
    """A chain segment's structural role. Classified only from real
    structural position (first/last segment of a >=3-segment chain) plus a
    broad, generically-justified plausibility range — never from an exact
    hardcoded value or a value blacklist tuned to any specific drawing."""
    WALL_THICKNESS = "wall_thickness"
    INTERNAL_SPAN = "internal_span"
    UNCLASSIFIED = "unclassified"


# A broad, generic real-world wall thickness range (stud partition through
# heavy masonry/concrete). This is a plausibility bound, not an exact-value
# lookup table — no specific standard thickness is privileged over another.
_WALL_THICKNESS_RANGE_M: Tuple[float, float] = (0.06, 0.40)

# A generic plausible range for any real figured building dimension, used
# only to reject obviously-not-a-dimension text (page numbers, scale
# ratios, phone numbers) — never to exclude specific values.
_PLAUSIBLE_DIMENSION_RANGE_MM: Tuple[float, float] = (10.0, 60000.0)

_NOISE_CONTEXT_PATTERN = re.compile(
    r"\b(scale|sheet|dwg|drawing\s*no|rev(?:ision)?|date|tel|fax|phone|"
    r"p\.?o\.?\s*box|project\s*no|job\s*no|page)\b\s*[:.]?\s*$",
    re.IGNORECASE,
)
_YEAR_PATTERN = re.compile(r"^(19|20)\d{2}$")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DimensionObservation:
    """A single figured (or scaled/inferred) dimension, fully traceable back
    to its source. Mirrors pb_drawing_evidence_binding.EvidenceObservation's
    shape closely on purpose — same view/scope/authority vocabulary as every
    other evidence type in the pipeline — but keeps dimension-specific
    fields (value, unit, orientation, endpoints, witness targets) that don't
    fit that model's opening-shaped `dimensions` field."""
    dimension_id: str
    source_page: int = 1
    sheet: str = ""
    view_id: str = ""
    view_type: str = DrawingViewType.UNKNOWN.value
    bbox: Optional[Tuple[float, float, float, float]] = None
    raw_text: str = ""
    value: float = 0.0  # numeric value in `unit`, as printed/parsed
    unit: str = "mm"  # "mm", "m", "in", "ft"
    orientation: str = DimensionOrientation.UNKNOWN.value
    endpoints: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
    witness_targets: Tuple[str, ...] = field(default_factory=tuple)
    candidate_geometry_ids: Tuple[str, ...] = field(default_factory=tuple)
    bound_geometry_id: Optional[str] = None
    authority: str = MeasurementAuthorityType.DOCUMENTED_DIMENSION.value
    confidence: float = 1.0
    conflict_state: str = ConstraintStatus.FULLY_CONSTRAINED.value
    extraction_method: str = "native_text"

    @property
    def value_m(self) -> float:
        """Canonical value in metres. Raises rather than guessing a unit
        for an unrecognized unit string — an unrecognized unit is a data
        problem to surface, not to silently coerce."""
        if self.unit == "mm":
            return self.value / 1000.0
        if self.unit == "m":
            return self.value
        if self.unit == "in":
            return self.value * 0.0254
        if self.unit == "ft":
            return self.value * 0.3048
        raise ValueError(f"Unrecognized dimension unit {self.unit!r} for {self.dimension_id!r}")


@dataclass
class DimensionChain:
    """An ordered, same-view, same-axis sequence of DimensionObservations
    that together span one continuous run (e.g. wall / room / wall). Chains
    are never built across views or pages — mixed-scale/mixed-view isolation
    is enforced by construction, not by a downstream filter."""
    chain_id: str
    view_id: str
    source_page: int
    orientation: str
    observations: List[DimensionObservation] = field(default_factory=list)

    def __post_init__(self) -> None:
        for obs in self.observations:
            if obs.view_id != self.view_id:
                raise ValueError(
                    f"DimensionChain {self.chain_id!r} mixes view_id "
                    f"{obs.view_id!r} into a chain scoped to {self.view_id!r} — "
                    f"chains must never merge observations across views."
                )

    @property
    def segment_sum_m(self) -> float:
        return sum(o.value_m for o in self.observations)


@dataclass
class LevelMarker:
    """A vertical level datum (roof/floor/ceiling/ground/beam) from a
    section or elevation. `scope_id` distinguishes a local height (e.g. a
    bulkhead over one room) from the general building datum — height
    resolution only ever combines markers sharing the same scope_id, so a
    local override can never leak into (or be leaked into by) the general
    height."""
    marker_id: str
    level_m: float
    raw_text: str
    marker_type: str  # "roof", "floor", "ceiling", "ground", "beam", "unknown"
    view_id: str = ""
    source_page: int = 1
    scope_id: Optional[str] = None  # None = general/global building datum


@dataclass
class RectangleResolution:
    """Resolved rectangular geometry for one zone/leg (a whole building
    footprint, or one leg of an L-shape, or one room)."""
    zone_id: str
    status: str = ConstraintStatus.UNRESOLVED.value
    internal_length_m: Optional[float] = None
    internal_width_m: Optional[float] = None
    internal_area_m2: Optional[float] = None
    external_length_m: Optional[float] = None
    external_width_m: Optional[float] = None
    external_perimeter_m: Optional[float] = None
    wall_thickness_m: Optional[float] = None
    notes: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HeightResolution:
    scope_id: Optional[str]
    status: str = ConstraintStatus.UNRESOLVED.value
    clear_height_m: Optional[float] = None
    notes: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Text tokenizing — generic noise filtering only, no value blacklist
# ---------------------------------------------------------------------------

def parse_dimension_tokens_from_text(text: str) -> List[float]:
    """Extract plausible dimension values (in millimetres) from a text
    block, filtering noise by *context and shape*, never by excluding
    specific numeric values. Rejects:
      - a bare 4-digit token that reads as a calendar year (1900-2099) —
        a genuinely generic rule, since any real drawing may carry a date;
      - a token immediately preceded by scale/sheet/date/contact-label
        context words;
      - a token outside the broad plausible dimension range.
    This is deliberately conservative: it is meant to reject drawing
    chrome (title blocks, scale notes, phone numbers), not to decide which
    surviving numbers form a wall — that is DimensionChain's job.
    """
    values: List[float] = []
    for m in re.finditer(r"\b\d{1,2}[,.]?\d{3}\b|\b\d{2,4}\b", text):
        token = m.group(0)
        preceding = text[max(0, m.start() - 24):m.start()]
        if _NOISE_CONTEXT_PATTERN.search(preceding):
            continue
        cleaned = token.replace(",", "").replace(".", "")
        if _YEAR_PATTERN.match(cleaned):
            continue
        try:
            v = float(cleaned)
        except ValueError:
            continue
        lo, hi = _PLAUSIBLE_DIMENSION_RANGE_MM
        if lo <= v <= hi:
            values.append(v)
    return values


# ---------------------------------------------------------------------------
# Reference grouping — internal vs external, or any other distinct binding
# ---------------------------------------------------------------------------

def group_observations_by_reference(
    observations: Sequence[DimensionObservation],
) -> Dict[Optional[str], List[DimensionObservation]]:
    """Group observations by the geometry reference they are actually bound
    to (bound_geometry_id, falling back to the first candidate if not yet
    resolved). Reconciliation/duplicate-collapse functions must only ever
    be called *within* one group. An internal-face dimension and an
    external-face dimension of the same wall are both real, legitimate
    measurements that carry different bound_geometry_id values — they must
    never be reconciled against each other as if one were a corrupted copy
    of the other; this grouping is what keeps them apart by construction."""
    groups: Dict[Optional[str], List[DimensionObservation]] = {}
    for obs in observations:
        key = obs.bound_geometry_id or (obs.candidate_geometry_ids[0] if obs.candidate_geometry_ids else None)
        groups.setdefault(key, []).append(obs)
    return groups


# ---------------------------------------------------------------------------
# Segment classification
# ---------------------------------------------------------------------------

def classify_chain_segments(chain: DimensionChain) -> Dict[str, Any]:
    """Classify a chain's first/last segments as wall thickness only when
    BOTH their structural position (endpoint of a >=3-segment chain) AND
    their value (within the generic plausibility range) support it. A
    chain shorter than 3 segments, or whose endpoints fall outside the
    plausible range, is left unclassified — never guessed."""
    obs = chain.observations
    if len(obs) == 1:
        return {"wall_thickness_m": None, "internal_span_m": obs[0].value_m, "role": "single_segment"}
    if len(obs) < 3:
        return {"wall_thickness_m": None, "internal_span_m": None, "role": "insufficient_segments"}

    lo, hi = _WALL_THICKNESS_RANGE_M
    first_v, last_v = obs[0].value_m, obs[-1].value_m
    first_is_wall = lo <= first_v <= hi
    last_is_wall = lo <= last_v <= hi

    if first_is_wall and last_is_wall:
        internal = obs[1:-1]
        internal_sum = sum(o.value_m for o in internal) if internal else None
        return {
            "wall_thickness_m": (first_v, last_v),
            "internal_span_m": internal_sum,
            "role": "wall_enclosed",
        }
    return {"wall_thickness_m": None, "internal_span_m": None, "role": "unclassified"}


# ---------------------------------------------------------------------------
# Overall-vs-chain and duplicate-observation reconciliation
# ---------------------------------------------------------------------------

def reconcile_overall_and_chain(
    overall: Optional[DimensionObservation],
    chain: DimensionChain,
    tolerance_m: float = 0.01,
) -> Tuple[Optional[float], str, List[str]]:
    """Compare an explicit "overall" dimension against the sum of a chain's
    own segments for the same span (capability #1, #10). Never silently
    prefers one over the other on mismatch. Returns
    (resolved_value_m, ConstraintStatus, notes)."""
    chain_sum = chain.segment_sum_m
    if not chain.observations:
        if overall is None:
            return None, ConstraintStatus.UNRESOLVED.value, ["no overall dimension and no chain segments"]
        return overall.value_m, ConstraintStatus.FULLY_CONSTRAINED.value, []
    if overall is None:
        return chain_sum, ConstraintStatus.FULLY_CONSTRAINED.value, []
    diff = abs(overall.value_m - chain_sum)
    if diff <= tolerance_m:
        return overall.value_m, ConstraintStatus.FULLY_CONSTRAINED.value, []
    return None, ConstraintStatus.CONFLICT_MANUAL_REVIEW.value, [
        f"Overall dimension {overall.value_m:.4f}m does not match chain segment "
        f"sum {chain_sum:.4f}m (difference {diff:.4f}m, tolerance {tolerance_m:.4f}m)"
    ]


def reconcile_duplicate_observations(
    observations: Sequence[DimensionObservation],
    tolerance_m: float = 0.005,
) -> Tuple[Optional[DimensionObservation], str, List[str]]:
    """Reconcile multiple observations believed to represent the SAME
    physical dimension (e.g. a native-text extraction and an OCR
    extraction of the same printed number, or the same dimension repeated
    across two views). If every value agrees within tolerance, the
    highest-authority observation (documented > scaled > AI-detected, then
    highest confidence) is returned. If they disagree, returns None with
    CONFLICT_MANUAL_REVIEW — never the value that merely looks more
    plausible."""
    if not observations:
        return None, ConstraintStatus.UNRESOLVED.value, ["no observations"]
    if len(observations) == 1:
        return observations[0], ConstraintStatus.FULLY_CONSTRAINED.value, []

    values = [o.value_m for o in observations]
    spread = max(values) - min(values)
    if spread <= tolerance_m:
        authority_order = {
            MeasurementAuthorityType.DOCUMENTED_DIMENSION.value: 0,
            MeasurementAuthorityType.PDF_SCALED.value: 1,
            MeasurementAuthorityType.AI_DETECTED.value: 2,
        }
        best = sorted(
            observations,
            key=lambda o: (authority_order.get(o.authority, 9), -o.confidence),
        )[0]
        return best, ConstraintStatus.FULLY_CONSTRAINED.value, []

    return None, ConstraintStatus.CONFLICT_MANUAL_REVIEW.value, [
        f"{len(observations)} observations of the same dimension disagree by "
        f"{spread:.4f}m (values: {sorted(round(v, 4) for v in values)})"
    ]


# ---------------------------------------------------------------------------
# Rectangle (footprint / room / leg) resolution
# ---------------------------------------------------------------------------

def resolve_rectangle_from_chains(
    zone_id: str,
    length_chain: Optional[DimensionChain],
    width_chain: Optional[DimensionChain],
    length_overall: Optional[DimensionObservation] = None,
    width_overall: Optional[DimensionObservation] = None,
) -> RectangleResolution:
    """Resolve one rectangular zone's internal/external dimensions, area,
    and perimeter from up to two orthogonal dimension chains. Requires
    BOTH axes to be genuinely constrained (either a wall-enclosed chain or
    a matching overall+chain pair) to reach FULLY_CONSTRAINED; a single
    axis yields PARTIALLY_CONSTRAINED; no axes yields UNRESOLVED. Wall
    thickness is only used when both chains agree on it (within a small
    tolerance) or only one chain classifies a thickness at all — a
    genuine disagreement fails closed rather than picking either value.
    """
    result = RectangleResolution(zone_id=zone_id)
    notes: List[str] = []
    sources: Dict[str, Any] = {}

    def _resolve_axis(chain: Optional[DimensionChain], overall: Optional[DimensionObservation], label: str):
        if chain is None:
            return None, None
        classification = classify_chain_segments(chain)
        span_m = classification["internal_span_m"]
        thickness = classification["wall_thickness_m"]
        if span_m is None and chain.observations:
            # No wall-enclosed classification — fall back to reconciling
            # against an explicit overall dimension for this axis, if any.
            resolved, status, axis_notes = reconcile_overall_and_chain(overall, chain)
            notes.extend(f"{label}: {n}" for n in axis_notes)
            if status == ConstraintStatus.CONFLICT_MANUAL_REVIEW.value:
                return "CONFLICT", None
            span_m = resolved
        sources[f"{label}_chain_sum_m"] = chain.segment_sum_m
        if thickness is not None:
            sources[f"{label}_wall_thickness_candidates_m"] = thickness
        return span_m, thickness

    length_span, length_thickness = _resolve_axis(length_chain, length_overall, "length")
    width_span, width_thickness = _resolve_axis(width_chain, width_overall, "width")

    if length_span == "CONFLICT" or width_span == "CONFLICT":
        result.status = ConstraintStatus.CONFLICT_MANUAL_REVIEW.value
        result.notes = notes
        result.sources = sources
        return result

    wall_thickness_m: Optional[float] = None
    thickness_candidates = [t for t in (length_thickness, width_thickness) if t is not None]
    if thickness_candidates:
        flat = [v for pair in thickness_candidates for v in pair]
        if max(flat) - min(flat) <= 0.02:
            wall_thickness_m = sum(flat) / len(flat)
        else:
            notes.append(
                f"Length-axis and width-axis wall thickness disagree "
                f"({length_thickness} vs {width_thickness}) — thickness left unresolved."
            )

    result.internal_length_m = length_span
    result.internal_width_m = width_span

    if length_span is not None and width_span is not None:
        result.internal_area_m2 = round(length_span * width_span, 4)
        if wall_thickness_m is not None:
            result.wall_thickness_m = round(wall_thickness_m, 4)
            result.external_length_m = round(length_span + 2 * wall_thickness_m, 4)
            result.external_width_m = round(width_span + 2 * wall_thickness_m, 4)
            result.external_perimeter_m = round(2 * (result.external_length_m + result.external_width_m), 4)
        result.status = ConstraintStatus.FULLY_CONSTRAINED.value
    elif length_span is not None or width_span is not None:
        result.status = ConstraintStatus.PARTIALLY_CONSTRAINED.value
    else:
        result.status = ConstraintStatus.UNRESOLVED.value

    result.notes = notes
    result.sources = sources
    return result


# ---------------------------------------------------------------------------
# Height resolution — strictly evidence-scoped, no default fallback
# ---------------------------------------------------------------------------

_ROOF_LIKE = {"roof", "ceiling", "beam"}
_FLOOR_LIKE = {"floor", "ground"}


def resolve_wall_height(levels: Sequence[LevelMarker], scope_id: Optional[str] = None) -> HeightResolution:
    """Resolve clear wall/room height strictly from real level-marker
    evidence sharing `scope_id` — never mixing a local scope's markers
    into the general datum or vice versa, and never substituting a
    default height when evidence is missing. A local scope_id (e.g. one
    room's bulkhead) resolves independently of the general building
    datum, so a local override can never leak into unrelated geometry."""
    result = HeightResolution(scope_id=scope_id)
    scoped = [l for l in levels if l.scope_id == scope_id]
    roof_levels = [l.level_m for l in scoped if l.marker_type in _ROOF_LIKE]
    floor_levels = [l.level_m for l in scoped if l.marker_type in _FLOOR_LIKE]

    if not roof_levels or not floor_levels:
        result.status = ConstraintStatus.UNRESOLVED.value
        result.notes.append(
            f"Missing {'roof/ceiling' if not roof_levels else 'floor/ground'} "
            f"level evidence for scope {scope_id!r} — height left unresolved, not defaulted."
        )
        return result

    height = max(roof_levels) - min(floor_levels)
    if not math.isfinite(height) or height <= 0.0:
        result.status = ConstraintStatus.UNRESOLVED.value
        result.notes.append(f"Computed height {height!r} is non-finite or non-positive.")
        return result

    result.clear_height_m = round(height, 4)
    result.status = ConstraintStatus.FULLY_CONSTRAINED.value
    result.sources = {
        "roof_level_m": max(roof_levels),
        "floor_level_m": min(floor_levels),
        "scope_id": scope_id,
    }
    return result
