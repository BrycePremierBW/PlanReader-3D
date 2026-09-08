"""Figured-dimension evidence extraction and binding (Phase F.13 completion).

This module closes the raw-evidence gap deliberately left by
``pb_dimension_graph_constraint_engine``.  It converts native PDF text,
vector linework, and explicitly transformed OCR candidates into traceable
``DimensionObservation`` records without conflating four distinct concepts:

1. observed page geometry (PDF vector segments),
2. figured-dimension constraints (printed dimension values),
3. candidate bindings (dimension / witness-line associations), and
4. resolved construction geometry (owned by the F.13 constraint engine).

Important safety properties:
- project/file/benchmark identity is never an input to semantic decisions;
- non-dimension drafting tokens are typed rather than value-blacklisted;
- OCR does not overwrite native evidence -- both candidates are preserved;
- raster coordinates require an explicit transform before they can be mixed
  with PDF-point coordinates;
- figured dimensions do not require drawing scale, while scaled vector
  measurements require a page-matched usable ScaleCalibration;
- ambiguous line/witness association fails closed rather than picking the
  value or geometry that looks most convenient.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
import statistics
from typing import Any, Iterable, Optional, Sequence

from pb_dimension_graph_constraint_engine import (
    ConstraintStatus,
    DimensionChain,
    DimensionObservation,
    DimensionOrientation,
    reconcile_duplicate_observations,
)
from pb_drawing_evidence_binding import DrawingViewType
from pb_geometry_takeoff_model import (
    AuthorityStatus,
    MeasurementAuthorityType,
    ScaleCalibration,
)
from pb_page_scale_calibration_authority import measurement_authority_for_page_scale


class CoordinateSpace(str, Enum):
    PDF_POINTS = "pdf_points"
    RASTER_PIXELS = "raster_pixels"


class DimensionTokenKind(str, Enum):
    LINEAR_DIMENSION = "linear_dimension"
    SCALE = "scale"
    DRAWING_REFERENCE = "drawing_reference"
    ROOM_NUMBER = "room_number"
    OPENING_TAG = "opening_tag"
    GRID_LABEL = "grid_label"
    REVISION = "revision"
    YEAR = "year"
    SHEET_NUMBER = "sheet_number"
    DRAWING_NUMBER = "drawing_number"
    OTHER = "other"


class BindingStatus(str, Enum):
    WITNESS_BOUND = "witness_bound"
    LINE_BOUND = "line_bound"
    PARTIAL_WITNESS = "partial_witness"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class DimensionEvidenceTier(str, Enum):
    WITNESS_BOUND = "witness_bound"
    LINE_BOUND = "line_bound"
    TEXT_ONLY = "text_only"
    OCR_ONLY = "ocr_only"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class TypedDimensionToken:
    raw_text: str
    kind: str
    value: Optional[float] = None
    unit: Optional[str] = None
    normalized_text: str = ""
    reason: str = ""

    @property
    def is_linear_dimension(self) -> bool:
        return self.kind == DimensionTokenKind.LINEAR_DIMENSION.value and self.value is not None


@dataclass(frozen=True)
class ObservedGeometrySegment:
    segment_id: str
    source_page: int
    start: tuple[float, float]
    end: tuple[float, float]
    coordinate_space: str = CoordinateSpace.PDF_POINTS.value
    view_id: str = ""
    source_path_index: Optional[int] = None

    @property
    def dx(self) -> float:
        return self.end[0] - self.start[0]

    @property
    def dy(self) -> float:
        return self.end[1] - self.start[1]

    @property
    def length(self) -> float:
        return math.hypot(self.dx, self.dy)

    @property
    def orientation(self) -> str:
        if self.length <= 0:
            return DimensionOrientation.UNKNOWN.value
        # Axis classification is relative to the segment itself; no project
        # units or scale assumptions are involved.
        if abs(self.dx) >= abs(self.dy) * 4.0:
            return DimensionOrientation.HORIZONTAL.value
        if abs(self.dy) >= abs(self.dx) * 4.0:
            return DimensionOrientation.VERTICAL.value
        return DimensionOrientation.UNKNOWN.value


@dataclass(frozen=True)
class RasterCoordinateTransform:
    """Explicit raster-pixel -> PDF-point transform for one page.

    OCR boxes must never be mixed with PDF vector coordinates without this
    information. Rotation is intentionally explicit and limited to the four
    lossless page rotations used by the metamorphic suite.
    """

    page_width_pt: float
    page_height_pt: float
    raster_width_px: float
    raster_height_px: float
    rotation_deg: int = 0

    def __post_init__(self) -> None:
        if self.page_width_pt <= 0 or self.page_height_pt <= 0:
            raise ValueError("PDF page dimensions must be positive")
        if self.raster_width_px <= 0 or self.raster_height_px <= 0:
            raise ValueError("Raster dimensions must be positive")
        if self.rotation_deg not in (0, 90, 180, 270):
            raise ValueError("rotation_deg must be one of 0, 90, 180, 270")

    def point_to_pdf(self, point: tuple[float, float]) -> tuple[float, float]:
        x_px, y_px = point
        x = x_px * self.page_width_pt / self.raster_width_px
        y = y_px * self.page_height_pt / self.raster_height_px
        if self.rotation_deg == 0:
            return x, y
        if self.rotation_deg == 90:
            return self.page_width_pt - y, x
        if self.rotation_deg == 180:
            return self.page_width_pt - x, self.page_height_pt - y
        return y, self.page_height_pt - x

    def bbox_to_pdf(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = bbox
        points = [
            self.point_to_pdf((x0, y0)),
            self.point_to_pdf((x1, y0)),
            self.point_to_pdf((x0, y1)),
            self.point_to_pdf((x1, y1)),
        ]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True)
class DimensionLayoutCalibration:
    """Page-derived spatial tolerances used for evidence association."""

    median_word_height_pt: float
    line_search_distance_pt: float
    witness_endpoint_distance_pt: float
    chain_axis_tolerance_pt: float


@dataclass
class DimensionAnchorBinding:
    observation_id: str
    status: str
    dimension_line_id: Optional[str] = None
    witness_line_ids: tuple[str, ...] = field(default_factory=tuple)
    endpoints: Optional[tuple[tuple[float, float], tuple[float, float]]] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class DimensionCandidateGroup:
    group_id: str
    candidates: list[DimensionObservation]
    resolved: Optional[DimensionObservation]
    status: str
    notes: list[str] = field(default_factory=list)


@dataclass
class ScaledSegmentMeasurement:
    segment_id: str
    status: str
    length_m: Optional[float]
    authority: str
    notes: list[str] = field(default_factory=list)


@dataclass
class DimensionEvidenceBundle:
    observations: list[DimensionObservation] = field(default_factory=list)
    observed_geometry: list[ObservedGeometrySegment] = field(default_factory=list)
    bindings: list[DimensionAnchorBinding] = field(default_factory=list)
    candidate_groups: list[DimensionCandidateGroup] = field(default_factory=list)
    chains: list[DimensionChain] = field(default_factory=list)


# Typed grammar: identity-like drafting tokens are recognized by shape/context.
# No benchmark/project-specific values occur here.
_SCALE_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\s*$", re.I)
_REFERENCE_RE = re.compile(r"^\s*\d+\s*/\s*[A-Z]{1,4}\d{1,4}\s*$", re.I)
_DRAWING_NUMBER_RE = re.compile(r"^\s*[A-Z]{1,4}\d{2,4}\s*$", re.I)
_OPENING_TAG_RE = re.compile(r"^\s*(?:D|DR|W|WD)\s*[-_]?\s*\d{1,3}[A-Z]?\s*$", re.I)
_ROOM_RE = re.compile(r"^\s*(?:ROOM|RM)\s*[-:#]?\s*\d+[A-Z]?\s*$", re.I)
_GRID_RE = re.compile(r"^\s*GRID\s*[-:#]?\s*[A-Z0-9]+\s*$", re.I)
_REV_RE = re.compile(r"^\s*REV(?:ISION)?\s*[-:#]?\s*[A-Z0-9]+\s*$", re.I)
_SHEET_RE = re.compile(r"^\s*SHEET\s*[-:#]?\s*\d+\s*$", re.I)
_YEAR_RE = re.compile(r"^\s*(?:19|20)\d{2}\s*$")
_METRIC_MM_RE = re.compile(r"^\s*(\d+(?:[,.]\d+)?)\s*mm\s*$", re.I)
_METRIC_M_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*m\s*$", re.I)
_BARE_MM_RE = re.compile(r"^\s*(\d{2,5}|\d{1,2}[,.]\d{3})\s*$")
_IMPERIAL_RE = re.compile(
    r"^\s*(?:(\d+)\s*(?:'|ft))?\s*[-–]?\s*(?:(\d+(?:\.\d+)?)\s*(?:\"|in))?\s*$",
    re.I,
)
_CONTEXT_KIND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:ROOM|RM)\s*$", re.I), DimensionTokenKind.ROOM_NUMBER.value),
    (re.compile(r"\bGRID\s*$", re.I), DimensionTokenKind.GRID_LABEL.value),
    (re.compile(r"\bREV(?:ISION)?\s*$", re.I), DimensionTokenKind.REVISION.value),
    (re.compile(r"\bSHEET\s*$", re.I), DimensionTokenKind.SHEET_NUMBER.value),
    (re.compile(r"\b(?:DWG|DRAWING\s*NO)\s*$", re.I), DimensionTokenKind.DRAWING_NUMBER.value),
    (re.compile(r"\bSCALE\s*$", re.I), DimensionTokenKind.SCALE.value),
)


def classify_dimension_token(text: str, *, preceding_context: str = "") -> TypedDimensionToken:
    """Classify one dimension candidate using typed drafting grammar.

    Bare numbers are accepted as millimetres only after typed non-dimension
    forms and immediate drafting-label context have been rejected. This keeps
    ordinary dimension strings usable without creating value blacklists.
    """
    raw = text
    normalized = " ".join(text.strip().split())
    for pattern, kind in (
        (_SCALE_RE, DimensionTokenKind.SCALE.value),
        (_REFERENCE_RE, DimensionTokenKind.DRAWING_REFERENCE.value),
        (_ROOM_RE, DimensionTokenKind.ROOM_NUMBER.value),
        (_GRID_RE, DimensionTokenKind.GRID_LABEL.value),
        (_REV_RE, DimensionTokenKind.REVISION.value),
        (_SHEET_RE, DimensionTokenKind.SHEET_NUMBER.value),
        (_OPENING_TAG_RE, DimensionTokenKind.OPENING_TAG.value),
        (_YEAR_RE, DimensionTokenKind.YEAR.value),
        (_DRAWING_NUMBER_RE, DimensionTokenKind.DRAWING_NUMBER.value),
    ):
        if pattern.match(normalized):
            return TypedDimensionToken(raw, kind, normalized_text=normalized, reason="typed drafting token")

    ctx = preceding_context[-40:]
    for pattern, kind in _CONTEXT_KIND_PATTERNS:
        if pattern.search(ctx):
            return TypedDimensionToken(raw, kind, normalized_text=normalized, reason="typed preceding context")

    m = _METRIC_MM_RE.match(normalized)
    if m:
        value = float(m.group(1).replace(",", ""))
        return TypedDimensionToken(raw, DimensionTokenKind.LINEAR_DIMENSION.value, value, "mm", normalized)

    m = _METRIC_M_RE.match(normalized)
    if m:
        return TypedDimensionToken(raw, DimensionTokenKind.LINEAR_DIMENSION.value, float(m.group(1)), "m", normalized)

    # Imperial notation is accepted only when it contains an explicit foot or
    # inch marker. A bare number therefore never becomes imperial by guess.
    if "'" in normalized or '"' in normalized or re.search(r"\b(?:ft|in)\b", normalized, re.I):
        m = _IMPERIAL_RE.match(normalized)
        if m and (m.group(1) or m.group(2)):
            feet = float(m.group(1) or 0.0)
            inches = float(m.group(2) or 0.0)
            return TypedDimensionToken(
                raw,
                DimensionTokenKind.LINEAR_DIMENSION.value,
                feet * 12.0 + inches,
                "in",
                normalized,
            )

    m = _BARE_MM_RE.match(normalized)
    if m:
        cleaned = m.group(1).replace(",", "").replace(".", "")
        if _YEAR_RE.match(cleaned):
            return TypedDimensionToken(raw, DimensionTokenKind.YEAR.value, normalized_text=normalized)
        value = float(cleaned)
        # The F.13 engine owns the general plausible range; retain only
        # positive finite values here and let constraint semantics decide use.
        if math.isfinite(value) and value > 0:
            return TypedDimensionToken(raw, DimensionTokenKind.LINEAR_DIMENSION.value, value, "mm", normalized)

    return TypedDimensionToken(raw, DimensionTokenKind.OTHER.value, normalized_text=normalized, reason="no dimension grammar matched")


def calibrate_dimension_layout(page: Any) -> DimensionLayoutCalibration:
    """Derive spatial association tolerances from this page's own typography."""
    heights = [float(w[3] - w[1]) for w in page.get_text("words") if float(w[3] - w[1]) > 0]
    median_h = statistics.median(heights) if heights else 8.0
    # Multipliers express geometric relationships (nearby line / endpoint /
    # same-axis row) while the absolute scale comes from the document itself.
    return DimensionLayoutCalibration(
        median_word_height_pt=median_h,
        line_search_distance_pt=max(median_h * 2.0, 2.0),
        witness_endpoint_distance_pt=max(median_h * 1.5, 2.0),
        chain_axis_tolerance_pt=max(median_h * 0.55, 1.0),
    )


