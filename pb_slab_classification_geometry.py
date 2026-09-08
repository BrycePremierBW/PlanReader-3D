"""pb_slab_classification_geometry.py — Generic Reinforced-Floor-Slab
Classification & Geometry Binding (Phase F.21).

Recognizes reinforced-concrete slab annotations (RC SLAB, REINFORCED
CONCRETE SLAB, SUSPENDED SLAB, GROUND BEARING SLAB, POST-TENSIONED SLAB),
their thickness callouts and reinforcement specifications, and binds them
to authoritative boundary/floor geometry supplied by the caller. This
module never traces its own boundary geometry -- it reuses whatever
authoritative geometry the rest of the pipeline has already resolved (see
CandidateBoundary), exactly mirroring the authority doctrine already
established by pb_dimension_graph_constraint_engine.py (F.13):
DOCUMENTED_DIMENSION evidence only, never a convenience default.

Fail-closed doctrine, same family as ConstraintStatus (F.13) but with
slab-specific state names, because a slab has two independent evidence
axes -- boundary and thickness -- that ConstraintStatus's single
PARTIALLY_CONSTRAINED state would conflate:
    RESOLVED              -- boundary bound, thickness resolved, no conflicts
    UNRESOLVED             -- nothing yet evaluated (dataclass default)
    UNRESOLVED_THICKNESS   -- boundary bound, but no thickness evidence
    UNRESOLVED_BOUNDARY    -- annotation has no (or no unambiguous) boundary
    CONFLICTING            -- thickness observations disagree, or more than
                              one candidate boundary binds ambiguously
Priority when more than one condition applies: CONFLICTING (an explicit
contradiction) beats UNRESOLVED_BOUNDARY beats UNRESOLVED_THICKNESS -- a
real disagreement is worse than merely missing evidence, and a missing
boundary blocks any measured quantity regardless of thickness status.

This module has ZERO knowledge of benchmark IDs, ground truth BOQs, or
expected quantities, and never imports or reads any ground truth manifest
file. A ResolvedSlabEntity's area_m2 is never computed by this module from
raw geometry -- it is always the caller-supplied, already-authoritative
CandidateBoundary.area_m2, so this module can never fabricate an area from
an unverified or unit-unsafe source.

Known, explicit scope limit (see pb_planreader_pdf_extractor.py wiring):
production annotation-to-boundary binding uses each annotation's own real
PDF word position tested against the real page-space bounding envelope of
the dimension-shaped words that produced the boundary's resolved
length/width -- a genuine, evidence-bounded spatial region, but a coarser
proxy than true vector-traced witness-line geometry (see F13-03 in the
F-series review). This is a documented limitation, not a silent guess.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pb_geometry_takeoff_model import MeasurementAuthorityType


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SlabType(str, Enum):
    """String-valued, matching this repo's existing authority/status enum
    convention (MeasurementAuthorityType, ConstraintStatus) rather than the
    plain integer enum of the original spec sketch."""
    REINFORCED_CONCRETE = "reinforced_concrete"
    SUSPENDED_SLAB = "suspended_slab"
    GROUND_BEARING_SLAB = "ground_bearing_slab"
    POST_TENSIONED = "post_tensioned"
    UNKNOWN = "unknown"


class SlabResolutionState(str, Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    UNRESOLVED_THICKNESS = "UNRESOLVED_THICKNESS"
    UNRESOLVED_BOUNDARY = "UNRESOLVED_BOUNDARY"
    CONFLICTING = "CONFLICTING"


# A broad, generic real-world RC floor slab thickness range. Domestic and
# light-commercial ground-bearing slabs commonly run 100-200mm; suspended
# and post-tensioned slabs commonly run up to 300-450mm. Below 50mm is a
# topping/screed, not a structural RC slab; above 500mm is implausible for
# any conventional building floor slab. A plausibility bound, not an
# exact-value lookup table -- mirrors _WALL_THICKNESS_RANGE_M's role in
# pb_dimension_graph_constraint_engine.py.
_SLAB_THICKNESS_RANGE_MM: Tuple[float, float] = (50.0, 500.0)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SlabReinforcement:
    reinforcement_type: str  # normalized canonical form, e.g. "T12@200-EW", "A142"
    specification: str  # raw source text as printed


@dataclass
class SlabThicknessObservation:
    value_mm: float
    raw_text: str
    source_page: int = 1
    authority: str = MeasurementAuthorityType.DOCUMENTED_DIMENSION.value


@dataclass
class SlabAnnotationObservation:
    annotation_id: str
    slab_type: str  # SlabType value
    raw_text: str
    source_page: int = 1
    # Real position in whatever 2D reference frame the bound CandidateBoundary
    # shares (PDF points in production; any consistent unit in tests). None
    # means no spatial evidence is available -- binding then always fails
    # closed to UNRESOLVED_BOUNDARY, never falls back to keyword presence.
    position: Optional[Tuple[float, float]] = None
    match_start: int = -1
    match_end: int = -1


@dataclass
class CandidateBoundary:
    """Authoritative boundary/floor geometry supplied by the caller -- this
    module never derives one itself. `area_m2` must already be a genuine,
    unit-safe physical area (e.g. pb_multi_space_footprint_geometry's
    FootprintGeometryResult.gross_floor_area_m2, or a
    pb_dimension_graph_constraint_engine.RectangleResolution's
    internal_area_m2) -- never recomputed here from `polygon`, since
    `polygon` may live in a page-space unit (PDF points) that carries no
    physical scale of its own."""
    boundary_id: str
    polygon: List[Tuple[float, float]]
    area_m2: float
    source_page: int = 1
    units_authoritative: bool = True
    # Real page-space region (x0, y0, x1, y1) this boundary corresponds to,
    # for annotation binding when `polygon` itself carries no real page
    # position (see module docstring). None falls back to point-in-polygon
    # / edge-adjacency testing directly against `polygon`.
    spatial_envelope: Optional[Tuple[float, float, float, float]] = None


@dataclass
class ResolvedSlabEntity:
    slab_id: str
    slab_type: str = SlabType.UNKNOWN.value
    thickness_mm: Optional[float] = None
    reinforcement: List[SlabReinforcement] = field(default_factory=list)
    boundary_polygon: Optional[List[Tuple[float, float]]] = None
    area_m2: Optional[float] = None
    resolution_state: str = SlabResolutionState.UNRESOLVED.value
    provenance: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Annotation recognition -- order matters: more specific phrases before the
# generic bare "RC SLAB" pattern, and overlapping matches are never
# double-counted (see extract_slab_annotations_from_text).
# ---------------------------------------------------------------------------

_SLAB_ANNOTATION_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    (
        re.compile(r"\bpost[\s-]?tensioned\b(?:\s+r\.?c\.?)?\s+slab\b", re.IGNORECASE),
        SlabType.POST_TENSIONED.value,
    ),
    (
        re.compile(r"\bground[\s-]?bearing\b\s+slab\b", re.IGNORECASE),
        SlabType.GROUND_BEARING_SLAB.value,
    ),
    (
        re.compile(r"\bsuspended\b(?:\s+r\.?c\.?)?\s+slab\b", re.IGNORECASE),
        SlabType.SUSPENDED_SLAB.value,
    ),
    (
        re.compile(r"\breinforced\s+concrete\s+slab\b", re.IGNORECASE),
        SlabType.REINFORCED_CONCRETE.value,
    ),
    (
        re.compile(r"\br\.?\s?c\.?\s+slab\b", re.IGNORECASE),
        SlabType.REINFORCED_CONCRETE.value,
    ),
)


def extract_slab_annotations_from_text(
    text: str, *, source_page: int = 1
) -> List[SlabAnnotationObservation]:
    """Find every recognized slab annotation phrase in `text`. Overlapping
    matches (e.g. "SUSPENDED RC SLAB" also containing the bare "RC SLAB"
    pattern) are claimed once only, by whichever pattern is checked first
    -- so a suspended slab is never also double-counted as a second,
    generic reinforced-concrete slab entity."""
    out: List[SlabAnnotationObservation] = []
    claimed_spans: List[Tuple[int, int]] = []
    for pattern, slab_type in _SLAB_ANNOTATION_PATTERNS:
        for m in pattern.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in claimed_spans):
                continue
            claimed_spans.append((m.start(), m.end()))
            out.append(
                SlabAnnotationObservation(
                    annotation_id=f"slab_ann_p{source_page}_{m.start()}",
                    slab_type=slab_type,
                    raw_text=m.group(0),
                    source_page=source_page,
                    match_start=m.start(),
                    match_end=m.end(),
                )
            )
    out.sort(key=lambda a: a.match_start)
    return out


# ---------------------------------------------------------------------------
# Thickness parsing -- flexible token ordering, one combined pattern so the
# same numeral is never claimed by two alternative branches at once.
# ---------------------------------------------------------------------------

_THICKNESS_RE = re.compile(
    r"(?:(\d{2,4}(?:\.\d+)?)\s*mm\s+thick\b)"  # "100mm THICK" ... SLAB
    r"|(?:\bthk\b\s*[:\-]?\s*(\d{2,4}(?:\.\d+)?)\s*mm\b)"  # "THK 200mm"
    r"|(?:\bslab\b\s+(\d{2,4}(?:\.\d+)?)\s*mm\b)"  # "SLAB 175mm"
    r"|(?:\b(\d{2,4}(?:\.\d+)?)\s+(?:r\.?\s?c\.?\s+)?slab\b)",  # "150 RC SLAB" / "150 SLAB"
    re.IGNORECASE,
)


def extract_thickness_observations_near(
    text: str, match_start: int, match_end: int, *, source_page: int = 1, window: int = 40
) -> List[SlabThicknessObservation]:
    """Gather every thickness-shaped token in a bounded window around one
    annotation's own match span. Deliberately does not filter by
    plausibility here -- see resolve_slab_thickness, which rejects but
    retains implausible values for provenance rather than discarding them
    silently."""
    window_start = max(0, match_start - window)
    window_end = min(len(text), match_end + window)
    window_text = text[window_start:window_end]

    out: List[SlabThicknessObservation] = []
    for m in _THICKNESS_RE.finditer(window_text):
        raw_val = next((g for g in m.groups() if g is not None), None)
        if raw_val is None:
            continue
        try:
            value_mm = float(raw_val)
        except ValueError:
            continue
        out.append(
            SlabThicknessObservation(
                value_mm=value_mm,
                raw_text=m.group(0).strip(),
                source_page=source_page,
            )
        )
    return out


def resolve_slab_thickness(
    observations: Sequence[SlabThicknessObservation], *, tolerance_mm: float = 1.0
) -> Tuple[Optional[float], str, List[SlabThicknessObservation], List[SlabThicknessObservation]]:
    """Resolve one slab's thickness from its own gathered observations.
    Implausible observations (outside the documented generic range) are
    rejected before agreement/conflict is evaluated, but are always
    returned for provenance -- never silently discarded. Returns
    (value_mm, state, accepted, rejected)."""
    lo, hi = _SLAB_THICKNESS_RANGE_MM
    accepted = [o for o in observations if lo <= o.value_mm <= hi]
    rejected = [o for o in observations if not (lo <= o.value_mm <= hi)]

    if not accepted:
        return None, SlabResolutionState.UNRESOLVED_THICKNESS.value, accepted, rejected

    values = sorted({round(o.value_mm, 2) for o in accepted})
    if len(values) == 1:
        return values[0], SlabResolutionState.RESOLVED.value, accepted, rejected

    spread = values[-1] - values[0]
    if spread <= tolerance_mm:
        return round(sum(values) / len(values), 2), SlabResolutionState.RESOLVED.value, accepted, rejected

    return None, SlabResolutionState.CONFLICTING.value, accepted, rejected


# ---------------------------------------------------------------------------
# Reinforcement parsing -- rebar (T/N bar @ spacing) and fabric mesh
# (A/B/SL-series). Mesh codes are shape-ambiguous with drawing/sheet
# numbers, so a mesh-context keyword must appear nearby -- rebar callouts
# are distinctive enough by shape alone.
# ---------------------------------------------------------------------------

_REBAR_RE = re.compile(
    r"\b([TN])\s?(\d{1,2})\s*(?:@|-)\s*(\d{2,4})"
    r"(?:\s*(each\s*way|e\.?\s*w\.?|c\s*/\s*c|cc))?\b",
    re.IGNORECASE,
)
_MESH_RE = re.compile(r"\b(SL|A|B)\s?(\d{2,4})\b")
_MESH_CONTEXT_RE = re.compile(r"\b(mesh|fabric|b\.?\s?r\.?\s?c\.?)\b", re.IGNORECASE)


def _normalize_rebar_suffix(raw: Optional[str]) -> str:
    if not raw:
        return ""
    cleaned = re.sub(r"[.\s]", "", raw).upper()
    if cleaned in ("EW", "EACHWAY"):
        return "EW"
    if cleaned in ("CC", "C/C"):
        return "CC"
    return cleaned


def extract_reinforcement_near(
    text: str, match_start: int, match_end: int, *, source_page: int = 1, window: int = 80
) -> List[SlabReinforcement]:
    """Gather and normalize reinforcement callouts in a bounded window
    around one annotation's match span -- never a global scan of the whole
    page/document, so an unrelated code far from any slab annotation is
    never pulled in. Deduplicated by normalized canonical form."""
    window_start = max(0, match_start - window)
    window_end = min(len(text), match_end + window)
    window_text = text[window_start:window_end]

    found: Dict[str, SlabReinforcement] = {}

    for m in _REBAR_RE.finditer(window_text):
        bar_type, dia, spacing, suffix = m.groups()
        suffix_norm = _normalize_rebar_suffix(suffix)
        canonical = f"{bar_type.upper()}{int(dia)}@{int(spacing)}"
        if suffix_norm:
            canonical += f"-{suffix_norm}"
        found.setdefault(
            canonical, SlabReinforcement(reinforcement_type=canonical, specification=m.group(0).strip())
        )

    for m in _MESH_RE.finditer(window_text):
        ctx_start = max(0, m.start() - 40)
        ctx_end = min(len(window_text), m.end() + 40)
        if not _MESH_CONTEXT_RE.search(window_text[ctx_start:ctx_end]):
            continue
        prefix, number = m.groups()
        canonical = f"{prefix.upper()}{number}"
        found.setdefault(
            canonical, SlabReinforcement(reinforcement_type=canonical, specification=m.group(0).strip())
        )

    return list(found.values())


# ---------------------------------------------------------------------------
# Boundary polygon validation & geometry helpers
# ---------------------------------------------------------------------------

def _polygon_area_abs(pts: Sequence[Tuple[float, float]]) -> float:
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _point_in_polygon(point: Tuple[float, float], polygon: Sequence[Tuple[float, float]]) -> bool:
    x, y = point
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_intersect = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def _distance_point_to_segment(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> float:
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    proj_x, proj_y = ax + t * dx, ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _distance_to_polygon_boundary(point: Tuple[float, float], polygon: Sequence[Tuple[float, float]]) -> float:
    n = len(polygon)
    return min(
        _distance_point_to_segment(point, polygon[i], polygon[(i + 1) % n]) for i in range(n)
    )


def validate_boundary_polygon(polygon: Optional[Sequence[Tuple[float, float]]]) -> bool:
    """A boundary polygon is valid only with >= 3 distinct, finite
    vertices forming a real (nonzero-area) closed ring with no
    zero-length edges. Self-intersection is not checked -- a documented
    scope limit, not a silent gap."""
    if polygon is None:
        return False
    pts: List[Tuple[float, float]] = []
    for p in polygon:
        try:
            x, y = p
        except (TypeError, ValueError):
            return False
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
            return False
        if isinstance(x, bool) or isinstance(y, bool):
            return False
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
        pts.append((float(x), float(y)))

    if len(pts) < 3:
        return False
    if len(set(pts)) < 3:
        return False
    n = len(pts)
    for i in range(n):
        if pts[i] == pts[(i + 1) % n]:
            return False
    if _polygon_area_abs(pts) <= 1e-9:
        return False
    return True


def _boundary_binds(
    annotation: SlabAnnotationObservation, boundary: CandidateBoundary, adjacency_tolerance: float
) -> bool:
    """True only when real spatial evidence places the annotation inside,
    or within `adjacency_tolerance` of, the boundary -- never on keyword
    presence alone. When the boundary carries a real page-space
    `spatial_envelope`, that is authoritative; otherwise falls back to a
    point-in-polygon / edge-adjacency test directly against `polygon`."""
    if annotation.position is None:
        return False
    if boundary.spatial_envelope is not None:
        x0, y0, x1, y1 = boundary.spatial_envelope
        px, py = annotation.position
        return (
            (x0 - adjacency_tolerance) <= px <= (x1 + adjacency_tolerance)
            and (y0 - adjacency_tolerance) <= py <= (y1 + adjacency_tolerance)
        )
    if not validate_boundary_polygon(boundary.polygon):
        return False
    if _point_in_polygon(annotation.position, boundary.polygon):
        return True
    return _distance_to_polygon_boundary(annotation.position, boundary.polygon) <= adjacency_tolerance


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_slab_entity(
    *,
    slab_id: str,
    annotation: SlabAnnotationObservation,
    thickness_observations: Sequence[SlabThicknessObservation],
    reinforcement: Sequence[SlabReinforcement],
    candidate_boundaries: Sequence[CandidateBoundary],
    adjacency_tolerance: float = 0.5,
    thickness_tolerance_mm: float = 1.0,
) -> ResolvedSlabEntity:
    """Resolve one slab entity from its own gathered evidence. A boundary
    without slab evidence never reaches this function in the first place
    (callers only ever construct it from a recognized SlabAnnotationObservation)
    -- a bare boundary can never automatically become a slab."""
    provenance: Dict[str, Any] = {
        "annotation_raw_text": annotation.raw_text,
        "annotation_source_page": annotation.source_page,
        "thickness_observations": [asdict(o) for o in thickness_observations],
        "reinforcement_raw_count": len(reinforcement),
    }

    thickness_mm, thickness_state, _accepted_thick, rejected_thick = resolve_slab_thickness(
        thickness_observations, tolerance_mm=thickness_tolerance_mm
    )
    if rejected_thick:
        provenance["rejected_thickness_observations"] = [asdict(o) for o in rejected_thick]

    dedup_reinforcement: Dict[str, SlabReinforcement] = {}
    for r in reinforcement:
        dedup_reinforcement.setdefault(r.reinforcement_type, r)
    reinforcement_list = list(dedup_reinforcement.values())

    entity = ResolvedSlabEntity(
        slab_id=slab_id,
        slab_type=annotation.slab_type,
        thickness_mm=thickness_mm,
        reinforcement=reinforcement_list,
        provenance=provenance,
    )

    if thickness_state == SlabResolutionState.CONFLICTING.value:
        entity.resolution_state = SlabResolutionState.CONFLICTING.value
        entity.thickness_mm = None
        provenance["conflict_reason"] = "thickness_observations_disagree"
        return entity

    same_page = [b for b in candidate_boundaries if b.source_page == annotation.source_page]
    bound_candidates = [
        b
        for b in same_page
        if b.units_authoritative
        and validate_boundary_polygon(b.polygon)
        and _boundary_binds(annotation, b, adjacency_tolerance)
    ]

    if len(bound_candidates) > 1:
        entity.resolution_state = SlabResolutionState.CONFLICTING.value
        provenance["conflict_reason"] = "ambiguous_boundary_binding"
        provenance["ambiguous_boundary_ids"] = [b.boundary_id for b in bound_candidates]
        return entity

    if not bound_candidates:
        entity.resolution_state = SlabResolutionState.UNRESOLVED_BOUNDARY.value
        return entity

    boundary = bound_candidates[0]
    entity.boundary_polygon = list(boundary.polygon)
    provenance["boundary_id"] = boundary.boundary_id

    if thickness_state == SlabResolutionState.UNRESOLVED_THICKNESS.value:
        entity.resolution_state = SlabResolutionState.UNRESOLVED_THICKNESS.value
        return entity

    entity.area_m2 = boundary.area_m2
    entity.resolution_state = SlabResolutionState.RESOLVED.value
    return entity


def resolve_slabs_from_text(
    text: str,
    candidate_boundaries: Sequence[CandidateBoundary],
    *,
    source_page: int = 1,
    thickness_window: int = 40,
    reinforcement_window: int = 80,
    adjacency_tolerance: float = 0.5,
    thickness_tolerance_mm: float = 1.0,
) -> List[ResolvedSlabEntity]:
    """Text-only convenience: finds every slab annotation in `text` and
    resolves each against `candidate_boundaries`. Annotations built this
    way always carry `position=None` (plain text carries no coordinates),
    so binding always fails closed to UNRESOLVED_BOUNDARY unless a caller
    replaces an annotation's `.position` before resolving -- this is by
    design: keyword presence in text is never sufficient to bind a slab to
    geometry. See resolve_slabs_from_page for the real-PDF entry point."""
    annotations = extract_slab_annotations_from_text(text, source_page=source_page)
    resolved: List[ResolvedSlabEntity] = []
    for idx, ann in enumerate(annotations):
        thickness_obs = extract_thickness_observations_near(
            text, ann.match_start, ann.match_end, source_page=source_page, window=thickness_window
        )
        reinforcement = extract_reinforcement_near(
            text, ann.match_start, ann.match_end, source_page=source_page, window=reinforcement_window
        )
        resolved.append(
            resolve_slab_entity(
                slab_id=f"slab_p{source_page}_{idx}",
                annotation=ann,
                thickness_observations=thickness_obs,
                reinforcement=reinforcement,
                candidate_boundaries=candidate_boundaries,
                adjacency_tolerance=adjacency_tolerance,
                thickness_tolerance_mm=thickness_tolerance_mm,
            )
        )
    return resolved


def dimension_word_bbox_envelope(page: Any) -> Optional[Tuple[float, float, float, float]]:
    """Real page-space bounding envelope of every dimension-shaped word on
    this page -- the same word-shape test pb_dimension_chain_evidence_extractor
    already uses to build DimensionChain evidence (reused directly, not
    reinvented). A genuine, evidence-bounded region of the page -- not the
    whole page, and not a synthetic reconstruction -- used as the spatial
    region a slab annotation must be near to bind to the footprint those
    same dimension words produced. None if no dimension-shaped words are
    found on the page."""
    from pb_dimension_chain_evidence_extractor import _DIM_WORD_RE

    xs0: List[float] = []
    ys0: List[float] = []
    xs1: List[float] = []
    ys1: List[float] = []
    for w in page.get_text("words"):
        if not _DIM_WORD_RE.match(w[4]):
            continue
        xs0.append(w[0])
        ys0.append(w[1])
        xs1.append(w[2])
        ys1.append(w[3])
    if not xs0:
        return None
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def _auto_adjacency_tolerance(
    candidate_boundaries: Sequence[CandidateBoundary],
    page_rect: Optional[Any] = None,
) -> float:
    """A scale-aware fallback tolerance, relative to this specific page/
    sheet rather than one universal constant: half the diagonal of the
    real page-space envelope(s) the candidate boundaries carry, floored at
    roughly a third of the page's own shorter side (when the page is
    known) so a note placed anywhere plausibly near the dimensioned region
    of THIS sheet is not rejected purely for landing on a different text
    line than the dimension figures themselves. Proximity alone never
    resolves a slab -- it is one of several independent gates (same page,
    a single unambiguous candidate, corroborated thickness) resolve_slab_entity
    still requires."""
    floor = 40.0
    if page_rect is not None:
        floor = max(floor, 0.35 * min(page_rect.width, page_rect.height))
    envelopes = [b.spatial_envelope for b in candidate_boundaries if b.spatial_envelope is not None]
    if not envelopes:
        return floor
    x0 = min(e[0] for e in envelopes)
    y0 = min(e[1] for e in envelopes)
    x1 = max(e[2] for e in envelopes)
    y1 = max(e[3] for e in envelopes)
    diagonal = math.hypot(x1 - x0, y1 - y0)
    return max(floor, diagonal * 0.5)


def resolve_slabs_from_page(
    page: Any,
    candidate_boundaries: Sequence[CandidateBoundary],
    *,
    source_page: int = 1,
    thickness_window: int = 40,
    reinforcement_window: int = 80,
    adjacency_tolerance: Optional[float] = None,
    thickness_tolerance_mm: float = 1.0,
) -> List[ResolvedSlabEntity]:
    """Real-PDF entry point. Finds slab annotations from the page's text,
    locates each annotation's real page-space position from its own "slab"
    word's bounding box (never assumed, never interpolated from unrelated
    text), and resolves each against the supplied candidate boundaries.
    `adjacency_tolerance` left at its default (None) is computed
    automatically from the candidate boundaries' own spatial envelopes
    (see _auto_adjacency_tolerance) rather than assuming one fixed value
    suits every drawing scale/sheet size. If a page has more slab
    annotations than located "slab" word positions (should not normally
    happen -- every recognized phrase ends in the
    word "slab"), the surplus annotations resolve with position=None and
    therefore fail closed to UNRESOLVED_BOUNDARY rather than guessing."""
    resolved_adjacency_tolerance = (
        adjacency_tolerance
        if adjacency_tolerance is not None
        else _auto_adjacency_tolerance(candidate_boundaries, page_rect=page.rect)
    )

    text = page.get_text("text")
    words = page.get_text("words")
    annotations = extract_slab_annotations_from_text(text, source_page=source_page)

    slab_word_positions = [
        ((w[0] + w[2]) / 2.0, (w[1] + w[3]) / 2.0)
        for w in words
        if w[4].strip(".,;:").lower() == "slab"
    ]

    resolved: List[ResolvedSlabEntity] = []
    for idx, ann in enumerate(annotations):
        if idx < len(slab_word_positions):
            ann.position = slab_word_positions[idx]
        thickness_obs = extract_thickness_observations_near(
            text, ann.match_start, ann.match_end, source_page=source_page, window=thickness_window
        )
        reinforcement = extract_reinforcement_near(
            text, ann.match_start, ann.match_end, source_page=source_page, window=reinforcement_window
        )
        resolved.append(
            resolve_slab_entity(
                slab_id=f"slab_p{source_page}_{idx}",
                annotation=ann,
                thickness_observations=thickness_obs,
                reinforcement=reinforcement,
                candidate_boundaries=candidate_boundaries,
                adjacency_tolerance=resolved_adjacency_tolerance,
                thickness_tolerance_mm=thickness_tolerance_mm,
            )
        )
    return resolved