def _xy(point: Any) -> tuple[float, float]:
    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)
    return float(point[0]), float(point[1])


def extract_vector_segments(
    page: Any,
    *,
    page_num: int,
    view_id: str = "",
) -> list[ObservedGeometrySegment]:
    """Extract native vector line segments without assigning construction meaning."""
    segments: list[ObservedGeometrySegment] = []
    for path_index, path in enumerate(page.get_drawings()):
        for item_index, item in enumerate(path.get("items", [])):
            if not item:
                continue
            kind = item[0]
            if kind == "l" and len(item) >= 3:
                start, end = _xy(item[1]), _xy(item[2])
                if start == end:
                    continue
                segments.append(
                    ObservedGeometrySegment(
                        segment_id=f"vec_p{page_num}_{path_index}_{item_index}",
                        source_page=page_num,
                        start=start,
                        end=end,
                        view_id=view_id,
                        source_path_index=path_index,
                    )
                )
            elif kind == "re" and len(item) >= 2:
                rect = item[1]
                x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
                for edge_index, (start, end) in enumerate((
                    ((x0, y0), (x1, y0)),
                    ((x1, y0), (x1, y1)),
                    ((x1, y1), (x0, y1)),
                    ((x0, y1), (x0, y0)),
                )):
                    if start != end:
                        segments.append(
                            ObservedGeometrySegment(
                                segment_id=f"vec_p{page_num}_{path_index}_{item_index}_e{edge_index}",
                                source_page=page_num,
                                start=start,
                                end=end,
                                view_id=view_id,
                                source_path_index=path_index,
                            )
                        )
    return segments


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0


def _axis_distance(point: tuple[float, float], segment: ObservedGeometrySegment) -> float:
    if segment.orientation == DimensionOrientation.HORIZONTAL.value:
        return abs(point[1] - (segment.start[1] + segment.end[1]) / 2.0)
    if segment.orientation == DimensionOrientation.VERTICAL.value:
        return abs(point[0] - (segment.start[0] + segment.end[0]) / 2.0)
    return float("inf")


def _projection_contains(point: tuple[float, float], segment: ObservedGeometrySegment, margin: float) -> bool:
    if segment.orientation == DimensionOrientation.HORIZONTAL.value:
        lo, hi = sorted((segment.start[0], segment.end[0]))
        return lo - margin <= point[0] <= hi + margin
    if segment.orientation == DimensionOrientation.VERTICAL.value:
        lo, hi = sorted((segment.start[1], segment.end[1]))
        return lo - margin <= point[1] <= hi + margin
    return False


def _intersection_with_perpendicular(
    dimension_line: ObservedGeometrySegment,
    witness: ObservedGeometrySegment,
    tolerance: float,
) -> Optional[tuple[float, float]]:
    if dimension_line.orientation == DimensionOrientation.HORIZONTAL.value and witness.orientation == DimensionOrientation.VERTICAL.value:
        y = (dimension_line.start[1] + dimension_line.end[1]) / 2.0
        x = (witness.start[0] + witness.end[0]) / 2.0
        wy0, wy1 = sorted((witness.start[1], witness.end[1]))
        dx0, dx1 = sorted((dimension_line.start[0], dimension_line.end[0]))
        if wy0 - tolerance <= y <= wy1 + tolerance and dx0 - tolerance <= x <= dx1 + tolerance:
            return x, y
    if dimension_line.orientation == DimensionOrientation.VERTICAL.value and witness.orientation == DimensionOrientation.HORIZONTAL.value:
        x = (dimension_line.start[0] + dimension_line.end[0]) / 2.0
        y = (witness.start[1] + witness.end[1]) / 2.0
        wx0, wx1 = sorted((witness.start[0], witness.end[0]))
        dy0, dy1 = sorted((dimension_line.start[1], dimension_line.end[1]))
        if wx0 - tolerance <= x <= wx1 + tolerance and dy0 - tolerance <= y <= dy1 + tolerance:
            return x, y
    return None


def bind_observation_to_vector_geometry(
    observation: DimensionObservation,
    segments: Sequence[ObservedGeometrySegment],
    calibration: DimensionLayoutCalibration,
) -> DimensionAnchorBinding:
    """Bind one figured dimension to a unique nearby dimension/witness-line system."""
    if observation.bbox is None:
        return DimensionAnchorBinding(observation.dimension_id, BindingStatus.UNSUPPORTED.value, notes=["observation has no PDF-space bbox"])
    center = _bbox_center(observation.bbox)
    same_scope = [
        s for s in segments
        if s.source_page == observation.source_page
        and s.coordinate_space == CoordinateSpace.PDF_POINTS.value
        and (not observation.view_id or not s.view_id or s.view_id == observation.view_id)
        and s.orientation != DimensionOrientation.UNKNOWN.value
    ]
    candidates = [
        s for s in same_scope
        if _axis_distance(center, s) <= calibration.line_search_distance_pt
        and _projection_contains(center, s, calibration.line_search_distance_pt)
    ]
    if not candidates:
        return DimensionAnchorBinding(observation.dimension_id, BindingStatus.UNSUPPORTED.value, notes=["no nearby axis-aligned vector dimension line"])

    candidates.sort(key=lambda s: (_axis_distance(center, s), -s.length, s.segment_id))
    best = candidates[0]
    if len(candidates) > 1:
        d0 = _axis_distance(center, candidates[0])
        d1 = _axis_distance(center, candidates[1])
        # If two different line candidates are spatially indistinguishable at
        # the page's own text-height resolution, do not choose by arbitrary ID.
        if abs(d1 - d0) <= calibration.median_word_height_pt * 0.25:
            return DimensionAnchorBinding(
                observation.dimension_id,
                BindingStatus.AMBIGUOUS.value,
                notes=[f"multiple equally plausible dimension lines: {candidates[0].segment_id}, {candidates[1].segment_id}"],
            )

    witness_hits: list[tuple[ObservedGeometrySegment, tuple[float, float]]] = []
    for segment in same_scope:
        if segment.segment_id == best.segment_id:
            continue
        intersection = _intersection_with_perpendicular(best, segment, calibration.witness_endpoint_distance_pt)
        if intersection is not None:
            witness_hits.append((segment, intersection))

    # Collapse multiple vector fragments at effectively the same witness
    # coordinate; vector exporters commonly split one visual line into pieces.
    unique_hits: list[tuple[ObservedGeometrySegment, tuple[float, float]]] = []
    for segment, point in sorted(witness_hits, key=lambda h: (h[1][0], h[1][1], h[0].segment_id)):
        if not any(math.hypot(point[0] - p[0], point[1] - p[1]) <= calibration.witness_endpoint_distance_pt for _, p in unique_hits):
            unique_hits.append((segment, point))

    if best.orientation == DimensionOrientation.HORIZONTAL.value:
        unique_hits.sort(key=lambda h: h[1][0])
    else:
        unique_hits.sort(key=lambda h: h[1][1])

    if len(unique_hits) >= 2:
        first, last = unique_hits[0], unique_hits[-1]
        return DimensionAnchorBinding(
            observation.dimension_id,
            BindingStatus.WITNESS_BOUND.value,
            dimension_line_id=best.segment_id,
            witness_line_ids=(first[0].segment_id, last[0].segment_id),
            endpoints=(first[1], last[1]),
        )
    if len(unique_hits) == 1:
        return DimensionAnchorBinding(
            observation.dimension_id,
            BindingStatus.PARTIAL_WITNESS.value,
            dimension_line_id=best.segment_id,
            witness_line_ids=(unique_hits[0][0].segment_id,),
            notes=["only one witness/extension line resolved"],
        )
    return DimensionAnchorBinding(
        observation.dimension_id,
        BindingStatus.LINE_BOUND.value,
        dimension_line_id=best.segment_id,
        notes=["dimension line resolved but witness/extension endpoints did not"],
    )


def extract_native_dimension_observations(
    page: Any,
    *,
    page_num: int,
    sheet: str = "",
    view_id: str = "",
    view_type: str = DrawingViewType.UNKNOWN.value,
) -> list[DimensionObservation]:
    """Extract typed native-text figured-dimension candidates from a PDF page."""
    words = list(page.get_text("words"))
    observations: list[DimensionObservation] = []
    for index, word in enumerate(words):
        text = str(word[4]).strip()
        preceding = " ".join(str(w[4]) for w in words[max(0, index - 2):index])
        token = classify_dimension_token(text, preceding_context=preceding)
        if not token.is_linear_dimension:
            continue
        bbox = (float(word[0]), float(word[1]), float(word[2]), float(word[3]))
        observations.append(
            DimensionObservation(
                dimension_id=f"native_dim_p{page_num}_{index}",
                source_page=page_num,
                sheet=sheet,
                view_id=view_id,
                view_type=view_type,
                bbox=bbox,
                raw_text=text,
                value=float(token.value),
                unit=str(token.unit),
                authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
                confidence=1.0,
                conflict_state=ConstraintStatus.FULLY_CONSTRAINED.value,
                extraction_method="native_text",
            )
        )
    return observations


def make_ocr_dimension_observation(
    *,
    dimension_id: str,
    raw_text: str,
    bbox_px: tuple[float, float, float, float],
    transform: Optional[RasterCoordinateTransform],
    source_page: int,
    sheet: str = "",
    view_id: str = "",
    view_type: str = DrawingViewType.UNKNOWN.value,
    confidence: float = 0.7,
) -> Optional[DimensionObservation]:
    """Create an OCR candidate only when its coordinate transform is explicit."""
    token = classify_dimension_token(raw_text)
    if not token.is_linear_dimension:
        return None
    if transform is None:
        return None
    bbox = transform.bbox_to_pdf(bbox_px)
    return DimensionObservation(
        dimension_id=dimension_id,
        source_page=source_page,
        sheet=sheet,
        view_id=view_id,
        view_type=view_type,
        bbox=bbox,
        raw_text=raw_text,
        value=float(token.value),
        unit=str(token.unit),
        authority=MeasurementAuthorityType.AI_DETECTED.value,
        confidence=confidence,
        conflict_state=ConstraintStatus.PARTIALLY_CONSTRAINED.value,
        extraction_method="ocr",
    )


def reconcile_candidate_group(
    group_id: str,
    candidates: Sequence[DimensionObservation],
) -> DimensionCandidateGroup:
    """Preserve all candidates while delegating value arbitration to F.13."""
    resolved, status, notes = reconcile_duplicate_observations(candidates)
    return DimensionCandidateGroup(group_id, list(candidates), resolved, status, list(notes))


def apply_anchor_binding(
    observation: DimensionObservation,
    binding: DimensionAnchorBinding,
) -> DimensionObservation:
    """Return a bound copy without mutating the raw evidence object."""
    return DimensionObservation(
        dimension_id=observation.dimension_id,
        source_page=observation.source_page,
        sheet=observation.sheet,
        view_id=observation.view_id,
        view_type=observation.view_type,
        bbox=observation.bbox,
        raw_text=observation.raw_text,
        value=observation.value,
        unit=observation.unit,
        orientation=(
            DimensionOrientation.HORIZONTAL.value
            if binding.endpoints and abs(binding.endpoints[1][0] - binding.endpoints[0][0]) >= abs(binding.endpoints[1][1] - binding.endpoints[0][1])
            else DimensionOrientation.VERTICAL.value
            if binding.endpoints
            else observation.orientation
        ),
        endpoints=binding.endpoints,
        witness_targets=binding.witness_line_ids,
        candidate_geometry_ids=observation.candidate_geometry_ids,
        bound_geometry_id=observation.bound_geometry_id,
        authority=observation.authority,
        confidence=observation.confidence,
        conflict_state=(
            ConstraintStatus.CONFLICT_MANUAL_REVIEW.value
            if binding.status == BindingStatus.AMBIGUOUS.value
            else observation.conflict_state
        ),
        extraction_method=observation.extraction_method,
    )


def evidence_tier_for(
    observation: DimensionObservation,
    binding: Optional[DimensionAnchorBinding],
) -> str:
    if observation.conflict_state == ConstraintStatus.CONFLICT_MANUAL_REVIEW.value:
        return DimensionEvidenceTier.CONFLICT.value
    if observation.extraction_method == "ocr" and binding is None:
        return DimensionEvidenceTier.OCR_ONLY.value
    if binding is None:
        return DimensionEvidenceTier.TEXT_ONLY.value
    if binding.status == BindingStatus.WITNESS_BOUND.value:
        return DimensionEvidenceTier.WITNESS_BOUND.value
    if binding.status in (BindingStatus.LINE_BOUND.value, BindingStatus.PARTIAL_WITNESS.value):
        return DimensionEvidenceTier.LINE_BOUND.value
    if binding.status == BindingStatus.AMBIGUOUS.value:
        return DimensionEvidenceTier.CONFLICT.value
    return DimensionEvidenceTier.TEXT_ONLY.value


def build_chains_from_bound_observations(
    observations: Sequence[DimensionObservation],
    *,
    calibration: DimensionLayoutCalibration,
) -> list[DimensionChain]:
    """Build same-page/view/axis chains from bound or positioned observations."""
    buckets: dict[tuple[int, str, str, int], list[DimensionObservation]] = {}
    for observation in observations:
        if observation.conflict_state == ConstraintStatus.CONFLICT_MANUAL_REVIEW.value:
            continue
        if observation.bbox is None:
            continue
        orientation = observation.orientation
        if orientation == DimensionOrientation.UNKNOWN.value:
            # Native text without anchors remains horizontally row-groupable,
            # preserving the proven F.15 behavior. Vertical semantics require
            # vector anchors rather than guessing from text rotation metadata.
            orientation = DimensionOrientation.HORIZONTAL.value
        center = _bbox_center(observation.bbox)
        axis_coord = center[1] if orientation == DimensionOrientation.HORIZONTAL.value else center[0]
        axis_index = round(axis_coord / calibration.chain_axis_tolerance_pt)
        key = (observation.source_page, observation.view_id, orientation, axis_index)
        buckets.setdefault(key, []).append(observation)

    chains: list[DimensionChain] = []
    for seq, (key, bucket) in enumerate(sorted(buckets.items(), key=lambda kv: kv[0])):
        page_num, view_id, orientation, _ = key
        if orientation == DimensionOrientation.HORIZONTAL.value:
            ordered = sorted(bucket, key=lambda o: _bbox_center(o.bbox)[0] if o.bbox else 0.0)
        else:
            ordered = sorted(bucket, key=lambda o: _bbox_center(o.bbox)[1] if o.bbox else 0.0)
        chains.append(
            DimensionChain(
                chain_id=f"bound_chain_p{page_num}_{seq}",
                view_id=view_id,
                source_page=page_num,
                orientation=orientation,
                observations=ordered,
            )
        )
    return chains


def measure_segment_with_page_scale(
    segment: ObservedGeometrySegment,
    calibration: Optional[ScaleCalibration],
) -> ScaledSegmentMeasurement:
    """Convert PDF-point line length to metres only under a usable same-page scale."""
    if segment.coordinate_space != CoordinateSpace.PDF_POINTS.value:
        return ScaledSegmentMeasurement(segment.segment_id, AuthorityStatus.BLOCKED.value, None, MeasurementAuthorityType.PROVISIONAL.value, ["segment is not in canonical PDF-point coordinates"])
    if calibration is None:
        return ScaledSegmentMeasurement(segment.segment_id, AuthorityStatus.BLOCKED.value, None, MeasurementAuthorityType.PROVISIONAL.value, ["no page scale calibration"])
    if calibration.page_no != segment.source_page:
        return ScaledSegmentMeasurement(segment.segment_id, AuthorityStatus.BLOCKED.value, None, MeasurementAuthorityType.PROVISIONAL.value, ["scale calibration belongs to a different page"])
    status = measurement_authority_for_page_scale(calibration)
    if status == AuthorityStatus.BLOCKED.value or calibration.px_per_m <= 0:
        return ScaledSegmentMeasurement(segment.segment_id, AuthorityStatus.BLOCKED.value, None, MeasurementAuthorityType.PROVISIONAL.value, list(calibration.issues))
    return ScaledSegmentMeasurement(
        segment.segment_id,
        status,
        segment.length / calibration.px_per_m,
        MeasurementAuthorityType.PDF_SCALED.value,
        list(calibration.issues),
    )


def extract_dimension_evidence_bundle(
    page: Any,
    *,
    page_num: int,
    sheet: str = "",
    view_id: str = "",
    view_type: str = DrawingViewType.UNKNOWN.value,
    ocr_candidates: Iterable[DimensionObservation] = (),
) -> DimensionEvidenceBundle:
    """Extract native/vector evidence, bind candidates, preserve OCR, and form chains."""
    layout = calibrate_dimension_layout(page)
    segments = extract_vector_segments(page, page_num=page_num, view_id=view_id)
    native = extract_native_dimension_observations(
        page,
        page_num=page_num,
        sheet=sheet,
        view_id=view_id,
        view_type=view_type,
    )
    bindings: list[DimensionAnchorBinding] = []
    bound_native: list[DimensionObservation] = []
    for observation in native:
        binding = bind_observation_to_vector_geometry(observation, segments, layout)
        bindings.append(binding)
        bound_native.append(apply_anchor_binding(observation, binding))

    observations = bound_native + list(ocr_candidates)
    chains = build_chains_from_bound_observations(bound_native, calibration=layout)
    return DimensionEvidenceBundle(
        observations=observations,
        observed_geometry=segments,
        bindings=bindings,
        chains=chains,
    )
