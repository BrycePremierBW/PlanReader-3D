"""G17 physical-opening existence and local instance identity authority.

A positive existence result is available only from producer-proven visible
native PDF geometry. Caller-published structural semantic labels remain useful
for fail-closed diagnostics, but cannot self-certify a physical opening.

Physical-opening identity is deliberately local to one authenticated source
scope. It is resolved only by independently re-proving G17 existence for both
selectors and comparing the producer-owned existence records. Dimensions,
host binding, universe completeness, physical voids, deductions and commercial
publication remain separate downstream authorities.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Optional, Sequence

import cv2
import numpy as np

from pb_migration_contracts import EvidenceAtom, EvidenceResolutionStatus, stable_contract_id
from pb_plan_opening_detection_v171 import (
    Segment as LegacyPlanSegment,
    detect_door_candidates,
    detect_gap_candidates,
    detect_wall_lines,
    detect_window_candidates,
)
from pb_plan_opening_detection_indexed_v172 import (
    detect_door_candidates_indexed,
    detect_gap_candidates_indexed,
)
from pb_source_observation_authority import (
    NativePageImagePlacement,
    ObservationSelector,
    SourceObservationAuthority,
    SourceObservationAuthorityResult,
    SourceObservationRecord,
)
from pb_source_visibility_authority import (
    NATIVE_PDF_VISIBLE_SEGMENT,
    RASTER_OPENING_PRIMITIVE_RENDER_DPI,
    RASTER_PDF_VISIBLE_SEGMENT,
    VISIBILITY_RECEIPT_UNAVAILABLE,
    SourceVisibilityAuthority,
)
from pb_raster_opening_source_primitives import (
    BAND_MAX_THICKNESS_PT as RASTER_BAND_MAX_THICKNESS_PT,
    BAND_MIN_ASPECT as RASTER_BAND_MIN_ASPECT,
    BAND_MIN_RUN_PT as RASTER_BAND_MIN_RUN_PT,
    LINE_THRESHOLD as RASTER_LINE_THRESHOLD,
    MASS_THRESHOLD as RASTER_MASS_THRESHOLD,
    POCHE_MIN_PT as RASTER_POCHE_MIN_PT,
    RASTER_LINE_RUN,
    RASTER_THIN_INK_RUN,
    RASTER_WALL_BAND_END,
    RASTER_WALL_BAND_FACE,
)


PHYSICAL_OPENING_EXISTS = "physical_opening_exists"
PHYSICAL_OPENING_EXISTENCE_UNRESOLVED = "physical_opening_existence_unresolved"
PHYSICAL_OPENING_IDENTITY_UNRESOLVED = "physical_opening_identity_unresolved"
PHYSICAL_OPENING_IDENTITIES_DISTINCT = "physical_opening_identities_distinct"
PHYSICAL_OPENING_IDENTITY_SCOPE_MISMATCH = "physical_opening_identity_scope_mismatch"
PHYSICAL_OPENING_IDENTITY_EXISTENCE_REQUIRED = "physical_opening_identity_existence_required"
PHYSICAL_OPENING_IDENTITY_RESOLVED = "physical_opening_identity_resolved"
PHYSICAL_OPENING_DISPOSITION_OPENING_SUPPORT = "opening_support"
PHYSICAL_OPENING_DISPOSITION_CANDIDATE = "candidate_unresolved"
PHYSICAL_OPENING_DISPOSITION_NO_CANDIDATE = "no_candidate_in_covered_path"
PHYSICAL_OPENING_DISPOSITION_CONFLICT = "conflict"
PHYSICAL_OPENING_DISPOSITION_UNRESOLVED = "unresolved"

AUTHORITATIVE_PHYSICAL_OPENING_SEMANTICS_UNAVAILABLE = (
    "authoritative_physical_opening_semantics_unavailable"
)
AUTHORITATIVE_PHYSICAL_OPENING_IDENTITY_UNAVAILABLE = (
    "authoritative_physical_opening_identity_unavailable"
)
MISSING_PHYSICAL_OPENING_SEMANTIC_CAPABILITY = (
    "independent source-native physical opening instance semantic producer"
)

JAMB_BOUNDED_TWO_FACE_INTERRUPTION = "jamb_bounded_two_face_interruption"
RASTER_FRAMED_WALL_BAND_INTERRUPTION = "raster_framed_wall_band_interruption"
RASTER_DOOR_SWING_WALL_BAND_INTERRUPTION = (
    "raster_door_swing_wall_band_interruption"
)
RASTER_DOOR_SWING_AMBIGUOUS = "raster_door_swing_ambiguous"

# Reviewed raster framed-opening authority constants. These are generic paper
# units / relative geometry tests from the independently validated #1276
# shadow rule; no drawing scale, project identity, coordinate, or expected
# quantity enters them.
_RASTER_END_WINDOW_PT = 1.5
_RASTER_END_COVERAGE = 0.8
_RASTER_CLEAN_GAP_MAX_PARTIAL = 0.15
_RASTER_THICKNESS_OVERLAP = 0.8
_RASTER_THICKNESS_TOLERANCE = 0.35
_RASTER_MIN_OPENING_GAP_PT = 8.0
_RASTER_MIN_GAP_THICKNESS_RATIO = 2.0
_RASTER_LINE_COVERAGE = 0.8
_RASTER_MIN_FRAME_LINES = 2
_RASTER_LINE_ROW_PAD_PT = 0.5
_RASTER_SWING_ARC_RADIUS_TOLERANCE = 0.15
_RASTER_SWING_ARC_MIN_COVERAGE = 0.8
_RASTER_SWING_ARC_SAMPLE_STEP_DEG = 2
_RASTER_SWING_LEAF_MIN_COVERAGE = 0.9
_RASTER_SWING_LEAF_JAMB_PAD_PT = 1.5
GAP_CORROBORATED_DOOR_JAMB_LEAF = "gap_corroborated_door_jamb_leaf"
GAP_CORROBORATED_WINDOW_JAMB_PAIR = "gap_corroborated_window_jamb_pair"
WALL_FACE_INTERRUPTION_KIND = "wall_face_interruption"
OPENING_JAMB_BOUNDARY_KIND = "opening_jamb_boundary"
WEAK_PHYSICAL_OPENING_CANDIDATE_KINDS = frozenset(
    {"opening_swing_arc", "wall_gap_candidate"}
)

STRUCTURAL_OPENING_CANDIDATE = "structural_opening_candidate"
STRUCTURAL_OPENING_EXISTENCE_RESOLVED = "structural_opening_existence_resolved"
AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES = "ambiguous_physical_opening_candidates"
INSUFFICIENT_INDEPENDENT_SOURCE_LINEAGE = "insufficient_independent_source_lineage"
INVALID_STRUCTURAL_GEOMETRY = "invalid_structural_geometry"
SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE = "snapshot_observation_integrity_failure"
VISIBLE_WALL_CONTINUATION_REQUIRED = "visible_wall_continuation_required"
VISIBLE_SOURCE_AUTHORITY_REQUIRED = "visible_source_authority_required"
PHYSICAL_OPENING_CANDIDATE_CLOSURE_UNRESOLVED = "physical_opening_candidate_closure_unresolved"
PHYSICAL_OPENING_CANDIDATE_CLOSURE_RESOLVED = "physical_opening_candidate_closure_resolved"

# Numeric equality only. These are not proximity/search radii and cannot create
# candidate membership between otherwise unrelated primitives.
_COORD_EQ_ABS_TOL = 1e-6
_PARALLEL_REL_TOL = 1e-9
_VIEWPORT_SCOPED_PRODUCER_SEAL = object()
OPENING_CANDIDATE_OUTSIDE_FLOOR_PLAN_SCOPE = "opening_candidate_outside_floor_plan_scope"
OPENING_CANDIDATE_VIEWPORT_SCOPE_UNRESOLVED = "opening_candidate_viewport_scope_unresolved"


@dataclass(frozen=True)
class CandidateSemanticOpening:
    """Producer-snapshot-owned candidate, not yet a broader opening identity."""

    candidate_id: str
    source_observation_ids: tuple[str, ...]
    source_lineage_root_ids: tuple[str, ...]
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    viewport_id: Optional[str]
    structural_pattern: str
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PhysicalOpeningExistenceRecord:
    """Narrow resolved proposition: one local physical opening exists."""

    record_id: str
    source_observation_ids: tuple[str, ...]
    source_lineage_root_ids: tuple[str, ...]
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    viewport_id: Optional[str]
    semantic_class: str
    status: EvidenceResolutionStatus
    proposition: str
    structural_pattern: str
    diagnostic_confidence: float
    blocking_reasons: tuple[str, ...]
    structural_reason_codes: tuple[str, ...]
    producer_method: str
    producer_version: str
    producer_generation: int
    aperture_bbox_pt: Optional[tuple[float, float, float, float]] = None


@dataclass(frozen=True)
class PhysicalOpeningExistenceResult:
    """Fail-closed result for the physical-opening existence proposition."""

    status: EvidenceResolutionStatus
    proposition: Optional[str]
    physical_opening_existence: str
    reason_codes: tuple[str, ...]
    source_observation: Optional[SourceObservationAuthorityResult] = None
    candidate: Optional[CandidateSemanticOpening] = None
    existence_record: Optional[PhysicalOpeningExistenceRecord] = None
    missing_upstream_capability: Optional[str] = None
    opposing_evidence_atoms: tuple[EvidenceAtom, ...] = ()


@dataclass(frozen=True)
class PhysicalOpeningDispositionResult:
    """Disposition of one visible observation under covered opening paths.

    no_candidate_in_covered_path is deliberately not a proof that the
    observation can never participate in any opening representation. It means
    only that the producer examined the observation against the currently
    registered structural paths and found no candidate membership.
    """

    status: EvidenceResolutionStatus
    disposition: str
    reason_codes: tuple[str, ...]
    candidate_ids: tuple[str, ...] = ()
    existence_record: Optional[PhysicalOpeningExistenceRecord] = None


@dataclass(frozen=True)
class PhysicalOpeningCandidateClosureResult:
    """Producer-derived closure of opening-like candidates on one source page."""

    status: EvidenceResolutionStatus
    page_id: Optional[str]
    candidate_universe_complete: bool
    raw_candidate_count: int
    resolved_candidate_count: int
    unresolved_candidate_ids: tuple[str, ...]
    unresolved_observation_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PhysicalOpeningCandidateStructureResult:
    """Read-only view of the candidates discovered on one source-visible page.

    Diagnostic seam.  ``candidates`` are exactly the objects
    ``classify_disposition`` / ``prove_existence`` / ``assess_visible_candidate_closure``
    already use for this page; nothing here is proof that any of them is an
    opening, that two of them are or are not the same opening, or a count.  The
    status is ``CANDIDATE`` when the page was enumerated (never
    ``CORROBORATED``) and ``ABSTAINED`` / ``CONFLICT`` when it could not be.
    """

    status: EvidenceResolutionStatus
    page_id: Optional[str]
    candidates: tuple[CandidateSemanticOpening, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PhysicalOpeningIdentityResult:
    """Fail-closed result for whether two observations denote one opening."""

    status: EvidenceResolutionStatus
    physical_opening_identity: str
    proven_same: bool
    reason_codes: tuple[str, ...]
    left_source_observation: Optional[SourceObservationAuthorityResult] = None
    right_source_observation: Optional[SourceObservationAuthorityResult] = None
    missing_upstream_capability: Optional[str] = None


@dataclass(frozen=True)
class _RasterBandPair:
    """One raster wall-band interruption in its horizontal analysis frame."""

    a: tuple[int, int, int, int]
    b: tuple[int, int, int, int]
    gap_x0: int
    gap_x1: int
    row0: int
    row1: int
    thickness_a: int
    thickness_b: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _RasterDoorSwingSolution:
    hinge_end: str
    hinge_x: int
    side: int
    face_y: int
    direction: int
    radius_px: int
    perpendicular_radius_px: int
    arc_coverage: float
    leaf_coverage: float


@dataclass(frozen=True)
class _FaceBreak:
    first: SourceObservationRecord
    second: SourceObservationRecord
    gap_start: float
    gap_end: float
    start_point: tuple[float, float]
    end_point: tuple[float, float]
    direction: tuple[float, float]


def _dedupe_reason_codes(*groups: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for group in groups:
        for reason in group:
            clean = str(reason or "").strip()
            if clean and clean not in result:
                result.append(clean)
    return tuple(result)


def _source_failure_status(*results: SourceObservationAuthorityResult) -> EvidenceResolutionStatus:
    if any(result.status is EvidenceResolutionStatus.CONFLICT for result in results):
        return EvidenceResolutionStatus.CONFLICT
    return EvidenceResolutionStatus.ABSTAINED


def _line_geometry(record: SourceObservationRecord) -> Optional[tuple[float, float, float, float]]:
    if len(record.geometry) != 4:
        return None
    values = tuple(float(value) for value in record.geometry)
    if not all(math.isfinite(value) for value in values):
        return None
    x1, y1, x2, y2 = values
    if math.hypot(x2 - x1, y2 - y1) <= _COORD_EQ_ABS_TOL:
        return None
    return (x1, y1, x2, y2)


def _point_close(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return (
        abs(left[0] - right[0]) <= _COORD_EQ_ABS_TOL
        and abs(left[1] - right[1]) <= _COORD_EQ_ABS_TOL
    )


def _segment_matches(
    record: SourceObservationRecord,
    first: tuple[float, float],
    second: tuple[float, float],
) -> bool:
    line = _line_geometry(record)
    if line is None:
        return False
    start = (line[0], line[1])
    end = (line[2], line[3])
    return (
        _point_close(start, first) and _point_close(end, second)
    ) or (
        _point_close(start, second) and _point_close(end, first)
    )


def _parallel(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    ldx, ldy = left[2] - left[0], left[3] - left[1]
    rdx, rdy = right[2] - right[0], right[3] - right[1]
    llen = math.hypot(ldx, ldy)
    rlen = math.hypot(rdx, rdy)
    if llen <= _COORD_EQ_ABS_TOL or rlen <= _COORD_EQ_ABS_TOL:
        return False
    return abs(ldx * rdy - ldy * rdx) <= _PARALLEL_REL_TOL * llen * rlen


def _canonical_direction(line: tuple[float, float, float, float]) -> tuple[float, float]:
    dx, dy = line[2] - line[0], line[3] - line[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    if ux < -_COORD_EQ_ABS_TOL or (
        abs(ux) <= _COORD_EQ_ABS_TOL and uy < 0.0
    ):
        ux, uy = -ux, -uy
    return (ux, uy)


def _projection(point: tuple[float, float], direction: tuple[float, float]) -> float:
    return point[0] * direction[0] + point[1] * direction[1]


def _cross(left: tuple[float, float], right: tuple[float, float]) -> float:
    return left[0] * right[1] - left[1] * right[0]


def _collinear(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    if not _parallel(left, right):
        return False
    direction = _canonical_direction(left)
    delta = (right[0] - left[0], right[1] - left[1])
    return abs(_cross(direction, delta)) <= _COORD_EQ_ABS_TOL


def _endpoint_at_projection(
    line: tuple[float, float, float, float],
    direction: tuple[float, float],
    target: float,
) -> Optional[tuple[float, float]]:
    first = (line[0], line[1])
    second = (line[2], line[3])
    if abs(_projection(first, direction) - target) <= _COORD_EQ_ABS_TOL:
        return first
    if abs(_projection(second, direction) - target) <= _COORD_EQ_ABS_TOL:
        return second
    return None


def _candidate_collinear_record_pairs(
    records: tuple[SourceObservationRecord, ...],
    *,
    line_geometries: Optional[
        Sequence[Optional[tuple[float, float, float, float]]]
    ] = None,
) -> tuple[tuple[int, int], ...]:
    """Return a conservative broad-phase superset of collinear record pairs.

    Exact membership is still decided by _face_break. This index only removes
    pairs that cannot satisfy the existing parallel + collinearity tolerances.
    Pair indexes are returned in the same lexicographic order as the historical
    nested all-pairs loop so downstream break ordering stays deterministic.
    """

    if len(records) < 2:
        return ()

    lines = (
        tuple(line_geometries)
        if line_geometries is not None
        else tuple(_line_geometry(record) for record in records)
    )
    if len(lines) != len(records):
        raise ValueError("line_geometries must align with records")

    indexed: list[tuple[int, float, float, float]] = []
    max_radius = 0.0
    for index, line in enumerate(lines):
        if line is None:
            continue
        direction = _canonical_direction(line)
        angle = math.atan2(direction[1], direction[0]) % math.pi
        offset = _cross(direction, (line[0], line[1]))
        radius = max(
            math.hypot(line[0], line[1]),
            math.hypot(line[2], line[3]),
        )
        max_radius = max(max_radius, radius)
        indexed.append((index, angle, offset, radius))

    if len(indexed) < 2:
        return ()

    max_angle_delta = math.asin(min(1.0, _PARALLEL_REL_TOL))
    angle_width = max(max_angle_delta * 4.0, 1e-12)
    angle_bucket_count = max(1, int(math.ceil(math.pi / angle_width)))
    offset_width = max(
        _COORD_EQ_ABS_TOL * 4.0,
        (_COORD_EQ_ABS_TOL + max_radius * max_angle_delta) * 4.0,
    )

    def angle_bin(angle: float) -> int:
        return int(math.floor(angle / angle_width)) % angle_bucket_count

    def offset_bin(offset: float) -> int:
        return math.floor(offset / offset_width)

    buckets: dict[tuple[int, int], list[int]] = {}
    pairs: set[tuple[int, int]] = set()

    for index, angle, offset, _radius in indexed:
        a_bin = angle_bin(angle)
        o_bin = offset_bin(offset)
        candidate_indexes: set[int] = set()
        for da in (-1, 0, 1):
            neighbor_angle = (a_bin + da) % angle_bucket_count
            for do in (-1, 0, 1):
                candidate_indexes.update(
                    buckets.get((neighbor_angle, o_bin + do), ())
                )

        line = lines[index]
        assert line is not None
        for prior in candidate_indexes:
            prior_line = lines[prior]
            assert prior_line is not None
            if _parallel(prior_line, line) and _collinear(prior_line, line):
                pairs.add((prior, index) if prior < index else (index, prior))

        buckets.setdefault((a_bin, o_bin), []).append(index)

    return tuple(sorted(pairs))

def _face_break(
    first: SourceObservationRecord,
    second: SourceObservationRecord,
    *,
    first_line: Optional[tuple[float, float, float, float]] = None,
    second_line: Optional[tuple[float, float, float, float]] = None,
) -> Optional[_FaceBreak]:
    if first_line is None:
        first_line = _line_geometry(first)
    if second_line is None:
        second_line = _line_geometry(second)
    if first_line is None or second_line is None or not _collinear(first_line, second_line):
        return None
    direction = _canonical_direction(first_line)
    first_values = sorted(
        (_projection((first_line[0], first_line[1]), direction),
         _projection((first_line[2], first_line[3]), direction))
    )
    second_values = sorted(
        (_projection((second_line[0], second_line[1]), direction),
         _projection((second_line[2], second_line[3]), direction))
    )
    if first_values[0] <= second_values[0]:
        left_record, left_line, left_values = first, first_line, first_values
        right_record, right_line, right_values = second, second_line, second_values
    else:
        left_record, left_line, left_values = second, second_line, second_values
        right_record, right_line, right_values = first, first_line, first_values
    gap_start = left_values[1]
    gap_end = right_values[0]
    if gap_end - gap_start <= _COORD_EQ_ABS_TOL:
        return None
    start_point = _endpoint_at_projection(left_line, direction, gap_start)
    end_point = _endpoint_at_projection(right_line, direction, gap_end)
    if start_point is None or end_point is None:
        return None
    return _FaceBreak(
        first=left_record,
        second=right_record,
        gap_start=gap_start,
        gap_end=gap_end,
        start_point=start_point,
        end_point=end_point,
        direction=direction,
    )


def _same_gap(left: _FaceBreak, right: _FaceBreak) -> bool:
    if abs(left.gap_start - right.gap_start) > _COORD_EQ_ABS_TOL:
        return False
    if abs(left.gap_end - right.gap_end) > _COORD_EQ_ABS_TOL:
        return False
    dot = left.direction[0] * right.direction[0] + left.direction[1] * right.direction[1]
    return abs(abs(dot) - 1.0) <= _PARALLEL_REL_TOL


def _distinct_parallel_axes(left: _FaceBreak, right: _FaceBreak) -> bool:
    delta = (
        right.start_point[0] - left.start_point[0],
        right.start_point[1] - left.start_point[1],
    )
    return abs(_cross(left.direction, delta)) > _COORD_EQ_ABS_TOL


def _canonical_line(record: SourceObservationRecord) -> tuple[tuple[float, float], tuple[float, float]]:
    line = _line_geometry(record)
    if line is None:
        return ((0.0, 0.0), (0.0, 0.0))
    first = (round(line[0], 6), round(line[1], 6))
    second = (round(line[2], 6), round(line[3], 6))
    return tuple(sorted((first, second)))  # type: ignore[return-value]



def _physical_opening_geometry_identity(
    candidate: CandidateSemanticOpening,
    records: Sequence[SourceObservationRecord],
) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
    """Return the producer-independent physical geometry key for one opening.

    Evidence/snapshot identifiers remain provenance, not physical identity.
    Positive physical-opening candidates are supported by source-visible line
    geometry; every declared support observation must therefore resolve to one
    finite line before a stable physical identity can be published.
    """

    support_ids = {str(value) for value in candidate.source_observation_ids}
    support_records = tuple(
        record
        for record in records
        if str(record.observation_id) in support_ids
    )
    if {str(record.observation_id) for record in support_records} != support_ids:
        return ()
    geometry = tuple(
        sorted({_canonical_line(record) for record in support_records})
    )
    if (
        not geometry
        or any(
            first == second == (0.0, 0.0)
            for first, second in geometry
        )
    ):
        return ()
    return geometry


def _raster_px(value_pt: float, dpi: int, *, minimum: int = 1) -> int:
    return max(int(minimum), int(round(float(value_pt) * float(dpi) / 72.0)))


def _raster_odd(value: int) -> int:
    value = int(value)
    return value if value % 2 == 1 else value + 1


def _raster_pt(value_px: float, dpi: int) -> float:
    return round(float(value_px) * 72.0 / float(dpi), 6)


def _raster_box_pt(
    box_px: Sequence[float],
    dpi: int,
) -> tuple[float, float, float, float]:
    values = tuple(float(value) for value in box_px)
    if len(values) != 4:
        raise ValueError("raster box must contain four coordinates")
    return (
        _raster_pt(values[0], dpi),
        _raster_pt(values[1], dpi),
        _raster_pt(values[2] + 1.0, dpi),
        _raster_pt(values[3] + 1.0, dpi),
    )


def _raster_geometry_pt(
    geometry_px: Sequence[float],
    dpi: int,
) -> tuple[float, float, float, float]:
    values = tuple(_raster_pt(value, dpi) for value in geometry_px)
    if len(values) != 4:
        raise ValueError("raster geometry must contain four coordinates")
    return values  # type: ignore[return-value]


def _raster_to_page_box(
    box: tuple[int, int, int, int],
    axis: str,
) -> tuple[int, int, int, int]:
    if axis == "horizontal":
        return box
    return (box[1], box[0], box[3], box[2])


def _raster_axis_registration_scales(
    axis: str,
    registration_scale: tuple[float, float],
) -> tuple[float, float]:
    sx, sy = (float(value) for value in registration_scale)
    if (
        not math.isfinite(sx)
        or not math.isfinite(sy)
        or sx <= 0.0
        or sy <= 0.0
    ):
        raise ValueError("registration_scale must contain positive finite values")
    if axis == "horizontal":
        return sx, sy
    if axis == "vertical":
        return sy, sx
    raise ValueError("axis must be horizontal or vertical")


def _raster_scaled_px(
    value_pt: float,
    dpi: int,
    scale: float,
    *,
    minimum: int = 1,
) -> int:
    if not math.isfinite(float(scale)) or float(scale) <= 0.0:
        raise ValueError("registration scale must be positive and finite")
    return max(
        int(minimum),
        int(round(float(value_pt) * float(dpi) / 72.0 * float(scale))),
    )


def _raster_band_boxes(
    thick: np.ndarray,
    *,
    dpi: int,
    axis: str,
    registration_scale: tuple[float, float] = (1.0, 1.0),
) -> tuple[tuple[int, int, int, int], ...]:
    """Return reviewed solid wall-band pieces in page pixel coordinates."""

    work = thick if axis == "horizontal" else np.ascontiguousarray(thick.T)
    along_scale, cross_scale = _raster_axis_registration_scales(
        axis,
        registration_scale,
    )
    run = _raster_odd(
        _raster_scaled_px(RASTER_BAND_MIN_RUN_PT, dpi, along_scale)
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (run, 1))
    band = cv2.morphologyEx(work, cv2.MORPH_OPEN, kernel)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        band,
        connectivity=8,
    )
    solid = _raster_scaled_px(RASTER_POCHE_MIN_PT, dpi, cross_scale)
    tmax = _raster_scaled_px(
        RASTER_BAND_MAX_THICKNESS_PT,
        dpi,
        cross_scale,
    )
    boxes: list[tuple[int, int, int, int]] = []
    for index in range(1, int(count)):
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        if (
            height < solid
            or height > tmax
            or (width / along_scale)
            < RASTER_BAND_MIN_ASPECT * (height / cross_scale)
        ):
            continue
        analysis_box = (x, y, x + width - 1, y + height - 1)
        boxes.append(_raster_to_page_box(analysis_box, axis))
    return tuple(sorted(set(boxes)))


def _raster_analysis_box(
    page_box: tuple[int, int, int, int],
    axis: str,
) -> tuple[int, int, int, int]:
    if axis == "horizontal":
        return page_box
    return (page_box[1], page_box[0], page_box[3], page_box[2])


def _raster_end_interval(
    work_thick: np.ndarray,
    piece_box: tuple[int, int, int, int],
    *,
    at_high_end: bool,
    window: int,
) -> Optional[tuple[int, int]]:
    x0, y0, x1, y1 = piece_box
    if at_high_end:
        xs = max(x1 - window + 1, 0), x1 + 1
    else:
        xs = x0, min(x0 + window, work_thick.shape[1])
    sub = work_thick[y0 : y1 + 1, xs[0] : xs[1]]
    if sub.size == 0:
        return None
    coverage = sub.mean(axis=1)
    rows = np.where(coverage >= _RASTER_END_COVERAGE)[0]
    if rows.size == 0:
        return None
    return y0 + int(rows.min()), y0 + int(rows.max())


def _raster_pair_flanks(
    work_thick: np.ndarray,
    boxes: Sequence[tuple[int, int, int, int]],
    *,
    dpi: int,
    along_scale: float = 1.0,
    cross_scale: float = 1.0,
) -> tuple[_RasterBandPair, ...]:
    """Retain every owner of the first source-occupied continuation column.

    Source row occupancy proves adjacency, but an arbitrary bounding-box hit
    cannot prove ownership. Multiple owner envelopes remain explicit ambiguous
    hypotheses; input order must never choose which one becomes an opening.
    """

    window = _raster_scaled_px(_RASTER_END_WINDOW_PT, dpi, along_scale)
    min_gap_floor = _raster_scaled_px(
        _RASTER_MIN_OPENING_GAP_PT,
        dpi,
        along_scale,
    )
    width = work_thick.shape[1]
    boxes = tuple(sorted(tuple(int(value) for value in box) for box in boxes))
    box_array = np.asarray(tuple(boxes), dtype=np.int64).reshape(-1, 4)
    pairs: list[_RasterBandPair] = []
    for a in boxes:
        rows = _raster_end_interval(
            work_thick,
            a,
            at_high_end=True,
            window=window,
        )
        if rows is None:
            continue
        r0, r1 = rows
        start = a[2] + 1
        if start >= width:
            continue
        profile = work_thick[r0 : r1 + 1, :].mean(axis=0)
        tail = profile[start:]
        solid_hits = np.where(tail >= _RASTER_END_COVERAGE)[0]
        partial_hits = np.where(tail > _RASTER_CLEAN_GAP_MAX_PARTIAL)[0]
        if solid_hits.size == 0:
            continue
        position = start + int(solid_hits[0])
        hit = np.where(
            (box_array[:, 0] <= position)
            & (position <= box_array[:, 2])
            & ~((box_array[:, 3] < r0) | (box_array[:, 1] > r1))
        )[0]
        if hit.size == 0:
            continue
        for partner_index in hit:
            partner = tuple(int(value) for value in box_array[int(partner_index)])
            reasons: list[str] = []
            if hit.size > 1:
                reasons.append("raster_continuation_owner_ambiguous")
            if partial_hits.size and start + int(partial_hits[0]) < position:
                reasons.append("raster_gap_not_clean")

            b_rows = _raster_end_interval(
                work_thick, partner, at_high_end=False, window=window)
            if b_rows is None:
                continue
            c0, c1 = max(r0, b_rows[0]), min(r1, b_rows[1])
            thickness_a = r1 - r0 + 1
            thickness_b = b_rows[1] - b_rows[0] + 1
            if (
                c1 < c0
                or (c1 - c0 + 1)
                < _RASTER_THICKNESS_OVERLAP * min(thickness_a, thickness_b)
                or abs(thickness_a - thickness_b)
                > _RASTER_THICKNESS_TOLERANCE * max(thickness_a, thickness_b)
            ):
                reasons.append("raster_flanks_not_collinear_bands")

            gap_x0 = a[2] + 1
            gap_x1 = position - 1
            gap = gap_x1 - gap_x0 + 1
            thickness = max(min(thickness_a, thickness_b), 1)
            relative_gap_floor = int(math.ceil(
                _RASTER_MIN_GAP_THICKNESS_RATIO * float(thickness)
                * float(along_scale) / float(cross_scale)))
            if gap < max(min_gap_floor, relative_gap_floor):
                reasons.append("raster_gap_too_small")
            if gap < 1:
                continue
            pairs.append(_RasterBandPair(
                a=a, b=partner, gap_x0=gap_x0, gap_x1=gap_x1,
                row0=c0 if c1 >= c0 else r0, row1=c1 if c1 >= c0 else r1,
                thickness_a=thickness_a, thickness_b=thickness_b,
                reasons=tuple(dict.fromkeys(reasons))))
    return tuple(pairs)


def _raster_frame_line_groups(
    line_mask: np.ndarray,
    pair: _RasterBandPair,
    *,
    dpi: int,
    cross_scale: float = 1.0,
) -> tuple[tuple[int, int], ...]:
    pad = _raster_scaled_px(
        _RASTER_LINE_ROW_PAD_PT,
        dpi,
        cross_scale,
        minimum=1,
    )
    r0 = max(pair.row0 - pad, 0)
    r1 = min(pair.row1 + pad, line_mask.shape[0] - 1)
    region = line_mask[r0 : r1 + 1, pair.gap_x0 : pair.gap_x1 + 1]
    if region.size == 0:
        return ()
    covered = region.mean(axis=1) >= _RASTER_LINE_COVERAGE
    groups: list[tuple[int, int]] = []
    start: Optional[int] = None
    for index, flag in enumerate(covered.tolist() + [False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            groups.append((r0 + start, r0 + index - 1))
            start = None
    if len(groups) < _RASTER_MIN_FRAME_LINES:
        return ()
    return tuple(groups)


def _raster_wall_face_continues(
    line_mask: np.ndarray,
    pair: _RasterBandPair,
) -> bool:
    for row in (pair.row0, pair.row1):
        if (
            0 <= row < line_mask.shape[0]
            and float(
                line_mask[row, pair.gap_x0 : pair.gap_x1 + 1].mean()
            )
            >= _RASTER_LINE_COVERAGE
        ):
            return True
    return False


def _raster_hairline_mask(
    line_mask: np.ndarray,
    thick: np.ndarray,
) -> np.ndarray:
    """Source ink that is neither solid wall poche nor touching it."""

    halo = cv2.dilate(thick, np.ones((3, 3), np.uint8))
    return (line_mask & (halo == 0)).astype(np.uint8)


def _raster_swing_perpendicular_scale_ratio(
    gap_box_pt: tuple[float, float, float, float],
    axis: str,
    placements: Sequence[NativePageImagePlacement],
) -> Optional[float]:
    """Return the producer-proved affine scale ratio for one raster gap.

    A source-image circle may render as an ellipse when the PDF placement uses
    different X/Y scales. The ratio is derived only from the exact embedded
    image's intrinsic pixels and source-page placement. Competing transforms
    fail closed.
    """

    x0, y0, x1, y1 = (float(value) for value in gap_box_pt)
    matches: list[float] = []
    tol = 1e-6
    for placement in placements:
        bx0, by0, bx1, by1 = placement.bbox_pt
        if not (
            bx0 - tol <= x0
            and x1 <= bx1 + tol
            and by0 - tol <= y0
            and y1 <= by1 + tol
        ):
            continue
        sx = (bx1 - bx0) / float(placement.pixel_width)
        sy = (by1 - by0) / float(placement.pixel_height)
        if (
            not math.isfinite(sx)
            or not math.isfinite(sy)
            or sx <= 0.0
            or sy <= 0.0
        ):
            continue
        ratio = sy / sx if axis == "horizontal" else sx / sy
        if math.isfinite(ratio) and ratio > 0.0:
            matches.append(float(ratio))
    if not matches:
        return None
    first = matches[0]
    if any(
        not math.isclose(value, first, rel_tol=1e-6, abs_tol=1e-9)
        for value in matches[1:]
    ):
        return None
    return first


def _raster_swing_arc_coverage(
    thin_mask: np.ndarray,
    center: tuple[float, float],
    radius: float,
    perpendicular_radius: float,
    *,
    side: int,
    direction: int,
) -> float:
    """Reviewed quarter-arc coverage over producer-owned raster evidence."""

    height, width = thin_mask.shape
    hits = 0
    total = 0
    cx, cy = center
    for degrees in range(0, 91, _RASTER_SWING_ARC_SAMPLE_STEP_DEG):
        theta = math.radians(degrees)
        x = cx + direction * radius * math.cos(theta)
        y = cy + side * perpendicular_radius * math.sin(theta)
        xi, yi = int(round(x)), int(round(y))
        total += 1
        if (
            1 <= xi < width - 1
            and 1 <= yi < height - 1
            and thin_mask[yi - 1 : yi + 2, xi - 1 : xi + 2].any()
        ):
            hits += 1
    return hits / total if total else 0.0


def _raster_door_swing_solutions(
    thin_mask: np.ndarray,
    pair: _RasterBandPair,
    *,
    dpi: int,
    perpendicular_scale_ratio: float,
    along_scale: float = 1.0,
) -> tuple[_RasterDoorSwingSolution, ...]:
    """Return every reviewed leaf + quarter-arc configuration for one clean gap.

    Multiple valid configurations are intentionally retained so G17 can report
    ambiguity instead of selecting a nearest/first hinge.
    """

    gap = pair.gap_x1 - pair.gap_x0 + 1
    pad = _raster_scaled_px(
        _RASTER_SWING_LEAF_JAMB_PAD_PT,
        dpi,
        along_scale,
    )
    found: list[_RasterDoorSwingSolution] = []
    for hinge_end, hinge_x, direction in (
        ("low", pair.gap_x0, 1),
        ("high", pair.gap_x1, -1),
    ):
        for side, face_y in ((-1, pair.row0), (1, pair.row1)):
            best: Optional[tuple[float, int, int]] = None
            low_radius = max(
                int(math.ceil(
                    gap * (1.0 - _RASTER_SWING_ARC_RADIUS_TOLERANCE)
                )),
                2,
            )
            high_radius = int(math.floor(
                gap * (1.0 + _RASTER_SWING_ARC_RADIUS_TOLERANCE)
            ))
            for radius in range(low_radius, high_radius + 1):
                perpendicular_radius = max(
                    int(round(float(radius) * perpendicular_scale_ratio)),
                    2,
                )
                coverage = _raster_swing_arc_coverage(
                    thin_mask,
                    (float(hinge_x), float(face_y)),
                    float(radius),
                    float(perpendicular_radius),
                    side=side,
                    direction=direction,
                )
                if best is None or coverage > best[0]:
                    best = (coverage, radius, perpendicular_radius)
            if best is None or best[0] < _RASTER_SWING_ARC_MIN_COVERAGE:
                continue

            coverage, radius, perpendicular_radius = best
            leaf_x0 = hinge_x - pad
            leaf_x1 = hinge_x + pad
            if side == -1:
                rows = slice(
                    max(face_y - perpendicular_radius, 0),
                    face_y,
                )
            else:
                rows = slice(
                    face_y + 1,
                    min(
                        face_y + 1 + perpendicular_radius,
                        thin_mask.shape[0],
                    ),
                )
            strip = thin_mask[
                rows,
                max(leaf_x0, 0) : min(leaf_x1 + 1, thin_mask.shape[1]),
            ]
            if strip.size == 0:
                continue
            leaf_coverage = float(strip.any(axis=1).mean())
            if leaf_coverage < _RASTER_SWING_LEAF_MIN_COVERAGE:
                continue
            found.append(_RasterDoorSwingSolution(
                hinge_end=hinge_end,
                hinge_x=int(hinge_x),
                side=int(side),
                face_y=int(face_y),
                direction=int(direction),
                radius_px=int(radius),
                perpendicular_radius_px=int(perpendicular_radius),
                arc_coverage=float(coverage),
                leaf_coverage=float(leaf_coverage),
            ))
    return tuple(found)


def _raster_gap_box_page_px(
    pair: _RasterBandPair,
    axis: str,
) -> tuple[int, int, int, int]:
    return _raster_to_page_box(
        (pair.gap_x0, pair.row0, pair.gap_x1, pair.row1),
        axis,
    )


class PhysicalOpeningAuthority:
    """Read-only authority over source-proven opening existence and local identity."""

    def __init__(
        self,
        source_observation_authority: SourceObservationAuthority | SourceVisibilityAuthority,
        *,
        _source_visibility_producer=None,
        _source_visibility_producer_seal: object = None,
    ) -> None:
        if type(source_observation_authority) is SourceObservationAuthority:
            self._source_observation_authority: Optional[SourceObservationAuthority] = (
                source_observation_authority
            )
            self._source_visibility_authority: Optional[SourceVisibilityAuthority] = None
        elif type(source_observation_authority) is SourceVisibilityAuthority:
            self._source_observation_authority = None
            self._source_visibility_authority = source_observation_authority
        else:
            raise TypeError(
                "source_observation_authority must be the concrete producer-owned "
                "SourceObservationAuthority or SourceVisibilityAuthority reader"
            )
        if (
            _source_visibility_producer is not None
            and _source_visibility_producer_seal is not _VIEWPORT_SCOPED_PRODUCER_SEAL
        ):
            raise TypeError(
                "viewport-scoped physical opening authority must be obtained from "
                "PhysicalOpeningAuthority.from_source_visibility_producer()"
            )
        self._source_visibility_producer = _source_visibility_producer
        self._visible_viewport_scope_cache: dict[
            tuple[str, str, str, str, str],
            tuple[
                tuple[CandidateSemanticOpening, ...],
                dict[str, object],
                tuple[str, ...],
            ],
        ] = {}
        self._visible_candidate_cache: dict[
            tuple[str, str, str, str, str],
            tuple[CandidateSemanticOpening, ...],
        ] = {}
        self._visible_candidate_membership_cache: dict[
            tuple[str, str, str, str, str],
            dict[str, tuple[CandidateSemanticOpening, ...]],
        ] = {}
        self._visible_viewport_candidate_membership_cache: dict[
            tuple[str, str, str, str, str],
            dict[str, tuple[CandidateSemanticOpening, ...]],
        ] = {}
        self._visible_existence_cache: dict[
            tuple[str, str, str, str, str],
            PhysicalOpeningExistenceResult,
        ] = {}
        self._visible_disposition_cache: dict[
            tuple[str, str, str, str, str],
            PhysicalOpeningDispositionResult,
        ] = {}
        # Visibility resolution is immutable for one exact source snapshot.
        # Snapshot materialization below already resolves every observation;
        # retain those exact authority results so per-observation proofs do not
        # re-run the same source/receipt validation thousands of times.
        self._wall_source_opening_page_proof_cache: dict[
            tuple[str, str, str, str, str, str],
            tuple[PhysicalOpeningExistenceRecord, ...],
        ] = {}
        self._visible_source_result_cache: dict[
            tuple[str, str, str, str, str],
            SourceObservationAuthorityResult,
        ] = {}
        self._visible_snapshot_cache: dict[
            tuple[str, str, str, str],
            tuple[
                tuple[SourceObservationRecord, ...],
                tuple[SourceObservationAuthorityResult, ...],
            ],
        ] = {}
        self._raster_primitive_snapshot_cache: dict[
            tuple[str, str, str, str],
            tuple[
                tuple[SourceObservationRecord, ...],
                tuple[SourceObservationAuthorityResult, ...],
            ],
        ] = {}
        self._raster_framed_candidate_cache: dict[
            tuple[str, str, str, str, str],
            tuple[CandidateSemanticOpening, ...],
        ] = {}
        # Candidate closure must see incomplete wall-band gaps too. Positive
        # framed/swing nomination alone cannot establish the competitor universe.
        self._raster_gap_candidate_audit_cache: dict[
            tuple[str, str, str, str, str],
            tuple[tuple[str, frozenset[str], tuple[float, ...]], ...],
        ] = {}
        self._raster_gap_audit_incomplete: set[tuple[str, str, str, str, str]] = set()
        self._raster_candidate_gap_box_cache: dict[
            str, tuple[float, float, float, float]
        ] = {}
        self._raster_swing_ambiguous_support_cache: dict[
            tuple[str, str, str, str, str], frozenset[str]
        ] = {}
        self._raster_existence_cache: dict[
            tuple[str, str, str, str, str],
            PhysicalOpeningExistenceResult,
        ] = {}

    @classmethod
    def from_source_visibility_producer(cls, source_visibility_producer):
        """Build the live viewport-scoped authority from its producer-owned source root."""
        from pb_source_visibility_authority import SourceVisibilityProducer

        if type(source_visibility_producer) is not SourceVisibilityProducer:
            raise TypeError("source_visibility_producer must be the concrete producer-owned SourceVisibilityProducer")
        return cls(
            source_visibility_producer.authority(),
            _source_visibility_producer=source_visibility_producer,
            _source_visibility_producer_seal=_VIEWPORT_SCOPED_PRODUCER_SEAL,
        )

    def source_visibility_authority(self) -> Optional[SourceVisibilityAuthority]:
        """Return the producer-owned visibility reader when this authority is visibility-backed.

        Raw diagnostic mode deliberately returns ``None``. Downstream authorities
        that require source-visible geometry can therefore fail closed without
        reaching through this class's private storage.
        """
        return self._source_visibility_authority

    def native_unstroked_fill_evidence(
        self, selector: ObservationSelector, *, source_primitive_ids: Sequence[str]
    ) -> tuple[EvidenceAtom, ...]:
        """Reauthenticate complete native paint-role support for frame opposition."""
        if self._source_visibility_producer is None or not source_primitive_ids:
            return ()
        required = frozenset(source_primitive_ids)
        if any(str(i).startswith('raster_segment:') for i in required):
            return ()
        published = self._source_visibility_producer.published_snapshot_for_revision(selector.revision_id)
        if (published is None or published.snapshot.snapshot_id != selector.snapshot_id
                or published.revision.document_id != selector.document_id
                or published.revision.source_sha256 != selector.source_sha256):
            raise RuntimeError('producer_integrity_failure')
        rows = self._source_visibility_producer.authority().authenticated_visible_observations(published)
        addressed = tuple((r.source_primitive_ref.removeprefix('visible:segment:'), i)
            for i,r in rows if r.source_primitive_ref.removeprefix('visible:segment:') in required)
        if {primitive for primitive,_ in addressed} != required:
            return ()
        ids = tuple(sorted({i for _,i in addressed}))
        return self._source_visibility_producer.native_unstroked_fill_evidence(
            replace(selector, observation_id=ids[0]), support_observation_ids=ids)

    def native_dimension_annotation_evidence(
        self, selector: ObservationSelector, *, source_primitive_ids: Sequence[str]
    ) -> tuple[EvidenceAtom, ...]:
        """Prove the complete native component role, without measuring text."""
        if self._source_visibility_producer is None or not source_primitive_ids:
            return ()
        required = frozenset(source_primitive_ids)
        if any(str(i).startswith('raster_segment:') for i in required):
            return ()
        published = self._source_visibility_producer.published_snapshot_for_revision(selector.revision_id)
        if (published is None or published.snapshot.snapshot_id != selector.snapshot_id
                or published.revision.document_id != selector.document_id
                or published.revision.source_sha256 != selector.source_sha256):
            raise RuntimeError('producer_integrity_failure')
        rows = self._source_visibility_producer.authority().authenticated_visible_observations(published)
        addressed = tuple((r.source_primitive_ref.removeprefix('visible:segment:'), i)
            for i, r in rows if r.source_primitive_ref.removeprefix('visible:segment:') in required)
        if {primitive for primitive, _ in addressed} != required:
            return ()
        ids = tuple(sorted({i for _, i in addressed}))
        return self._source_visibility_producer.native_dimension_cap_evidence(
            replace(selector, observation_id=ids[0]), opening_support_ids=ids)

    @staticmethod
    def capabilities() -> dict[str, bool]:
        return {
            "physical_opening_existence": True,
            "physical_opening_identity": True,
            "opening_universe_complete": False,
            "opening_dimensions": False,
            "host_identity": False,
            "host_binding": False,
            "physical_void": False,
            "net_wall_area": False,
        }

    def _raw_snapshot_records(
        self,
        seed: SourceObservationAuthorityResult,
    ) -> tuple[tuple[SourceObservationRecord, ...], tuple[SourceObservationAuthorityResult, ...]]:
        source = self._source_observation_authority
        if source is None or seed.snapshot is None or seed.source_revision is None:
            return (), ()
        records: list[SourceObservationRecord] = []
        failures: list[SourceObservationAuthorityResult] = []
        for observation_id in seed.snapshot.observation_ids:
            result = source.resolve(
                ObservationSelector(
                    document_id=seed.snapshot.document_id,
                    revision_id=seed.snapshot.revision_id,
                    source_sha256=seed.snapshot.source_sha256,
                    snapshot_id=seed.snapshot.snapshot_id,
                    observation_id=observation_id,
                )
            )
            if result.status is EvidenceResolutionStatus.CORROBORATED and result.observation:
                records.append(result.observation)
            else:
                failures.append(result)
        return tuple(records), tuple(failures)

    @staticmethod
    def _visible_selector_cache_key(
        selector: ObservationSelector,
    ) -> tuple[str, str, str, str, str]:
        return (
            str(selector.document_id),
            str(selector.revision_id),
            str(selector.source_sha256),
            str(selector.snapshot_id),
            str(selector.observation_id),
        )

    def _resolve_visible_cached(
        self,
        selector: ObservationSelector,
    ) -> SourceObservationAuthorityResult:
        visibility = self._source_visibility_authority
        if visibility is None:
            raise RuntimeError(VISIBLE_SOURCE_AUTHORITY_REQUIRED)
        key = self._visible_selector_cache_key(selector)
        cached = self._visible_source_result_cache.get(key)
        if cached is not None:
            return cached
        result = visibility.resolve_visible(selector)
        self._visible_source_result_cache[key] = result
        return result

    def _visible_snapshot_records(
        self,
        seed: SourceObservationAuthorityResult,
    ) -> tuple[tuple[SourceObservationRecord, ...], tuple[SourceObservationAuthorityResult, ...]]:
        visibility = self._source_visibility_authority
        if visibility is None or seed.snapshot is None or seed.source_revision is None:
            return (), ()
        cache_key = (
            seed.snapshot.document_id,
            seed.snapshot.revision_id,
            seed.snapshot.source_sha256,
            seed.snapshot.snapshot_id,
        )
        cached = self._visible_snapshot_cache.get(cache_key)
        if cached is not None:
            return cached
        records: list[SourceObservationRecord] = []
        failures: list[SourceObservationAuthorityResult] = []

        # Reuse the producer's fail-closed batch authenticator for this exact
        # immutable visible snapshot. Preserve historical snapshot ordering and
        # defensive copies; any batch integrity failure falls back to the
        # existing scalar visibility path unchanged.
        batch_rows = None
        producer = self._source_visibility_producer
        if producer is not None:
            published = producer.published_snapshot_for_revision(
                seed.snapshot.revision_id
            )
            if (
                published is not None
                and published.snapshot.snapshot_id == seed.snapshot.snapshot_id
            ):
                try:
                    batch_rows = visibility.authenticated_visible_observations(
                        published
                    )
                except RuntimeError:
                    batch_rows = None
        if batch_rows is not None:
            by_id = {
                str(observation_id): record
                for observation_id, record in batch_rows
            }
            records.extend(
                replace(by_id[observation_id])
                for observation_id in seed.snapshot.observation_ids
                if observation_id in by_id
            )
        else:
            visible_observation_ids = visibility.visible_observation_ids_for_snapshot(
                seed.snapshot.snapshot_id
            )
            for observation_id in seed.snapshot.observation_ids:
                # Non-visible source observations historically resolve to
                # VISIBILITY_RECEIPT_UNAVAILABLE and are intentionally ignored.
                if observation_id not in visible_observation_ids:
                    continue
                result = self._resolve_visible_cached(
                    ObservationSelector(
                        document_id=seed.snapshot.document_id,
                        revision_id=seed.snapshot.revision_id,
                        source_sha256=seed.snapshot.source_sha256,
                        snapshot_id=seed.snapshot.snapshot_id,
                        observation_id=observation_id,
                    )
                )
                if (
                    result.status is EvidenceResolutionStatus.CORROBORATED
                    and result.observation
                ):
                    records.append(result.observation)
                elif result.status is EvidenceResolutionStatus.CONFLICT:
                    failures.append(result)
                elif VISIBILITY_RECEIPT_UNAVAILABLE not in result.reason_codes:
                    failures.append(result)
        resolved = (tuple(records), tuple(failures))
        self._visible_snapshot_cache[cache_key] = resolved
        return resolved

    def _raster_primitive_snapshot_records(
        self,
        seed: SourceObservationAuthorityResult,
    ) -> tuple[
        tuple[SourceObservationRecord, ...],
        tuple[SourceObservationAuthorityResult, ...],
    ]:
        producer = self._source_visibility_producer
        visibility = self._source_visibility_authority
        if (
            producer is None
            or visibility is None
            or seed.snapshot is None
            or seed.source_revision is None
        ):
            return (), ()
        key = (
            str(seed.snapshot.document_id),
            str(seed.snapshot.revision_id),
            str(seed.snapshot.source_sha256),
            str(seed.snapshot.snapshot_id),
        )
        cached = self._raster_primitive_snapshot_cache.get(key)
        if cached is not None:
            return cached

        published = producer.published_snapshot_for_revision(
            seed.snapshot.revision_id
        )
        if (
            published is None
            or published.snapshot.snapshot_id != seed.snapshot.snapshot_id
        ):
            return (), ()

        records: list[SourceObservationRecord] = []
        failures: list[SourceObservationAuthorityResult] = []
        for observation_id in published.raster_opening_primitive_observation_ids:
            result = visibility.resolve_raster_opening_primitive(
                ObservationSelector(
                    document_id=seed.snapshot.document_id,
                    revision_id=seed.snapshot.revision_id,
                    source_sha256=seed.snapshot.source_sha256,
                    snapshot_id=seed.snapshot.snapshot_id,
                    observation_id=observation_id,
                )
            )
            if (
                result.status is EvidenceResolutionStatus.CORROBORATED
                and result.observation is not None
            ):
                records.append(result.observation)
            else:
                failures.append(result)
        resolved = (tuple(records), tuple(failures))
        self._raster_primitive_snapshot_cache[key] = resolved
        return resolved

    def _raster_framed_candidates_for(
        self,
        seed: SourceObservationRecord,
        records: tuple[SourceObservationRecord, ...],
    ) -> tuple[CandidateSemanticOpening, ...]:
        cache_key = self._visible_page_candidate_key(seed)
        cached = self._raster_framed_candidate_cache.get(cache_key)
        if cached is not None:
            return cached
        producer = self._source_visibility_producer
        if producer is None:
            return ()

        try:
            png_bytes, _page_parent, native_frame, dpi = (
                producer.render_raster_opening_source_page(
                    seed.revision_id,
                    seed.page_id,
                )
            )
        except Exception:
            self._raster_framed_candidate_cache[cache_key] = ()
            return ()
        if int(getattr(native_frame, "rotation", 0) or 0) != 0:
            self._raster_framed_candidate_cache[cache_key] = ()
            return ()
        try:
            image_placements = producer.raster_opening_image_placements(
                seed.revision_id,
                seed.page_id,
            )
            registration_scale = producer.raster_opening_registration_scale(
                seed.revision_id,
                seed.page_id,
            )
        except Exception:
            image_placements = ()
            registration_scale = None
        # A single/consistent embedded-image transform may normalize morphology
        # for source-space quarter-turn invariance. Mixed tiled transforms never
        # suppress the page: fall back to the already-validated page-coordinate
        # detector and keep local placement evidence for swing arc registration.
        if registration_scale is None:
            registration_scale = (1.0, 1.0)

        encoded = np.frombuffer(png_bytes, dtype=np.uint8)
        gray = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
        if gray is None or gray.ndim != 2 or gray.size == 0:
            self._raster_framed_candidate_cache[cache_key] = ()
            return ()
        mass = (gray < RASTER_MASS_THRESHOLD).astype(np.uint8)
        line_mask = (gray < RASTER_LINE_THRESHOLD).astype(np.uint8)
        scale_x, scale_y = registration_scale
        solid_x = _raster_odd(
            _raster_scaled_px(RASTER_POCHE_MIN_PT, dpi, scale_x)
        )
        solid_y = _raster_odd(
            _raster_scaled_px(RASTER_POCHE_MIN_PT, dpi, scale_y)
        )
        thick = cv2.morphologyEx(
            mass,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (solid_x, solid_y),
            ),
        )
        thin_mask = _raster_hairline_mask(line_mask, thick)

        scoped = tuple(
            record
            for record in records
            if record.document_id == seed.document_id
            and record.revision_id == seed.revision_id
            and record.source_sha256 == seed.source_sha256
            and record.snapshot_id == seed.snapshot_id
            and record.page_id == seed.page_id
            and record.viewport_id is None
        )
        by_kind_geometry: dict[
            tuple[str, tuple[float, float, float, float]],
            SourceObservationRecord,
        ] = {}
        line_runs: list[SourceObservationRecord] = []
        thin_runs: list[SourceObservationRecord] = []
        for record in scoped:
            geometry = tuple(round(float(value), 6) for value in record.geometry)
            if len(geometry) != 4:
                continue
            by_kind_geometry[(record.observation_kind, geometry)] = record
            if record.observation_kind == RASTER_LINE_RUN:
                line_runs.append(record)
            if record.observation_kind == RASTER_THIN_INK_RUN:
                thin_runs.append(record)

        def primitive_record(
            kind: str,
            geometry_px: Sequence[float],
        ) -> Optional[SourceObservationRecord]:
            geometry_pt = tuple(
                round(value, 6)
                for value in _raster_geometry_pt(geometry_px, dpi)
            )
            return by_kind_geometry.get((kind, geometry_pt))

        def band_support(
            page_box: tuple[int, int, int, int],
            axis: str,
            *,
            high_end: bool,
        ) -> tuple[SourceObservationRecord, ...]:
            x0, y0, x1, y1 = page_box
            if axis == "horizontal":
                faces_px = (
                    (x0, y0, x1, y0),
                    (x0, y1, x1, y1),
                )
                end_px = (
                    (x1, y0, x1, y1)
                    if high_end
                    else (x0, y0, x0, y1)
                )
            else:
                faces_px = (
                    (x0, y0, x0, y1),
                    (x1, y0, x1, y1),
                )
                end_px = (
                    (x0, y1, x1, y1)
                    if high_end
                    else (x0, y0, x1, y0)
                )
            rows = [
                primitive_record(RASTER_WALL_BAND_FACE, geometry)
                for geometry in faces_px
            ]
            rows.append(primitive_record(RASTER_WALL_BAND_END, end_px))
            if any(row is None for row in rows):
                return ()
            return tuple(row for row in rows if row is not None)

        def frame_support(
            pair: _RasterBandPair,
            axis: str,
            groups: tuple[tuple[int, int], ...],
        ) -> tuple[SourceObservationRecord, ...]:
            gap_length = pair.gap_x1 - pair.gap_x0 + 1
            selected: dict[str, SourceObservationRecord] = {}
            for group_start, group_end in groups:
                matched_group = False
                for record in line_runs:
                    line = tuple(
                        float(value) * float(dpi) / 72.0
                        for value in record.geometry
                    )
                    if axis == "horizontal":
                        if abs(line[1] - line[3]) > 0.51:
                            continue
                        row = (line[1] + line[3]) / 2.0
                        if row < group_start - 0.51 or row > group_end + 0.51:
                            continue
                        run_start, run_end = sorted((line[0], line[2]))
                    else:
                        if abs(line[0] - line[2]) > 0.51:
                            continue
                        row = (line[0] + line[2]) / 2.0
                        if row < group_start - 0.51 or row > group_end + 0.51:
                            continue
                        run_start, run_end = sorted((line[1], line[3]))
                    overlap = max(
                        0.0,
                        min(run_end, float(pair.gap_x1))
                        - max(run_start, float(pair.gap_x0))
                        + 1.0,
                    )
                    if overlap / float(gap_length) + 1e-12 < _RASTER_LINE_COVERAGE:
                        continue
                    selected[record.observation_id] = record
                    matched_group = True
                if not matched_group:
                    return ()
            return tuple(
                selected[observation_id]
                for observation_id in sorted(selected)
            )

        def swing_leaf_support(
            solution: _RasterDoorSwingSolution,
            axis: str,
            along_scale: float,
        ) -> tuple[SourceObservationRecord, ...]:
            pad = _raster_scaled_px(
                _RASTER_SWING_LEAF_JAMB_PAD_PT,
                dpi,
                along_scale,
            )
            expected_start = (
                solution.face_y - solution.perpendicular_radius_px
                if solution.side == -1
                else solution.face_y + 1
            )
            expected_end = (
                solution.face_y - 1
                if solution.side == -1
                else solution.face_y + solution.perpendicular_radius_px
            )
            expected_start, expected_end = sorted(
                (float(expected_start), float(expected_end))
            )
            expected_length = max(expected_end - expected_start + 1.0, 1.0)
            matched: dict[str, SourceObservationRecord] = {}
            matched_geometry: dict[str, tuple[float, float, float]] = {}
            for record in thin_runs:
                line = tuple(
                    float(value) * float(dpi) / 72.0
                    for value in record.geometry
                )
                if axis == "vertical":
                    line = (line[1], line[0], line[3], line[2])
                if abs(line[0] - line[2]) > 0.51:
                    continue
                leaf_x = (line[0] + line[2]) / 2.0
                if abs(leaf_x - float(solution.hinge_x)) > float(pad) + 0.51:
                    continue
                run_start, run_end = sorted((line[1], line[3]))
                overlap = max(
                    0.0,
                    min(run_end, expected_end)
                    - max(run_start, expected_start)
                    + 1.0,
                )
                if (
                    overlap / expected_length + 1e-12
                    < _RASTER_SWING_LEAF_MIN_COVERAGE
                ):
                    continue
                if solution.side == -1:
                    if abs(run_end - float(solution.face_y)) > float(pad) + 1.0:
                        continue
                else:
                    if abs(run_start - float(solution.face_y)) > float(pad) + 1.0:
                        continue
                matched[record.observation_id] = record
                matched_geometry[record.observation_id] = (
                    float(leaf_x),
                    float(run_start),
                    float(run_end),
                )

            if not matched:
                return ()

            # Raster antialiasing / line thickness can legitimately publish one
            # physical door leaf as two or more parallel thin-run primitives.
            # Preserve every source record as provenance, but accept them as one
            # leaf bundle only when they are spatially compact at the already
            # authenticated hinge and mutually overlap for the same full leaf.
            # Separated or non-overlapping multiple candidates remain fail-closed.
            if len(matched) > 1:
                geometries = tuple(
                    matched_geometry[observation_id]
                    for observation_id in sorted(matched_geometry)
                )
                leaf_positions = tuple(item[0] for item in geometries)
                if max(leaf_positions) - min(leaf_positions) > float(pad):
                    return ()

                common_start = max(item[1] for item in geometries)
                common_end = min(item[2] for item in geometries)
                common_overlap = max(common_end - common_start + 1.0, 0.0)
                shortest_run = min(
                    max(item[2] - item[1] + 1.0, 1.0)
                    for item in geometries
                )
                if (
                    common_overlap / shortest_run + 1e-12
                    < _RASTER_SWING_LEAF_MIN_COVERAGE
                ):
                    return ()

            return tuple(
                matched[observation_id]
                for observation_id in sorted(matched)
            )

        discovered: dict[str, dict[str, SourceObservationRecord]] = {}
        candidate_patterns: dict[str, str] = {}
        ambiguous_support_ids: set[str] = set()
        framed_gap_boxes: set[tuple[float, float, float, float]] = set()
        gap_audit: dict[str, tuple[str, frozenset[str], tuple[float, ...]]] = {}
        for axis in ("horizontal", "vertical"):
            along_scale, cross_scale = _raster_axis_registration_scales(
                axis,
                registration_scale,
            )
            page_boxes = _raster_band_boxes(
                thick,
                dpi=dpi,
                axis=axis,
                registration_scale=registration_scale,
            )
            analysis_boxes = tuple(
                _raster_analysis_box(box, axis)
                for box in page_boxes
            )
            work_thick = (
                thick
                if axis == "horizontal"
                else np.ascontiguousarray(thick.T)
            )
            work_line = (
                line_mask
                if axis == "horizontal"
                else np.ascontiguousarray(line_mask.T)
            )
            work_thin = (
                thin_mask
                if axis == "horizontal"
                else np.ascontiguousarray(thin_mask.T)
            )
            for pair in _raster_pair_flanks(
                work_thick,
                analysis_boxes,
                dpi=dpi,
                along_scale=along_scale,
                cross_scale=cross_scale,
            ):
                page_a = _raster_to_page_box(pair.a, axis)
                page_b = _raster_to_page_box(pair.b, axis)
                support_a = band_support(page_a, axis, high_end=True)
                support_b = band_support(page_b, axis, high_end=False)
                if not support_a or not support_b:
                    self._raster_gap_audit_incomplete.add(cache_key)
                    continue

                gap_box_px = _raster_gap_box_page_px(pair, axis)
                gap_box_pt = tuple(
                    round(value, 6)
                    for value in _raster_box_pt(gap_box_px, dpi)
                )
                gap_support = frozenset(
                    record.observation_id for record in (*support_a, *support_b)
                )
                gap_id = stable_contract_id("physical_opening_raw_candidate", {
                    "document_id": seed.document_id,
                    "revision_id": seed.revision_id,
                    "source_sha256": seed.source_sha256,
                    "snapshot_id": seed.snapshot_id,
                    "page_id": seed.page_id,
                    "pattern": "raster_wall_band_gap_candidate",
                    "gap_box_pt": gap_box_pt,
                    "source_observation_ids": tuple(sorted(gap_support)),
                }, digest_chars=32)
                gap_audit[gap_id] = (gap_id, gap_support, gap_box_pt)
                if pair.reasons:
                    continue

                groups = _raster_frame_line_groups(
                    work_line,
                    pair,
                    dpi=dpi,
                    cross_scale=cross_scale,
                )
                face_continues = (
                    bool(groups)
                    and _raster_wall_face_continues(work_line, pair)
                )
                frames = (
                    frame_support(pair, axis, groups)
                    if groups and not face_continues
                    else ()
                )
                if frames:
                    support = (*support_a, *support_b, *frames)
                    support_by_id = {
                        record.observation_id: record for record in support
                    }
                    if len(support_by_id) >= 8:
                        payload = {
                            "document_id": seed.document_id,
                            "revision_id": seed.revision_id,
                            "source_sha256": seed.source_sha256,
                            "page_id": seed.page_id,
                            "structural_pattern":
                                RASTER_FRAMED_WALL_BAND_INTERRUPTION,
                            "gap_box_pt": gap_box_pt,
                        }
                        candidate_id = stable_contract_id(
                            "physical_opening_candidate",
                            payload,
                            digest_chars=32,
                        )
                        evidence = discovered.setdefault(candidate_id, {})
                        evidence.update(support_by_id)
                        candidate_patterns[candidate_id] = (
                            RASTER_FRAMED_WALL_BAND_INTERRUPTION
                        )
                        self._raster_candidate_gap_box_cache[candidate_id] = gap_box_pt
                        framed_gap_boxes.add(gap_box_pt)
                        continue

                swing_scale_ratio = _raster_swing_perpendicular_scale_ratio(
                    gap_box_pt,
                    axis,
                    image_placements,
                )
                if swing_scale_ratio is None:
                    continue
                solutions = _raster_door_swing_solutions(
                    work_thin,
                    pair,
                    dpi=dpi,
                    perpendicular_scale_ratio=swing_scale_ratio,
                    along_scale=along_scale,
                )
                if len(solutions) > 1:
                    ambiguous_support_ids.update(
                        record.observation_id
                        for record in (*support_a, *support_b)
                    )
                    continue
                if len(solutions) != 1 or gap_box_pt in framed_gap_boxes:
                    continue
                leaf = swing_leaf_support(
                    solutions[0],
                    axis,
                    along_scale,
                )
                if not leaf:
                    continue
                support = (*support_a, *support_b, *leaf)
                support_by_id = {
                    record.observation_id: record for record in support
                }
                if len(support_by_id) < 7:
                    continue
                payload = {
                    "document_id": seed.document_id,
                    "revision_id": seed.revision_id,
                    "source_sha256": seed.source_sha256,
                    "page_id": seed.page_id,
                    "structural_pattern":
                        RASTER_DOOR_SWING_WALL_BAND_INTERRUPTION,
                    "gap_box_pt": gap_box_pt,
                }
                candidate_id = stable_contract_id(
                    "physical_opening_candidate",
                    payload,
                    digest_chars=32,
                )
                evidence = discovered.setdefault(candidate_id, {})
                evidence.update(support_by_id)
                candidate_patterns[candidate_id] = (
                    RASTER_DOOR_SWING_WALL_BAND_INTERRUPTION
                )
                self._raster_candidate_gap_box_cache[candidate_id] = gap_box_pt

        for candidate_id in tuple(sorted(discovered)):
            if (
                candidate_patterns.get(candidate_id)
                == RASTER_DOOR_SWING_WALL_BAND_INTERRUPTION
                and self._raster_candidate_gap_box_cache.get(candidate_id)
                in framed_gap_boxes
            ):
                discovered.pop(candidate_id, None)
                candidate_patterns.pop(candidate_id, None)
                self._raster_candidate_gap_box_cache.pop(candidate_id, None)

        candidates: list[CandidateSemanticOpening] = []
        for candidate_id in sorted(discovered):
            support = tuple(
                discovered[candidate_id][observation_id]
                for observation_id in sorted(discovered[candidate_id])
            )
            candidates.append(CandidateSemanticOpening(
                candidate_id=candidate_id,
                source_observation_ids=tuple(
                    record.observation_id for record in support
                ),
                source_lineage_root_ids=tuple(
                    sorted(
                        {
                            parent
                            for record in support
                            for parent in record.derivation_parent_ids
                        }
                    )
                ),
                document_id=seed.document_id,
                revision_id=seed.revision_id,
                source_sha256=seed.source_sha256,
                snapshot_id=seed.snapshot_id,
                page_id=seed.page_id,
                viewport_id=None,
                structural_pattern=candidate_patterns[candidate_id],
                status=EvidenceResolutionStatus.CANDIDATE,
                reason_codes=(
                    candidate_patterns[candidate_id],
                    VISIBLE_WALL_CONTINUATION_REQUIRED,
                ),
            ))

        result = tuple(candidates)
        self._raster_gap_candidate_audit_cache[cache_key] = tuple(
            gap_audit[key] for key in sorted(gap_audit)
        )
        self._raster_swing_ambiguous_support_cache[cache_key] = frozenset(
            ambiguous_support_ids
        )
        self._raster_framed_candidate_cache[cache_key] = result
        return result

    def _viewport_scoped_raster_candidates_for(
        self,
        seed: SourceObservationRecord,
        records: tuple[SourceObservationRecord, ...],
        candidates: tuple[CandidateSemanticOpening, ...],
    ) -> tuple[CandidateSemanticOpening, ...]:
        producer = self._source_visibility_producer
        if producer is None or not candidates:
            return candidates
        from pb_physical_opening_viewport_scope_authority import (
            classify_opening_candidate_viewport_scopes,
        )
        scope_result = classify_opening_candidate_viewport_scopes(
            source_visibility_producer=producer,
            revision_id=seed.revision_id,
            page_id=seed.page_id,
            snapshot_id=seed.snapshot_id,
            candidates=candidates,
            records=records,
        )
        if scope_result.status is not EvidenceResolutionStatus.CORROBORATED:
            return ()
        if not tuple(scope_result.authenticated_viewports):
            return candidates

        decisions = dict(scope_result.decisions)
        promoted: list[CandidateSemanticOpening] = []
        for candidate in candidates:
            decision = decisions.get(candidate.candidate_id)
            if decision is None or not bool(getattr(decision, "promotable", False)):
                continue
            viewport_id = str(getattr(decision, "viewport_id", "") or "").strip()
            if viewport_id:
                promoted.append(replace(candidate, viewport_id=viewport_id))
        return tuple(promoted)

    def _prove_raster_framed_existence(
        self,
        selector: ObservationSelector,
        source_result: SourceObservationAuthorityResult,
    ) -> PhysicalOpeningExistenceResult:
        cache_key = self._visible_selector_cache_key(selector)
        cached = self._raster_existence_cache.get(cache_key)
        if cached is not None:
            return cached

        def cache(
            result: PhysicalOpeningExistenceResult,
        ) -> PhysicalOpeningExistenceResult:
            self._raster_existence_cache[cache_key] = result
            return result

        if (
            source_result.status is not EvidenceResolutionStatus.CORROBORATED
            or source_result.observation is None
            or source_result.snapshot is None
        ):
            return cache(PhysicalOpeningExistenceResult(
                status=_source_failure_status(source_result),
                proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=_dedupe_reason_codes(source_result.reason_codes),
                source_observation=source_result,
            ))

        records, failures = self._raster_primitive_snapshot_records(source_result)
        if failures:
            return cache(PhysicalOpeningExistenceResult(
                status=_source_failure_status(*failures),
                proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=_dedupe_reason_codes(
                    (SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,),
                    *tuple(item.reason_codes for item in failures),
                ),
                source_observation=source_result,
            ))

        observation = source_result.observation
        raw_candidates = self._raster_framed_candidates_for(observation, records)
        candidates = self._viewport_scoped_raster_candidates_for(
            observation,
            records,
            raw_candidates,
        )
        containing = tuple(
            candidate
            for candidate in candidates
            if observation.observation_id in candidate.source_observation_ids
        )
        if len(containing) > 1:
            return cache(PhysicalOpeningExistenceResult(
                status=EvidenceResolutionStatus.CONFLICT,
                proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=(AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES,),
                source_observation=source_result,
            ))
        if len(containing) != 1:
            page_cache_key = self._visible_page_candidate_key(observation)
            ambiguous_support = self._raster_swing_ambiguous_support_cache.get(
                page_cache_key,
                frozenset(),
            )
            if observation.observation_id in ambiguous_support:
                return cache(PhysicalOpeningExistenceResult(
                    status=EvidenceResolutionStatus.CONFLICT,
                    proposition=None,
                    physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                    reason_codes=(RASTER_DOOR_SWING_AMBIGUOUS,),
                    source_observation=source_result,
                ))
            return cache(PhysicalOpeningExistenceResult(
                status=EvidenceResolutionStatus.ABSTAINED,
                proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=(VISIBLE_WALL_CONTINUATION_REQUIRED,),
                source_observation=source_result,
            ))

        candidate = containing[0]
        gap_box = self._raster_candidate_gap_box_cache.get(candidate.candidate_id)
        if gap_box is None:
            return cache(PhysicalOpeningExistenceResult(
                status=EvidenceResolutionStatus.ABSTAINED,
                proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=(INVALID_STRUCTURAL_GEOMETRY,),
                source_observation=source_result,
                candidate=candidate,
            ))

        # Unequal overlapping apertures cannot establish distinct physical
        # openings merely by hashing different detector extents. Keep both
        # hypotheses; exact equal apertures retain the existing stable identity.
        for other in candidates:
            other_box = self._raster_candidate_gap_box_cache.get(other.candidate_id)
            if other_box is None or other_box == gap_box:
                continue
            if (min(gap_box[2], other_box[2]) - max(gap_box[0], other_box[0]) > _COORD_EQ_ABS_TOL
                    and min(gap_box[3], other_box[3]) - max(gap_box[1], other_box[1]) > _COORD_EQ_ABS_TOL):
                return cache(PhysicalOpeningExistenceResult(
                    status=EvidenceResolutionStatus.CONFLICT,
                    proposition=None,
                    physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                    reason_codes=(AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES,),
                    source_observation=source_result,
                    candidate=candidate,
                ))

        record_payload = {
            "document_id": candidate.document_id,
            "revision_id": candidate.revision_id,
            "source_sha256": candidate.source_sha256,
            "page_id": candidate.page_id,
            "semantic_class": "opening",
            "gap_box_pt": gap_box,
        }
        existence = PhysicalOpeningExistenceRecord(
            record_id=stable_contract_id(
                "physical_opening_existence",
                record_payload,
                digest_chars=32,
            ),
            source_observation_ids=candidate.source_observation_ids,
            source_lineage_root_ids=candidate.source_lineage_root_ids,
            document_id=candidate.document_id,
            revision_id=candidate.revision_id,
            source_sha256=candidate.source_sha256,
            snapshot_id=candidate.snapshot_id,
            page_id=candidate.page_id,
            viewport_id=candidate.viewport_id,
            semantic_class="opening",
            status=EvidenceResolutionStatus.CORROBORATED,
            proposition=PHYSICAL_OPENING_EXISTS,
            structural_pattern=candidate.structural_pattern,
            diagnostic_confidence=1.0,
            blocking_reasons=(),
            structural_reason_codes=(
                STRUCTURAL_OPENING_EXISTENCE_RESOLVED,
                candidate.structural_pattern,
            ),
            producer_method=source_result.snapshot.producer_method,
            producer_version=source_result.snapshot.producer_version,
            producer_generation=source_result.snapshot.producer_generation,
            aperture_bbox_pt=gap_box,
        )
        return cache(PhysicalOpeningExistenceResult(
            status=EvidenceResolutionStatus.CORROBORATED,
            proposition=PHYSICAL_OPENING_EXISTS,
            physical_opening_existence=PHYSICAL_OPENING_EXISTS,
            reason_codes=(
                STRUCTURAL_OPENING_EXISTENCE_RESOLVED,
                candidate.structural_pattern,
            ),
            source_observation=source_result,
            candidate=candidate,
            existence_record=existence,
        ))

    @staticmethod
    def _raw_structural_candidates(
        seed: SourceObservationRecord,
        records: tuple[SourceObservationRecord, ...],
    ) -> tuple[CandidateSemanticOpening, ...]:
        scoped = tuple(
            record
            for record in records
            if record.document_id == seed.document_id
            and record.revision_id == seed.revision_id
            and record.source_sha256 == seed.source_sha256
            and record.snapshot_id == seed.snapshot_id
            and record.page_id == seed.page_id
            and record.viewport_id == seed.viewport_id
        )
        faces = tuple(
            record for record in scoped
            if record.observation_kind == WALL_FACE_INTERRUPTION_KIND
            and _line_geometry(record) is not None
        )
        jambs = tuple(
            record for record in scoped
            if record.observation_kind == OPENING_JAMB_BOUNDARY_KIND
            and _line_geometry(record) is not None
        )
        discovered: dict[tuple[object, ...], tuple[set[str], set[str]]] = {}
        for index, first_face in enumerate(faces):
            first_line = _line_geometry(first_face)
            if first_line is None:
                continue
            for second_face in faces[index + 1:]:
                second_line = _line_geometry(second_face)
                if second_line is None or not _parallel(first_line, second_line):
                    continue
                orientations = (
                    ((first_line[0], first_line[1]), (second_line[0], second_line[1]),
                     (first_line[2], first_line[3]), (second_line[2], second_line[3])),
                    ((first_line[0], first_line[1]), (second_line[2], second_line[3]),
                     (first_line[2], first_line[3]), (second_line[0], second_line[1])),
                )
                for first_a, first_b, second_a, second_b in orientations:
                    left_jambs = tuple(j for j in jambs if _segment_matches(j, first_a, first_b))
                    right_jambs = tuple(j for j in jambs if _segment_matches(j, second_a, second_b))
                    for left_jamb in left_jambs:
                        for right_jamb in right_jambs:
                            support = (first_face, second_face, left_jamb, right_jamb)
                            if len({item.observation_id for item in support}) != 4:
                                continue
                            geometry_key = tuple(sorted(_canonical_line(item) for item in support))
                            roots = {
                                parent
                                for item in support
                                for parent in item.derivation_parent_ids
                            }
                            key = (seed.document_id, seed.revision_id, seed.source_sha256,
                                   seed.snapshot_id, seed.page_id, seed.viewport_id, geometry_key)
                            if key in discovered:
                                discovered[key][0].update(item.observation_id for item in support)
                                discovered[key][1].update(roots)
                            else:
                                discovered[key] = (
                                    {item.observation_id for item in support}, set(roots)
                                )
        result: list[CandidateSemanticOpening] = []
        for key in sorted(discovered, key=repr):
            observation_ids, root_ids = discovered[key]
            payload = {
                "document_id": seed.document_id,
                "revision_id": seed.revision_id,
                "source_sha256": seed.source_sha256,
                "snapshot_id": seed.snapshot_id,
                "page_id": seed.page_id,
                "viewport_id": seed.viewport_id,
                "structural_pattern": JAMB_BOUNDED_TWO_FACE_INTERRUPTION,
                "source_observation_ids": tuple(sorted(observation_ids)),
                "source_lineage_root_ids": tuple(sorted(root_ids)),
            }
            result.append(CandidateSemanticOpening(
                candidate_id=stable_contract_id("physical_opening_candidate", payload, digest_chars=32),
                source_observation_ids=tuple(sorted(observation_ids)),
                source_lineage_root_ids=tuple(sorted(root_ids)),
                document_id=seed.document_id,
                revision_id=seed.revision_id,
                source_sha256=seed.source_sha256,
                snapshot_id=seed.snapshot_id,
                page_id=seed.page_id,
                viewport_id=seed.viewport_id,
                structural_pattern=JAMB_BOUNDED_TWO_FACE_INTERRUPTION,
                status=EvidenceResolutionStatus.CANDIDATE,
                reason_codes=(STRUCTURAL_OPENING_CANDIDATE, VISIBLE_SOURCE_AUTHORITY_REQUIRED),
            ))
        return tuple(result)

    @staticmethod
    def _visible_structural_candidates(
        seed: SourceObservationRecord,
        records: tuple[SourceObservationRecord, ...],
    ) -> tuple[CandidateSemanticOpening, ...]:
        """Discover exact structural openings without quadratic rescans of breaks.

        This is an equivalence-preserving index only. Candidate membership is
        still decided by the original exact predicates for same-gap, distinct
        parallel axes, segment matching, lineage and final geometry dedupe.
        """
        scoped_records: list[SourceObservationRecord] = []
        scoped_lines: list[tuple[float, float, float, float]] = []
        for record in records:
            if (
                record.observation_kind not in {
                    NATIVE_PDF_VISIBLE_SEGMENT,
                    RASTER_PDF_VISIBLE_SEGMENT,
                }
                or record.document_id != seed.document_id
                or record.revision_id != seed.revision_id
                or record.source_sha256 != seed.source_sha256
                or record.snapshot_id != seed.snapshot_id
                or record.page_id != seed.page_id
                or record.viewport_id is not None
            ):
                continue
            line = _line_geometry(record)
            if line is None:
                continue
            scoped_records.append(record)
            scoped_lines.append(line)
        # The final structural candidate map is keyed by canonical six-line
        # geometry and historically overwrites duplicate support with the last
        # source observation for identical geometry. Dense CAD/raster overlays
        # can contain thousands of observations of the exact same line, which
        # otherwise multiply the intermediate face-break universe without
        # changing the final candidate set. Apply that existing deterministic
        # overwrite rule before the all-break search. The generic correlated
        # door/window path is intentionally untouched because its candidate
        # identity is not geometry-keyed in the same way.
        last_by_geometry: dict[
            tuple[tuple[float, float], tuple[float, float]],
            tuple[int, SourceObservationRecord, tuple[float, float, float, float]],
        ] = {}
        for index, (record, line) in enumerate(zip(scoped_records, scoped_lines)):
            first = (round(line[0], 6), round(line[1], 6))
            second = (round(line[2], 6), round(line[3], 6))
            geometry_key = tuple(sorted((first, second)))
            last_by_geometry[geometry_key] = (index, record, line)

        collapsed = sorted(last_by_geometry.values(), key=lambda row: row[0])
        scoped = tuple(row[1] for row in collapsed)
        cached_lines = tuple(row[2] for row in collapsed)
        collinear_pairs = _candidate_collinear_record_pairs(
            scoped, line_geometries=cached_lines
        )
        collinear_neighbors: dict[int, set[int]] = {}
        for first_index, second_index in collinear_pairs:
            collinear_neighbors.setdefault(first_index, set()).add(second_index)
            collinear_neighbors.setdefault(second_index, set()).add(first_index)

        breaks: list[_FaceBreak] = []
        for first_index, second_index in collinear_pairs:
            found = _face_break(
                scoped[first_index],
                scoped[second_index],
                first_line=cached_lines[first_index],
                second_line=cached_lines[second_index],
            )
            if found is None:
                continue

            # Positive collinear wall continuation inside a proposed gap means
            # these two segments are not adjacent face boundaries. Historically
            # all-pairs discovery could jump across an intervening solid wall
            # stub and mint a false spanning opening. Only a source-visible gap
            # with no intervening collinear coverage may become a face break.
            continuation = False
            for other_index in (
                collinear_neighbors.get(first_index, set())
                | collinear_neighbors.get(second_index, set())
            ):
                if other_index in {first_index, second_index}:
                    continue
                other = cached_lines[other_index]
                values = sorted(
                    (
                        _projection((other[0], other[1]), found.direction),
                        _projection((other[2], other[3]), found.direction),
                    )
                )
                overlap = min(values[1], found.gap_end) - max(
                    values[0], found.gap_start
                )
                # A boundary-anchored cap is not independent proof of
                # physical wall continuation: native dimension ticks and jamb
                # decoration may start at either gap endpoint. Preserve that
                # structural hypothesis for the producer-owned annotation
                # opposition/integrity checks (which can only ABSTAIN).
                # A positive source-visible stub strictly INSIDE the proposed
                # gap does prove these are not adjacent wall faces.
                interior_stub = (
                    values[0] > found.gap_start + _COORD_EQ_ABS_TOL
                    and values[1] < found.gap_end - _COORD_EQ_ABS_TOL
                )
                if interior_stub and overlap > _COORD_EQ_ABS_TOL:
                    continuation = True
                    break
            if not continuation:
                breaks.append(found)

        if not breaks:
            return ()

        # Every discovered support tuple reuses the same immutable source
        # observations. Canonicalising six lines for every candidate pairing
        # repeatedly rebuilt identical geometry hundreds of thousands of times
        # on dense CAD pages. Cache the exact legacy canonical representation
        # once per observation for this page.
        canonical_line_by_observation_id = {
            record.observation_id: _canonical_line(record)
            for record in scoped
        }

        coord_tol = _COORD_EQ_ABS_TOL
        max_same_angle = math.acos(max(-1.0, 1.0 - _PARALLEL_REL_TOL))
        angle_width = max(max_same_angle * 2.0, 1e-12)
        angle_bucket_count = max(1, int(math.ceil(math.pi / angle_width)))

        def coord_bin(value: float) -> int:
            return math.floor(float(value) / coord_tol)

        def point_bin(point: tuple[float, float]) -> tuple[int, int]:
            return (coord_bin(point[0]), coord_bin(point[1]))

        def angle_bin(direction: tuple[float, float]) -> int:
            angle = math.atan2(direction[1], direction[0]) % math.pi
            return int(math.floor(angle / angle_width)) % angle_bucket_count

        endpoint_point_index: dict[
            tuple[int, int], list[SourceObservationRecord]
        ] = {}
        scoped_position = {
            record.observation_id: index for index, record in enumerate(scoped)
        }
        for index, record in enumerate(scoped):
            line = cached_lines[index]
            a = point_bin((line[0], line[1]))
            b = point_bin((line[2], line[3]))
            endpoint_point_index.setdefault(a, []).append(record)
            if b != a:
                endpoint_point_index.setdefault(b, []).append(record)

        segment_match_cache: dict[
            tuple[tuple[float, float], tuple[float, float]],
            tuple[SourceObservationRecord, ...],
        ] = {}

        def indexed_segment_matches(
            first: tuple[float, float],
            second: tuple[float, float],
        ) -> tuple[SourceObservationRecord, ...]:
            key = (first, second)
            cached = segment_match_cache.get(key)
            if cached is not None:
                return cached
            first_bin = point_bin(first)
            candidates: dict[str, SourceObservationRecord] = {}
            for fdx in (-1, 0, 1):
                for fdy in (-1, 0, 1):
                    fb = (first_bin[0] + fdx, first_bin[1] + fdy)
                    for record in endpoint_point_index.get(fb, ()):
                        candidates[record.observation_id] = record
            result = tuple(
                record
                for record in sorted(
                    candidates.values(),
                    key=lambda item: scoped_position[item.observation_id],
                )
                if _segment_matches(record, first, second)
            )
            segment_match_cache[key] = result
            return result

        break_index: dict[tuple[int, int, int], list[int]] = {}
        discovered: dict[
            tuple[object, ...], tuple[SourceObservationRecord, ...]
        ] = {}

        for second_index, second_break in enumerate(breaks):
            gs = coord_bin(second_break.gap_start)
            ge = coord_bin(second_break.gap_end)
            ga = angle_bin(second_break.direction)

            # Each prior break is stored in exactly one (gap-start, gap-end,
            # angle) bin, and the 27 neighbor keys below are distinct. A set
            # therefore performs duplicate tracking that can never remove an
            # item. Extend a list instead, then preserve the historical sorted
            # first-index evaluation order exactly.
            prior_indexes: list[int] = []
            for ds in (-1, 0, 1):
                for de in (-1, 0, 1):
                    for da in (-1, 0, 1):
                        ak = (ga + da) % angle_bucket_count
                        prior_indexes.extend(
                            break_index.get((gs + ds, ge + de, ak), ())
                        )

            for first_index in sorted(prior_indexes):
                first_break = breaks[first_index]
                if not _same_gap(first_break, second_break):
                    continue
                if not _distinct_parallel_axes(first_break, second_break):
                    continue

                left_jambs = indexed_segment_matches(
                    first_break.start_point,
                    second_break.start_point,
                )
                right_jambs = indexed_segment_matches(
                    first_break.end_point,
                    second_break.end_point,
                )
                for left_jamb in left_jambs:
                    for right_jamb in right_jambs:
                        support = (
                            first_break.first,
                            first_break.second,
                            second_break.first,
                            second_break.second,
                            left_jamb,
                            right_jamb,
                        )
                        if len({item.observation_id for item in support}) != 6:
                            continue
                        parent_ids: list[str] = []
                        lineage_ok = True
                        for item in support:
                            if len(item.derivation_parent_ids) != 1:
                                lineage_ok = False
                                break
                            parent_ids.append(item.derivation_parent_ids[0])
                        if not lineage_ok or len(set(parent_ids)) != 6:
                            continue
                        geometry_key = tuple(
                            sorted(
                                canonical_line_by_observation_id[
                                    item.observation_id
                                ]
                                for item in support
                            )
                        )
                        key = (
                            seed.document_id,
                            seed.revision_id,
                            seed.source_sha256,
                            seed.snapshot_id,
                            seed.page_id,
                            geometry_key,
                        )
                        discovered[key] = support

            break_index.setdefault((gs, ge, ga), []).append(second_index)

        candidates: list[CandidateSemanticOpening] = []
        for key in sorted(discovered, key=repr):
            support = discovered[key]
            observation_ids = tuple(
                sorted(item.observation_id for item in support)
            )
            root_ids = tuple(
                sorted(item.derivation_parent_ids[0] for item in support)
            )
            payload = {
                "document_id": seed.document_id,
                "revision_id": seed.revision_id,
                "source_sha256": seed.source_sha256,
                "snapshot_id": seed.snapshot_id,
                "page_id": seed.page_id,
                "viewport_id": None,
                "structural_pattern": JAMB_BOUNDED_TWO_FACE_INTERRUPTION,
                "source_observation_ids": observation_ids,
                "source_lineage_root_ids": root_ids,
            }
            candidates.append(
                CandidateSemanticOpening(
                    candidate_id=stable_contract_id(
                        "physical_opening_candidate",
                        payload,
                        digest_chars=32,
                    ),
                    source_observation_ids=observation_ids,
                    source_lineage_root_ids=root_ids,
                    document_id=seed.document_id,
                    revision_id=seed.revision_id,
                    source_sha256=seed.source_sha256,
                    snapshot_id=seed.snapshot_id,
                    page_id=seed.page_id,
                    viewport_id=None,
                    structural_pattern=JAMB_BOUNDED_TWO_FACE_INTERRUPTION,
                    status=EvidenceResolutionStatus.CANDIDATE,
                    reason_codes=(
                        JAMB_BOUNDED_TWO_FACE_INTERRUPTION,
                        VISIBLE_WALL_CONTINUATION_REQUIRED,
                    ),
                )
            )
        return tuple(candidates)

    @staticmethod
    def _visible_generic_correlated_candidates(
        seed: SourceObservationRecord,
        records: tuple[SourceObservationRecord, ...],
    ) -> tuple[CandidateSemanticOpening, ...]:
        """Discover additional source-visible opening paths via existing generic detectors.

        Door/window candidates are promoted only when independently corroborated
        by a wall discontinuity on the same producer-owned wall segment.
        """
        scoped_records = tuple(
            record
            for record in records
            if record.observation_kind in {
                NATIVE_PDF_VISIBLE_SEGMENT,
                RASTER_PDF_VISIBLE_SEGMENT,
            }
            and record.document_id == seed.document_id
            and record.revision_id == seed.revision_id
            and record.source_sha256 == seed.source_sha256
            and record.snapshot_id == seed.snapshot_id
            and record.page_id == seed.page_id
            and record.viewport_id is None
            and _line_geometry(record) is not None
        )
        if not scoped_records:
            return ()

        segments: list[LegacyPlanSegment] = []
        record_by_index: dict[int, SourceObservationRecord] = {}
        for index, record in enumerate(scoped_records):
            line = _line_geometry(record)
            assert line is not None
            segments.append(
                LegacyPlanSegment(
                    x1=line[0], y1=line[1], x2=line[2], y2=line[3],
                    drawing_index=index,
                )
            )
            record_by_index[index] = record

        walls = detect_wall_lines(segments)
        if not walls:
            return ()
        doors = detect_door_candidates_indexed(
            segments, walls, (), page_no=int(seed.page_id)
        )
        gaps = detect_gap_candidates_indexed(
            segments, walls, (), page_no=int(seed.page_id)
        )

        # Generic opening corroboration historically rescanned every source
        # segment twice for every wall gap to find endpoint-touching jambs.
        # Build a conservative endpoint broad phase once. A segment is only
        # admitted to the exact predicate below when one of its endpoints lies
        # in the queried point's 3x3 coordinate-bin neighborhood; _touches()
        # still owns final membership at the existing 1e-6 tolerance.
        endpoint_cell = _COORD_EQ_ABS_TOL

        def endpoint_bin(point: tuple[float, float]) -> tuple[int, int]:
            return (
                math.floor(float(point[0]) / endpoint_cell),
                math.floor(float(point[1]) / endpoint_cell),
            )

        endpoint_segment_index: dict[tuple[int, int], list[int]] = {}
        for segment_index, segment in enumerate(segments):
            for point in (
                (float(segment.x1), float(segment.y1)),
                (float(segment.x2), float(segment.y2)),
            ):
                endpoint_segment_index.setdefault(endpoint_bin(point), []).append(
                    segment_index
                )

        def _touches(
            segment: LegacyPlanSegment,
            point: tuple[float, float],
        ) -> bool:
            return min(
                math.hypot(segment.x1 - point[0], segment.y1 - point[1]),
                math.hypot(segment.x2 - point[0], segment.y2 - point[1]),
            ) <= _COORD_EQ_ABS_TOL

        def endpoint_touching_segments(
            point: tuple[float, float],
        ) -> tuple[LegacyPlanSegment, ...]:
            bx, by = endpoint_bin(point)
            indexes: set[int] = set()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    indexes.update(
                        endpoint_segment_index.get((bx + dx, by + dy), ())
                    )
            return tuple(
                segments[index]
                for index in sorted(indexes)
                if _touches(segments[index], point)
            )

        door_indexes_by_wall_identity: dict[int, list[int]] = {}
        for door_index, door in enumerate(doors):
            if door.wall_segment is None:
                continue
            door_indexes_by_wall_identity.setdefault(
                id(door.wall_segment), []
            ).append(door_index)

        def record_for(segment: LegacyPlanSegment | None) -> Optional[SourceObservationRecord]:
            if segment is None:
                return None
            return record_by_index.get(int(segment.drawing_index))

        def midpoint(segment: LegacyPlanSegment) -> tuple[float, float]:
            return ((segment.x1 + segment.x2) / 2.0, (segment.y1 + segment.y2) / 2.0)

        def gap_center(gap) -> Optional[tuple[float, float]]:
            if gap.centroid_x is None or gap.centroid_y is None:
                return None
            return (float(gap.centroid_x), float(gap.centroid_y))

        def support_candidate(
            *,
            support_records: tuple[SourceObservationRecord, ...],
            structural_pattern: str,
        ) -> Optional[CandidateSemanticOpening]:
            unique = {record.observation_id: record for record in support_records}
            if len(unique) < 3:
                return None
            support = tuple(unique[key] for key in sorted(unique))
            parent_ids: list[str] = []
            for item in support:
                if len(item.derivation_parent_ids) != 1:
                    return None
                parent_ids.append(item.derivation_parent_ids[0])
            if len(set(parent_ids)) != len(parent_ids):
                return None
            observation_ids = tuple(item.observation_id for item in support)
            root_ids = tuple(sorted(parent_ids))
            payload = {
                "document_id": seed.document_id,
                "revision_id": seed.revision_id,
                "source_sha256": seed.source_sha256,
                "snapshot_id": seed.snapshot_id,
                "page_id": seed.page_id,
                "viewport_id": None,
                "structural_pattern": structural_pattern,
                "source_observation_ids": observation_ids,
                "source_lineage_root_ids": root_ids,
            }
            return CandidateSemanticOpening(
                candidate_id=stable_contract_id(
                    "physical_opening_candidate", payload, digest_chars=32
                ),
                source_observation_ids=observation_ids,
                source_lineage_root_ids=root_ids,
                document_id=seed.document_id,
                revision_id=seed.revision_id,
                source_sha256=seed.source_sha256,
                snapshot_id=seed.snapshot_id,
                page_id=seed.page_id,
                viewport_id=None,
                structural_pattern=structural_pattern,
                status=EvidenceResolutionStatus.CANDIDATE,
                reason_codes=(
                    structural_pattern,
                    VISIBLE_WALL_CONTINUATION_REQUIRED,
                ),
            )

        found: dict[str, CandidateSemanticOpening] = {}
        for gap in gaps:
            if not gap.wall_segments:
                continue
            gap_wall_a, gap_wall_b = gap.wall_segments
            gap_wall_records = (
                record_for(gap_wall_a),
                record_for(gap_wall_b),
            )
            if any(record is None for record in gap_wall_records):
                continue
            center = gap_center(gap)
            if center is None:
                continue

            gap_width = min(
                math.hypot(ax - bx, ay - by)
                for ax, ay in (
                    (gap_wall_a.x1, gap_wall_a.y1),
                    (gap_wall_a.x2, gap_wall_a.y2),
                )
                for bx, by in (
                    (gap_wall_b.x1, gap_wall_b.y1),
                    (gap_wall_b.x2, gap_wall_b.y2),
                )
            )

            # Resolve the stronger two-jamb representation directly from
            # the wall discontinuity endpoints. The legacy window detector
            # assumes both jambs are near one continuous wall segment, which
            # is incompatible with a real gap where each jamb belongs to the
            # opposite side of the interruption.
            paired_window_jamb_ids: set[str] = set()

            endpoints_a = (
                (float(gap_wall_a.x1), float(gap_wall_a.y1)),
                (float(gap_wall_a.x2), float(gap_wall_a.y2)),
            )
            endpoints_b = (
                (float(gap_wall_b.x1), float(gap_wall_b.y1)),
                (float(gap_wall_b.x2), float(gap_wall_b.y2)),
            )
            gap_endpoint_a, gap_endpoint_b = min(
                (
                    (point_a, point_b)
                    for point_a in endpoints_a
                    for point_b in endpoints_b
                ),
                key=lambda pair: math.hypot(
                    pair[0][0] - pair[1][0],
                    pair[0][1] - pair[1][1],
                ),
            )

            def _parallel_segments(
                first: LegacyPlanSegment,
                second: LegacyPlanSegment,
            ) -> bool:
                delta = abs(first.angle_deg - second.angle_deg) % 180.0
                return min(delta, 180.0 - delta) <= 5.0

            def _perpendicular_to_wall(segment: LegacyPlanSegment) -> bool:
                delta = abs(segment.angle_deg - gap_wall_a.angle_deg) % 180.0
                return abs(delta - 90.0) <= 15.0

            left_jambs = tuple(
                segment
                for segment in endpoint_touching_segments(gap_endpoint_a)
                if segment is not gap_wall_a
                and segment is not gap_wall_b
                and _perpendicular_to_wall(segment)
            )
            right_jambs = tuple(
                segment
                for segment in endpoint_touching_segments(gap_endpoint_b)
                if segment is not gap_wall_a
                and segment is not gap_wall_b
                and _perpendicular_to_wall(segment)
            )
            for first in left_jambs:
                for second in right_jambs:
                    if first is second or not _parallel_segments(first, second):
                        continue
                    first_record = record_for(first)
                    second_record = record_for(second)
                    if first_record is None or second_record is None:
                        continue
                    candidate = support_candidate(
                        support_records=(
                            gap_wall_records[0], gap_wall_records[1],
                            first_record, second_record,
                        ),  # type: ignore[arg-type]
                        structural_pattern=GAP_CORROBORATED_WINDOW_JAMB_PAIR,
                    )
                    if candidate is not None:
                        found[candidate.candidate_id] = candidate
                        paired_window_jamb_ids.update(
                            (
                                first_record.observation_id,
                                second_record.observation_id,
                            )
                        )

            candidate_door_indexes = sorted(
                {
                    *door_indexes_by_wall_identity.get(id(gap_wall_a), ()),
                    *door_indexes_by_wall_identity.get(id(gap_wall_b), ()),
                }
            )
            for door_index in candidate_door_indexes:
                door = doors[door_index]
                if door.wall_segment not in gap.wall_segments or door.jamb_segment is None:
                    continue
                door_center = midpoint(door.jamb_segment)
                if math.hypot(
                    door_center[0] - center[0], door_center[1] - center[1]
                ) > max(float(door.jamb_segment.length), gap_width):
                    continue
                jamb_record = record_for(door.jamb_segment)
                if jamb_record is None:
                    continue
                if jamb_record.observation_id in paired_window_jamb_ids:
                    continue
                candidate = support_candidate(
                    support_records=(
                        gap_wall_records[0], gap_wall_records[1], jamb_record
                    ),  # type: ignore[arg-type]
                    structural_pattern=GAP_CORROBORATED_DOOR_JAMB_LEAF,
                )
                if candidate is not None:
                    found[candidate.candidate_id] = candidate

        return tuple(found[key] for key in sorted(found))

    @classmethod
    def _visible_all_structural_candidates(
        cls,
        seed: SourceObservationRecord,
        records: tuple[SourceObservationRecord, ...],
    ) -> tuple[CandidateSemanticOpening, ...]:
        strong = cls._visible_structural_candidates(seed, records)
        generic = cls._visible_generic_correlated_candidates(seed, records)
        strong_sets = [set(item.source_observation_ids) for item in strong]
        retained = [
            item
            for item in generic
            if not any(set(item.source_observation_ids) <= support for support in strong_sets)
        ]
        by_id = {item.candidate_id: item for item in (*strong, *retained)}
        return tuple(by_id[key] for key in sorted(by_id))

    @staticmethod
    def _visible_page_candidate_key(
        seed: SourceObservationRecord,
    ) -> tuple[str, str, str, str, str]:
        return (
            seed.document_id,
            seed.revision_id,
            seed.source_sha256,
            seed.snapshot_id,
            seed.page_id,
        )

    @staticmethod
    def _candidate_membership_index(
        candidates: tuple[CandidateSemanticOpening, ...],
    ) -> dict[str, tuple[CandidateSemanticOpening, ...]]:
        membership: dict[str, list[CandidateSemanticOpening]] = {}
        for candidate in candidates:
            for observation_id in candidate.source_observation_ids:
                membership.setdefault(str(observation_id), []).append(candidate)
        return {
            observation_id: tuple(rows)
            for observation_id, rows in membership.items()
        }

    def _candidate_memberships_for_returned_candidates(
        self,
        seed: SourceObservationRecord,
        raw_candidates: tuple[CandidateSemanticOpening, ...],
        scoped_candidates: tuple[CandidateSemanticOpening, ...],
    ) -> tuple[
        dict[str, tuple[CandidateSemanticOpening, ...]],
        dict[str, tuple[CandidateSemanticOpening, ...]],
    ]:
        """Use cached indexes only when they match the returned candidate tuples.

        Normal producer execution returns the exact memoized tuples, so this is
        an O(1) lookup. Tests and future provider overrides may replace
        candidate discovery after a page cache already exists; in that case the
        returned tuple is authoritative and its membership index is rebuilt
        without changing candidate semantics.
        """

        key = self._visible_page_candidate_key(seed)
        cached_raw = self._visible_candidate_cache.get(key)
        if raw_candidates is cached_raw:
            raw_membership = self._visible_candidate_membership_cache.get(key, {})
        else:
            raw_membership = self._candidate_membership_index(raw_candidates)

        if scoped_candidates is raw_candidates or (
            self._source_visibility_producer is None
            and scoped_candidates == raw_candidates
        ):
            scoped_membership = raw_membership
        else:
            cached_scope = self._visible_viewport_scope_cache.get(key)
            cached_scoped = cached_scope[0] if cached_scope is not None else None
            if scoped_candidates is cached_scoped:
                scoped_membership = (
                    self._visible_viewport_candidate_membership_cache.get(key, {})
                )
            else:
                scoped_membership = self._candidate_membership_index(
                    scoped_candidates
                )
        return raw_membership, scoped_membership

    def _visible_candidates_for(
        self,
        seed: SourceObservationRecord,
        records: tuple[SourceObservationRecord, ...],
    ) -> tuple[CandidateSemanticOpening, ...]:
        """Memoize deterministic multi-path candidate discovery per source page."""

        key = self._visible_page_candidate_key(seed)
        cached = self._visible_candidate_cache.get(key)
        if cached is not None:
            return cached
        candidates = self._visible_all_structural_candidates(seed, records)
        self._visible_candidate_cache[key] = candidates
        self._visible_candidate_membership_cache[key] = (
            self._candidate_membership_index(candidates)
        )
        return candidates

    def _viewport_scoped_visible_candidates_for(
        self,
        seed: SourceObservationRecord,
        records: tuple[SourceObservationRecord, ...],
    ) -> tuple[
        tuple[CandidateSemanticOpening, ...],
        dict[str, object],
        tuple[str, ...],
    ]:
        """Return only candidates positively owned by one authenticated floor-plan viewport.

        Raw page-wide candidate discovery remains available for diagnostics.
        This promotion gate is enabled only for authorities constructed from the
        producer-owned SourceVisibilityProducer.
        """
        candidates = self._visible_candidates_for(seed, records)
        key = self._visible_page_candidate_key(seed)
        if self._source_visibility_producer is None:
            self._visible_viewport_candidate_membership_cache[key] = (
                self._visible_candidate_membership_cache.get(key, {})
            )
            return candidates, {}, ()

        cached = self._visible_viewport_scope_cache.get(key)
        if cached is not None:
            return cached

        from pb_physical_opening_viewport_scope_authority import (
            classify_opening_candidate_viewport_scopes,
        )

        scope_result = classify_opening_candidate_viewport_scopes(
            source_visibility_producer=self._source_visibility_producer,
            revision_id=seed.revision_id,
            page_id=seed.page_id,
            snapshot_id=seed.snapshot_id,
            candidates=candidates,
            records=records,
        )
        decisions = dict(scope_result.decisions)
        if scope_result.status is not EvidenceResolutionStatus.CORROBORATED:
            result = ((), decisions, tuple(scope_result.reason_codes))
            self._visible_viewport_scope_cache[key] = result
            self._visible_viewport_candidate_membership_cache[key] = {}
            return result

        if not tuple(scope_result.authenticated_viewports):
            result = (candidates, decisions, tuple(scope_result.reason_codes))
            self._visible_viewport_scope_cache[key] = result
            self._visible_viewport_candidate_membership_cache[key] = (
                self._visible_candidate_membership_cache.get(key, {})
            )
            return result

        promoted: list[CandidateSemanticOpening] = []
        for candidate in candidates:
            decision = decisions.get(candidate.candidate_id)
            if decision is None or not bool(getattr(decision, "promotable", False)):
                continue
            viewport_id = str(getattr(decision, "viewport_id", "") or "").strip()
            if not viewport_id:
                continue
            if candidate.viewport_id is not None and str(candidate.viewport_id) != viewport_id:
                continue
            promoted.append(replace(candidate, viewport_id=viewport_id))

        promoted_tuple = tuple(promoted)
        result = (
            promoted_tuple,
            decisions,
            tuple(scope_result.reason_codes),
        )
        self._visible_viewport_scope_cache[key] = result
        self._visible_viewport_candidate_membership_cache[key] = (
            self._candidate_membership_index(promoted_tuple)
        )
        return result

    @staticmethod
    def _scope_reason_codes_for(
        raw_containing: Sequence[CandidateSemanticOpening],
        decisions: dict[str, object],
        fallback: tuple[str, ...],
    ) -> tuple[str, ...]:
        scopes = tuple(
            sorted(
                {
                    str(getattr(decisions.get(candidate.candidate_id), "scope", "") or "")
                    for candidate in raw_containing
                    if decisions.get(candidate.candidate_id) is not None
                }
                - {""}
            )
        )
        if scopes:
            return _dedupe_reason_codes(
                (OPENING_CANDIDATE_VIEWPORT_SCOPE_UNRESOLVED,),
                scopes,
                fallback,
            )
        return _dedupe_reason_codes(
            (OPENING_CANDIDATE_VIEWPORT_SCOPE_UNRESOLVED,),
            fallback,
        )

    def assess_visible_candidate_closure(
        self,
        selector: ObservationSelector,
    ) -> PhysicalOpeningCandidateClosureResult:
        """Assess whether all producer-detected opening-like candidates are resolved.

        This is page-local and source-owned. It does not claim that arbitrary
        geometry can never encode an opening; it proves only that every
        candidate emitted by the registered visible-geometry path family on
        this exact page is either subsumed by a proven physical opening or
        remains explicit unresolved evidence.
        """
        if not isinstance(selector, ObservationSelector):
            raise TypeError("selector must be ObservationSelector")
        if self._source_visibility_authority is None:
            return PhysicalOpeningCandidateClosureResult(
                status=EvidenceResolutionStatus.ABSTAINED,
                page_id=None,
                candidate_universe_complete=False,
                raw_candidate_count=0,
                resolved_candidate_count=0,
                unresolved_candidate_ids=(),
                unresolved_observation_ids=(),
                reason_codes=(VISIBLE_SOURCE_AUTHORITY_REQUIRED,),
            )

        visibility = self._source_visibility_authority
        source_result = self._resolve_visible_cached(selector)
        if (
            source_result.status is not EvidenceResolutionStatus.CORROBORATED
            or source_result.observation is None
        ):
            return PhysicalOpeningCandidateClosureResult(
                status=_source_failure_status(source_result),
                page_id=None,
                candidate_universe_complete=False,
                raw_candidate_count=0,
                resolved_candidate_count=0,
                unresolved_candidate_ids=(),
                unresolved_observation_ids=(),
                reason_codes=_dedupe_reason_codes(source_result.reason_codes),
            )

        records, failures = self._visible_snapshot_records(source_result)
        if failures:
            return PhysicalOpeningCandidateClosureResult(
                status=_source_failure_status(*failures),
                page_id=str(source_result.observation.page_id),
                candidate_universe_complete=False,
                raw_candidate_count=0,
                resolved_candidate_count=0,
                unresolved_candidate_ids=(),
                unresolved_observation_ids=(),
                reason_codes=_dedupe_reason_codes(
                    (SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,),
                    *tuple(result.reason_codes for result in failures),
                ),
            )

        seed = source_result.observation
        scoped_records = tuple(
            record
            for record in records
            if record.observation_kind in {
                NATIVE_PDF_VISIBLE_SEGMENT,
                RASTER_PDF_VISIBLE_SEGMENT,
            }
            and record.document_id == seed.document_id
            and record.revision_id == seed.revision_id
            and record.source_sha256 == seed.source_sha256
            and record.snapshot_id == seed.snapshot_id
            and record.page_id == seed.page_id
            and record.viewport_id is None
            and _line_geometry(record) is not None
        )

        segments: list[LegacyPlanSegment] = []
        record_by_index: dict[int, SourceObservationRecord] = {}
        for index, record in enumerate(scoped_records):
            line = _line_geometry(record)
            assert line is not None
            segments.append(
                LegacyPlanSegment(
                    x1=line[0], y1=line[1], x2=line[2], y2=line[3],
                    drawing_index=index,
                )
            )
            record_by_index[index] = record

        walls = detect_wall_lines(segments) if segments else ()
        doors = detect_door_candidates(
            segments, walls, (), page_no=int(seed.page_id)
        ) if walls else ()
        windows = detect_window_candidates(
            segments, walls, (), page_no=int(seed.page_id)
        ) if walls else ()
        gaps = detect_gap_candidates(
            segments, walls, (), page_no=int(seed.page_id)
        ) if walls else ()

        def record_for(segment: LegacyPlanSegment | None) -> Optional[SourceObservationRecord]:
            if segment is None:
                return None
            return record_by_index.get(int(segment.drawing_index))

        raw_candidates: dict[str, frozenset[str]] = {}

        def add_raw(pattern: str, support_records: tuple[Optional[SourceObservationRecord], ...]) -> None:
            if any(record is None for record in support_records):
                return
            ids = tuple(
                sorted({record.observation_id for record in support_records if record is not None})
            )
            if len(ids) < 2:
                return
            candidate_id = stable_contract_id(
                "physical_opening_raw_candidate",
                {
                    "document_id": seed.document_id,
                    "revision_id": seed.revision_id,
                    "source_sha256": seed.source_sha256,
                    "snapshot_id": seed.snapshot_id,
                    "page_id": seed.page_id,
                    "pattern": pattern,
                    "source_observation_ids": ids,
                },
                digest_chars=32,
            )
            raw_candidates[candidate_id] = frozenset(ids)

        for gap in gaps:
            if gap.wall_segments:
                add_raw(
                    "wall_gap_candidate",
                    (record_for(gap.wall_segments[0]), record_for(gap.wall_segments[1])),
                )

        for door in doors:
            add_raw(
                "door_jamb_leaf_candidate",
                (record_for(door.wall_segment), record_for(door.jamb_segment)),
            )

        for window in windows:
            if len(window.parallel_segments) == 2:
                add_raw(
                    "window_jamb_pair_candidate",
                    (
                        record_for(window.wall_segment),
                        record_for(window.parallel_segments[0]),
                        record_for(window.parallel_segments[1]),
                    ),
                )

        proven = self._visible_candidates_for(seed, records)
        promotable, viewport_decisions, viewport_reasons = (
            self._viewport_scoped_visible_candidates_for(seed, records)
        )
        # Structural membership is not existence authority. A selected source
        # hypothesis opposed by complete annotation evidence remains unresolved
        # in closure; retain its raw support instead of silently discarding it.
        proven_supports = []
        for candidate in promotable:
            support = frozenset(candidate.source_observation_ids)
            for observation_id in candidate.source_observation_ids:
                existence = self.prove_existence(
                    replace(selector, observation_id=observation_id)
                )
                if (
                    existence.status is EvidenceResolutionStatus.CORROBORATED
                    and existence.existence_record is not None
                    and frozenset(existence.existence_record.source_observation_ids)
                    == support
                ):
                    proven_supports.append(support)
                    break
                if (
                    existence.candidate is not None
                    and existence.candidate.candidate_id == candidate.candidate_id
                ):
                    raw_candidates[candidate.candidate_id] = support
        typed_non_plan_supports = tuple(
            frozenset(candidate.source_observation_ids)
            for candidate in proven
            if str(
                getattr(viewport_decisions.get(candidate.candidate_id), "scope", "")
                or ""
            )
            == "in_authenticated_non_plan_viewport"
        )

        unresolved_ids: list[str] = []
        unresolved_observation_ids: set[str] = set()
        resolved_count = 0
        for candidate_id, support in raw_candidates.items():
            if any(support <= proven_support for proven_support in proven_supports):
                resolved_count += 1
            elif any(support <= non_plan for non_plan in typed_non_plan_supports):
                # Authenticated non-plan viewport ownership is a typed negative
                # for floor-plan opening promotion. It disposes this covered
                # candidate path without asserting universal non-existence.
                resolved_count += 1
            else:
                unresolved_ids.append(candidate_id)
                unresolved_observation_ids.update(support)

        complete = not unresolved_ids
        return PhysicalOpeningCandidateClosureResult(
            status=EvidenceResolutionStatus.CORROBORATED,
            page_id=str(seed.page_id),
            candidate_universe_complete=complete,
            raw_candidate_count=len(raw_candidates),
            resolved_candidate_count=resolved_count,
            unresolved_candidate_ids=tuple(sorted(unresolved_ids)),
            unresolved_observation_ids=tuple(sorted(unresolved_observation_ids)),
            reason_codes=(
                (PHYSICAL_OPENING_CANDIDATE_CLOSURE_RESOLVED,)
                if complete
                else (PHYSICAL_OPENING_CANDIDATE_CLOSURE_UNRESOLVED,)
            ),
        )

    def assess_raster_candidate_closure(
        self, selector: ObservationSelector,
    ) -> PhysicalOpeningCandidateClosureResult:
        """Audit every registered raster wall-band gap, including weak gaps.

        Complete receipt coverage is checked afresh before cached geometry is
        consumed. A gap closes only when its exact aperture and every source
        support are subsumed by an independently re-proven, viewport-owned
        physical opening. Bare gaps, rejected/ambiguous candidates, failed
        render paths and an empty detector result cannot establish completeness.
        This proves the registered candidate family, not universal nonexistence.
        """
        if not isinstance(selector, ObservationSelector):
            raise TypeError("selector must be ObservationSelector")
        visibility = self._source_visibility_authority
        producer = self._source_visibility_producer

        def blocked(status, *reasons, page_id=None):
            return PhysicalOpeningCandidateClosureResult(
                status=status, page_id=page_id, candidate_universe_complete=False,
                raw_candidate_count=0, resolved_candidate_count=0,
                unresolved_candidate_ids=(), unresolved_observation_ids=(),
                reason_codes=_dedupe_reason_codes(tuple(reasons)),
            )

        if visibility is None or producer is None:
            return blocked(EvidenceResolutionStatus.ABSTAINED,
                           VISIBLE_SOURCE_AUTHORITY_REQUIRED)
        seed_result = visibility.resolve_raster_opening_primitive(selector)
        if (seed_result.status is not EvidenceResolutionStatus.CORROBORATED
                or seed_result.observation is None):
            return blocked(_source_failure_status(seed_result), *seed_result.reason_codes)
        seed = seed_result.observation
        published = producer.published_snapshot_for_revision(selector.revision_id)
        if published is None or published.snapshot.snapshot_id != selector.snapshot_id:
            return blocked(EvidenceResolutionStatus.ABSTAINED,
                           SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE, page_id=seed.page_id)
        ids = visibility.raster_opening_primitive_observation_ids_for_snapshot(
            selector.snapshot_id)
        if ids != frozenset(published.raster_opening_primitive_observation_ids):
            return blocked(EvidenceResolutionStatus.CONFLICT,
                           SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE, page_id=seed.page_id)
        records = []
        for observation_id in sorted(ids):
            result = visibility.resolve_raster_opening_primitive(
                replace(selector, observation_id=observation_id))
            if (result.status is not EvidenceResolutionStatus.CORROBORATED
                    or result.observation is None):
                return blocked(_source_failure_status(result),
                               SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,
                               *result.reason_codes, page_id=seed.page_id)
            records.append(result.observation)
        # Rendering rechecks immutable source bytes and the current page parent,
        # including when candidate geometry was cached by earlier existence calls.
        try:
            producer.render_raster_opening_source_page(seed.revision_id, seed.page_id)
        except Exception:
            return blocked(EvidenceResolutionStatus.ABSTAINED,
                           SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE, page_id=seed.page_id)
        raw = self._raster_framed_candidates_for(seed, tuple(records))
        scoped = self._viewport_scoped_raster_candidates_for(seed, tuple(records), raw)
        proven = []
        for candidate in scoped:
            support = frozenset(candidate.source_observation_ids)
            for observation_id in candidate.source_observation_ids:
                existence = self.prove_existence(replace(selector, observation_id=observation_id))
                if (existence.status is EvidenceResolutionStatus.CORROBORATED
                        and existence.existence_record is not None
                        and existence.candidate is not None
                        and existence.candidate.candidate_id == candidate.candidate_id
                        and frozenset(existence.existence_record.source_observation_ids) == support):
                    proven.append((support, existence.existence_record.aperture_bbox_pt))
                    break
        key = self._visible_page_candidate_key(seed)
        gaps = self._raster_gap_candidate_audit_cache.get(key)
        unresolved = []
        unresolved_support = set(self._raster_swing_ambiguous_support_cache.get(key, ()))
        resolved_count = 0
        for gap_id, support, aperture in gaps or ():
            if any(support <= owner_support and aperture == owner_aperture
                   for owner_support, owner_aperture in proven):
                resolved_count += 1
            else:
                unresolved.append(gap_id)
                unresolved_support.update(support)
        complete = bool(gaps) and not (
            unresolved or unresolved_support or key in self._raster_gap_audit_incomplete)
        return PhysicalOpeningCandidateClosureResult(
            status=EvidenceResolutionStatus.CORROBORATED, page_id=str(seed.page_id),
            candidate_universe_complete=complete, raw_candidate_count=len(gaps or ()),
            resolved_candidate_count=resolved_count,
            unresolved_candidate_ids=tuple(sorted(unresolved)),
            unresolved_observation_ids=tuple(sorted(unresolved_support)),
            reason_codes=((PHYSICAL_OPENING_CANDIDATE_CLOSURE_RESOLVED,)
                          if complete else (PHYSICAL_OPENING_CANDIDATE_CLOSURE_UNRESOLVED,)),
        )

    @staticmethod
    def _single_raw_candidate(
        observation: SourceObservationRecord,
    ) -> CandidateSemanticOpening:
        roots = tuple(sorted(observation.derivation_parent_ids))
        payload = {
            "document_id": observation.document_id,
            "revision_id": observation.revision_id,
            "source_sha256": observation.source_sha256,
            "snapshot_id": observation.snapshot_id,
            "page_id": observation.page_id,
            "viewport_id": observation.viewport_id,
            "source_observation_ids": (observation.observation_id,),
            "source_lineage_root_ids": roots,
            "structural_pattern": STRUCTURAL_OPENING_CANDIDATE,
        }
        reasons = (STRUCTURAL_OPENING_CANDIDATE, VISIBLE_SOURCE_AUTHORITY_REQUIRED)
        if observation.observation_kind in {WALL_FACE_INTERRUPTION_KIND, OPENING_JAMB_BOUNDARY_KIND} \
                and _line_geometry(observation) is None:
            reasons = _dedupe_reason_codes(reasons, (INVALID_STRUCTURAL_GEOMETRY,))
        return CandidateSemanticOpening(
            candidate_id=stable_contract_id("physical_opening_candidate", payload, digest_chars=32),
            source_observation_ids=(observation.observation_id,),
            source_lineage_root_ids=roots,
            document_id=observation.document_id,
            revision_id=observation.revision_id,
            source_sha256=observation.source_sha256,
            snapshot_id=observation.snapshot_id,
            page_id=observation.page_id,
            viewport_id=observation.viewport_id,
            structural_pattern=STRUCTURAL_OPENING_CANDIDATE,
            status=EvidenceResolutionStatus.CANDIDATE,
            reason_codes=reasons,
        )

    def visible_candidate_structures(
        self,
        selector: ObservationSelector,
    ) -> PhysicalOpeningCandidateStructureResult:
        """Return the page's discovered candidates with their member observations.

        Read-only diagnostic accessor.  It follows the same source-visibility and
        snapshot-integrity gates as ``classify_disposition`` and returns the same
        memoized page candidates that method inspects; it decides nothing and
        changes no other result.  The selector only names the page (and the
        authenticated snapshot) whose candidates are wanted.
        """

        if not isinstance(selector, ObservationSelector):
            raise TypeError("selector must be ObservationSelector")
        if self._source_visibility_authority is None:
            return PhysicalOpeningCandidateStructureResult(
                status=EvidenceResolutionStatus.ABSTAINED,
                page_id=None,
                candidates=(),
                reason_codes=(VISIBLE_SOURCE_AUTHORITY_REQUIRED,),
            )

        visibility = self._source_visibility_authority
        source_result = self._resolve_visible_cached(selector)
        if (
            source_result.status is not EvidenceResolutionStatus.CORROBORATED
            or source_result.observation is None
        ):
            return PhysicalOpeningCandidateStructureResult(
                status=_source_failure_status(source_result),
                page_id=None,
                candidates=(),
                reason_codes=_dedupe_reason_codes(source_result.reason_codes),
            )

        records, failures = self._visible_snapshot_records(source_result)
        if failures:
            return PhysicalOpeningCandidateStructureResult(
                status=_source_failure_status(*failures),
                page_id=str(source_result.observation.page_id),
                candidates=(),
                reason_codes=_dedupe_reason_codes(
                    (SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,),
                    *tuple(result.reason_codes for result in failures),
                ),
            )

        observation = source_result.observation
        return PhysicalOpeningCandidateStructureResult(
            status=EvidenceResolutionStatus.CANDIDATE,
            page_id=str(observation.page_id),
            candidates=self._visible_candidates_for(observation, records),
            reason_codes=(STRUCTURAL_OPENING_CANDIDATE,),
        )

    def classify_disposition(
        self,
        selector: ObservationSelector,
    ) -> PhysicalOpeningDispositionResult:
        """Classify one source-visible observation under covered structural paths."""

        if not isinstance(selector, ObservationSelector):
            raise TypeError("selector must be ObservationSelector")
        if self._source_visibility_authority is None:
            return PhysicalOpeningDispositionResult(
                status=EvidenceResolutionStatus.ABSTAINED,
                disposition=PHYSICAL_OPENING_DISPOSITION_UNRESOLVED,
                reason_codes=(VISIBLE_SOURCE_AUTHORITY_REQUIRED,),
            )

        visibility = self._source_visibility_authority
        primitive_result = visibility.resolve_raster_opening_primitive(selector)
        if (
            primitive_result.status is EvidenceResolutionStatus.CORROBORATED
            and primitive_result.observation is not None
        ):
            existence = self._prove_raster_framed_existence(
                selector,
                primitive_result,
            )
            candidate_ids = (
                ()
                if existence.candidate is None
                else (existence.candidate.candidate_id,)
            )
            if (
                existence.status is EvidenceResolutionStatus.CORROBORATED
                and existence.existence_record is not None
            ):
                return PhysicalOpeningDispositionResult(
                    status=EvidenceResolutionStatus.CORROBORATED,
                    disposition=PHYSICAL_OPENING_DISPOSITION_OPENING_SUPPORT,
                    reason_codes=existence.reason_codes,
                    candidate_ids=candidate_ids,
                    existence_record=existence.existence_record,
                )
            if existence.status is EvidenceResolutionStatus.CONFLICT:
                return PhysicalOpeningDispositionResult(
                    status=EvidenceResolutionStatus.CONFLICT,
                    disposition=PHYSICAL_OPENING_DISPOSITION_CONFLICT,
                    reason_codes=existence.reason_codes,
                    candidate_ids=candidate_ids,
                )
            return PhysicalOpeningDispositionResult(
                status=(
                    EvidenceResolutionStatus.CANDIDATE
                    if existence.candidate is not None
                    else EvidenceResolutionStatus.ABSTAINED
                ),
                disposition=(
                    PHYSICAL_OPENING_DISPOSITION_CANDIDATE
                    if existence.candidate is not None
                    else PHYSICAL_OPENING_DISPOSITION_UNRESOLVED
                ),
                reason_codes=existence.reason_codes,
                candidate_ids=candidate_ids,
            )
        if VISIBILITY_RECEIPT_UNAVAILABLE not in primitive_result.reason_codes:
            status = _source_failure_status(primitive_result)
            return PhysicalOpeningDispositionResult(
                status=status,
                disposition=(
                    PHYSICAL_OPENING_DISPOSITION_CONFLICT
                    if status is EvidenceResolutionStatus.CONFLICT
                    else PHYSICAL_OPENING_DISPOSITION_UNRESOLVED
                ),
                reason_codes=_dedupe_reason_codes(primitive_result.reason_codes),
            )

        visible_cache_key = (
            str(selector.document_id),
            str(selector.revision_id),
            str(selector.source_sha256),
            str(selector.snapshot_id),
            str(selector.observation_id),
        )
        cached_disposition = self._visible_disposition_cache.get(visible_cache_key)
        if cached_disposition is not None:
            return cached_disposition

        def cache_visible(
            result: PhysicalOpeningDispositionResult,
        ) -> PhysicalOpeningDispositionResult:
            self._visible_disposition_cache[visible_cache_key] = result
            return result

        source_result = self._resolve_visible_cached(selector)
        if (
            source_result.status is not EvidenceResolutionStatus.CORROBORATED
            or source_result.observation is None
        ):
            return cache_visible(PhysicalOpeningDispositionResult(
                status=_source_failure_status(source_result),
                disposition=(
                    PHYSICAL_OPENING_DISPOSITION_CONFLICT
                    if source_result.status is EvidenceResolutionStatus.CONFLICT
                    else PHYSICAL_OPENING_DISPOSITION_UNRESOLVED
                ),
                reason_codes=_dedupe_reason_codes(source_result.reason_codes),
            ))

        records, failures = self._visible_snapshot_records(source_result)
        if failures:
            status = _source_failure_status(*failures)
            return cache_visible(PhysicalOpeningDispositionResult(
                status=status,
                disposition=(
                    PHYSICAL_OPENING_DISPOSITION_CONFLICT
                    if status is EvidenceResolutionStatus.CONFLICT
                    else PHYSICAL_OPENING_DISPOSITION_UNRESOLVED
                ),
                reason_codes=_dedupe_reason_codes(
                    (SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,),
                    *tuple(result.reason_codes for result in failures),
                ),
            ))

        observation = source_result.observation
        raw_candidates = self._visible_candidates_for(observation, records)
        candidates, viewport_decisions, viewport_reasons = (
            self._viewport_scoped_visible_candidates_for(observation, records)
        )
        raw_membership, scoped_membership = (
            self._candidate_memberships_for_returned_candidates(
                observation,
                raw_candidates,
                candidates,
            )
        )
        raw_containing = raw_membership.get(observation.observation_id, ())
        containing = scoped_membership.get(observation.observation_id, ())

        if self._source_visibility_producer is not None and raw_containing and not containing:
            raw_scopes = {
                str(getattr(viewport_decisions.get(candidate.candidate_id), "scope", "") or "")
                for candidate in raw_containing
            }
            if raw_scopes and raw_scopes <= {"in_authenticated_non_plan_viewport"}:
                return cache_visible(PhysicalOpeningDispositionResult(
                    status=EvidenceResolutionStatus.CORROBORATED,
                    disposition=PHYSICAL_OPENING_DISPOSITION_NO_CANDIDATE,
                    reason_codes=_dedupe_reason_codes(
                        (OPENING_CANDIDATE_OUTSIDE_FLOOR_PLAN_SCOPE,),
                        tuple(sorted(raw_scopes)),
                        viewport_reasons,
                    ),
                ))
            return cache_visible(PhysicalOpeningDispositionResult(
                status=EvidenceResolutionStatus.ABSTAINED,
                disposition=PHYSICAL_OPENING_DISPOSITION_UNRESOLVED,
                reason_codes=self._scope_reason_codes_for(
                    raw_containing, viewport_decisions, viewport_reasons
                ),
                candidate_ids=tuple(sorted(candidate.candidate_id for candidate in raw_containing)),
            ))

        if len(containing) > 1:
            return cache_visible(PhysicalOpeningDispositionResult(
                status=EvidenceResolutionStatus.CONFLICT,
                disposition=PHYSICAL_OPENING_DISPOSITION_CONFLICT,
                reason_codes=(AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES,),
                candidate_ids=tuple(
                    sorted(candidate.candidate_id for candidate in containing)
                ),
            ))
        if len(containing) == 1:
            existence = self.prove_existence(selector)
            if (
                existence.status is EvidenceResolutionStatus.CORROBORATED
                and existence.existence_record is not None
            ):
                return cache_visible(PhysicalOpeningDispositionResult(
                    status=EvidenceResolutionStatus.CORROBORATED,
                    disposition=PHYSICAL_OPENING_DISPOSITION_OPENING_SUPPORT,
                    reason_codes=existence.reason_codes,
                    candidate_ids=(containing[0].candidate_id,),
                    existence_record=existence.existence_record,
                ))
            return cache_visible(PhysicalOpeningDispositionResult(
                status=EvidenceResolutionStatus.CANDIDATE,
                disposition=PHYSICAL_OPENING_DISPOSITION_CANDIDATE,
                reason_codes=containing[0].reason_codes,
                candidate_ids=(containing[0].candidate_id,),
            ))

        return cache_visible(PhysicalOpeningDispositionResult(
            status=EvidenceResolutionStatus.CORROBORATED,
            disposition=PHYSICAL_OPENING_DISPOSITION_NO_CANDIDATE,
            reason_codes=(VISIBLE_WALL_CONTINUATION_REQUIRED,),
        ))

    def prove_existence(self, selector: ObservationSelector) -> PhysicalOpeningExistenceResult:
        if not isinstance(selector, ObservationSelector):
            raise TypeError("selector must be ObservationSelector")

        if self._source_visibility_authority is None:
            source = self._source_observation_authority
            assert source is not None
            source_result = source.resolve(selector)
            if source_result.status is not EvidenceResolutionStatus.CORROBORATED or source_result.observation is None:
                return PhysicalOpeningExistenceResult(
                    status=_source_failure_status(source_result), proposition=None,
                    physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                    reason_codes=_dedupe_reason_codes(source_result.reason_codes),
                    source_observation=source_result,
                    missing_upstream_capability=MISSING_PHYSICAL_OPENING_SEMANTIC_CAPABILITY,
                )
            records, failures = self._raw_snapshot_records(source_result)
            if failures:
                return PhysicalOpeningExistenceResult(
                    status=_source_failure_status(*failures), proposition=None,
                    physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                    reason_codes=_dedupe_reason_codes(
                        (SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,),
                        *tuple(result.reason_codes for result in failures),
                    ), source_observation=source_result,
                )
            observation = source_result.observation
            candidates = self._raw_structural_candidates(observation, records)
            containing = tuple(
                candidate for candidate in candidates
                if observation.observation_id in candidate.source_observation_ids
            )
            if len(containing) > 1:
                return PhysicalOpeningExistenceResult(
                    status=EvidenceResolutionStatus.CONFLICT, proposition=None,
                    physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                    reason_codes=(AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES,),
                    source_observation=source_result,
                )
            if observation.observation_kind in {
                WALL_FACE_INTERRUPTION_KIND, OPENING_JAMB_BOUNDARY_KIND,
                *WEAK_PHYSICAL_OPENING_CANDIDATE_KINDS,
            }:
                candidate = containing[0] if containing else self._single_raw_candidate(observation)
                return PhysicalOpeningExistenceResult(
                    status=EvidenceResolutionStatus.CANDIDATE, proposition=None,
                    physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                    reason_codes=candidate.reason_codes,
                    source_observation=source_result, candidate=candidate,
                    missing_upstream_capability=MISSING_PHYSICAL_OPENING_SEMANTIC_CAPABILITY,
                )
            return PhysicalOpeningExistenceResult(
                status=EvidenceResolutionStatus.ABSTAINED, proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=(AUTHORITATIVE_PHYSICAL_OPENING_SEMANTICS_UNAVAILABLE,),
                source_observation=source_result,
                missing_upstream_capability=MISSING_PHYSICAL_OPENING_SEMANTIC_CAPABILITY,
            )

        visibility = self._source_visibility_authority
        primitive_result = visibility.resolve_raster_opening_primitive(selector)
        if (
            primitive_result.status is EvidenceResolutionStatus.CORROBORATED
            and primitive_result.observation is not None
        ):
            return self._prove_raster_framed_existence(
                selector,
                primitive_result,
            )
        if VISIBILITY_RECEIPT_UNAVAILABLE not in primitive_result.reason_codes:
            return PhysicalOpeningExistenceResult(
                status=_source_failure_status(primitive_result),
                proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=_dedupe_reason_codes(primitive_result.reason_codes),
                source_observation=primitive_result,
            )

        visible_cache_key = (
            str(selector.document_id),
            str(selector.revision_id),
            str(selector.source_sha256),
            str(selector.snapshot_id),
            str(selector.observation_id),
        )
        cached_existence = self._visible_existence_cache.get(visible_cache_key)
        if cached_existence is not None:
            return cached_existence

        def cache_visible(result: PhysicalOpeningExistenceResult) -> PhysicalOpeningExistenceResult:
            self._visible_existence_cache[visible_cache_key] = result
            return result

        source_result = self._resolve_visible_cached(selector)
        if source_result.status is not EvidenceResolutionStatus.CORROBORATED or source_result.observation is None:
            return cache_visible(PhysicalOpeningExistenceResult(
                status=_source_failure_status(source_result), proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=_dedupe_reason_codes(source_result.reason_codes),
                source_observation=source_result,
                missing_upstream_capability=MISSING_PHYSICAL_OPENING_SEMANTIC_CAPABILITY,
            ))
        records, failures = self._visible_snapshot_records(source_result)
        if failures:
            return cache_visible(PhysicalOpeningExistenceResult(
                status=_source_failure_status(*failures), proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=_dedupe_reason_codes(
                    (SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,),
                    *tuple(result.reason_codes for result in failures),
                ), source_observation=source_result,
            ))
        observation = source_result.observation
        raw_candidates = self._visible_candidates_for(observation, records)
        candidates, viewport_decisions, viewport_reasons = (
            self._viewport_scoped_visible_candidates_for(observation, records)
        )
        raw_membership, scoped_membership = (
            self._candidate_memberships_for_returned_candidates(
                observation,
                raw_candidates,
                candidates,
            )
        )
        raw_containing = raw_membership.get(observation.observation_id, ())
        containing = scoped_membership.get(observation.observation_id, ())
        if self._source_visibility_producer is not None and raw_containing and not containing:
            return cache_visible(PhysicalOpeningExistenceResult(
                status=EvidenceResolutionStatus.ABSTAINED,
                proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=self._scope_reason_codes_for(
                    raw_containing, viewport_decisions, viewport_reasons
                ),
                source_observation=source_result,
                missing_upstream_capability=MISSING_PHYSICAL_OPENING_SEMANTIC_CAPABILITY,
            ))
        if len(containing) > 1:
            return cache_visible(PhysicalOpeningExistenceResult(
                status=EvidenceResolutionStatus.CONFLICT, proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=(AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES,),
                source_observation=source_result,
            ))
        if len(containing) != 1 or source_result.snapshot is None:
            return cache_visible(PhysicalOpeningExistenceResult(
                status=EvidenceResolutionStatus.ABSTAINED, proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=(VISIBLE_WALL_CONTINUATION_REQUIRED,),
                source_observation=source_result,
                missing_upstream_capability=MISSING_PHYSICAL_OPENING_SEMANTIC_CAPABILITY,
            ))

        candidate = containing[0]
        if (self._source_visibility_producer is not None
                and candidate.structural_pattern == JAMB_BOUNDED_TWO_FACE_INTERRUPTION):
            opposition_reason = "native_dimension_annotation_opposes_opening"
            try:
                opposing = self._source_visibility_producer.native_dimension_cap_evidence(
                    selector, opening_support_ids=candidate.source_observation_ids)
                if not opposing:
                    opposing = self._source_visibility_producer.native_unstroked_fill_evidence(
                        selector, support_observation_ids=candidate.source_observation_ids)
                    opposition_reason = 'native_unstroked_fill_boundary_opposes_opening'
            except RuntimeError:
                return cache_visible(PhysicalOpeningExistenceResult(
                    status=EvidenceResolutionStatus.ABSTAINED, proposition=None,
                    physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                    reason_codes=('opening_annotation_source_integrity_unproven',),
                    source_observation=source_result, candidate=candidate))
            if opposing:
                # Retain the complete hypothesis and its exact opposing source
                # evidence. Annotation opposition is not non-existence proof
                # and does not dispose the raw universe for count authority.
                return cache_visible(PhysicalOpeningExistenceResult(
                    status=EvidenceResolutionStatus.ABSTAINED, proposition=None,
                    physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                    reason_codes=(opposition_reason,),
                    source_observation=source_result, candidate=candidate,
                    opposing_evidence_atoms=opposing))
        physical_geometry = _physical_opening_geometry_identity(candidate, records)
        if not physical_geometry:
            return cache_visible(PhysicalOpeningExistenceResult(
                status=EvidenceResolutionStatus.ABSTAINED,
                proposition=None,
                physical_opening_existence=PHYSICAL_OPENING_EXISTENCE_UNRESOLVED,
                reason_codes=(PHYSICAL_OPENING_IDENTITY_UNRESOLVED,),
                source_observation=source_result,
                candidate=candidate,
                missing_upstream_capability=AUTHORITATIVE_PHYSICAL_OPENING_IDENTITY_UNAVAILABLE,
            ))
        # Physical identity is source geometry, not evidence implementation.
        # snapshot_id, observation ids, lineage ids and producer version remain
        # on the record below as provenance and integrity evidence, but cannot
        # rename unchanged physical geometry across producer revisions.
        record_payload = {
            "document_id": candidate.document_id,
            "revision_id": candidate.revision_id,
            "source_sha256": candidate.source_sha256,
            "page_id": candidate.page_id,
            "semantic_class": "opening",
            "source_geometry": physical_geometry,
        }
        existence = PhysicalOpeningExistenceRecord(
            record_id=stable_contract_id("physical_opening_existence", record_payload, digest_chars=32),
            source_observation_ids=candidate.source_observation_ids,
            source_lineage_root_ids=candidate.source_lineage_root_ids,
            document_id=candidate.document_id,
            revision_id=candidate.revision_id,
            source_sha256=candidate.source_sha256,
            snapshot_id=candidate.snapshot_id,
            page_id=candidate.page_id,
            viewport_id=candidate.viewport_id,
            semantic_class="opening",
            status=EvidenceResolutionStatus.CORROBORATED,
            proposition=PHYSICAL_OPENING_EXISTS,
            structural_pattern=candidate.structural_pattern,
            diagnostic_confidence=1.0,
            blocking_reasons=(),
            structural_reason_codes=(STRUCTURAL_OPENING_EXISTENCE_RESOLVED,),
            producer_method=source_result.snapshot.producer_method,
            producer_version=source_result.snapshot.producer_version,
            producer_generation=source_result.snapshot.producer_generation,
        )
        return cache_visible(PhysicalOpeningExistenceResult(
            status=EvidenceResolutionStatus.CORROBORATED,
            proposition=PHYSICAL_OPENING_EXISTS,
            physical_opening_existence=PHYSICAL_OPENING_EXISTS,
            reason_codes=(STRUCTURAL_OPENING_EXISTENCE_RESOLVED,),
            source_observation=source_result,
            candidate=candidate,
            existence_record=existence,
        ))

    @staticmethod
    def _identity_scope(record: PhysicalOpeningExistenceRecord) -> tuple[str, str, str, str, str]:
        return (
            record.document_id,
            record.revision_id,
            record.source_sha256,
            record.snapshot_id,
            record.page_id,
        )

    def compare_identity(
        self,
        left_selector: ObservationSelector,
        right_selector: ObservationSelector,
    ) -> PhysicalOpeningIdentityResult:
        """Compare two selectors using independently re-proven G17 existence only."""
        if not isinstance(left_selector, ObservationSelector):
            raise TypeError("left_selector must be ObservationSelector")
        if not isinstance(right_selector, ObservationSelector):
            raise TypeError("right_selector must be ObservationSelector")

        left_existence = self.prove_existence(left_selector)
        right_existence = self.prove_existence(right_selector)
        left_source = left_existence.source_observation
        right_source = right_existence.source_observation

        if (
            left_existence.status is not EvidenceResolutionStatus.CORROBORATED
            or right_existence.status is not EvidenceResolutionStatus.CORROBORATED
            or left_existence.existence_record is None
            or right_existence.existence_record is None
            or left_existence.proposition != PHYSICAL_OPENING_EXISTS
            or right_existence.proposition != PHYSICAL_OPENING_EXISTS
        ):
            status = (
                EvidenceResolutionStatus.CONFLICT
                if (
                    left_existence.status is EvidenceResolutionStatus.CONFLICT
                    or right_existence.status is EvidenceResolutionStatus.CONFLICT
                )
                else EvidenceResolutionStatus.ABSTAINED
            )
            return PhysicalOpeningIdentityResult(
                status=status,
                physical_opening_identity=PHYSICAL_OPENING_IDENTITY_UNRESOLVED,
                proven_same=False,
                reason_codes=_dedupe_reason_codes(
                    (PHYSICAL_OPENING_IDENTITY_EXISTENCE_REQUIRED,),
                    left_existence.reason_codes,
                    right_existence.reason_codes,
                ),
                left_source_observation=left_source,
                right_source_observation=right_source,
                missing_upstream_capability=MISSING_PHYSICAL_OPENING_SEMANTIC_CAPABILITY,
            )

        left_record = left_existence.existence_record
        right_record = right_existence.existence_record
        if self._identity_scope(left_record) != self._identity_scope(right_record):
            return PhysicalOpeningIdentityResult(
                status=EvidenceResolutionStatus.ABSTAINED,
                physical_opening_identity=PHYSICAL_OPENING_IDENTITY_UNRESOLVED,
                proven_same=False,
                reason_codes=(PHYSICAL_OPENING_IDENTITY_SCOPE_MISMATCH,),
                left_source_observation=left_source,
                right_source_observation=right_source,
                missing_upstream_capability=(
                    "independent cross-scope physical opening equivalence authority"
                ),
            )

        if left_record.record_id == right_record.record_id:
            return PhysicalOpeningIdentityResult(
                status=EvidenceResolutionStatus.CORROBORATED,
                physical_opening_identity=left_record.record_id,
                proven_same=True,
                reason_codes=(PHYSICAL_OPENING_IDENTITY_RESOLVED,),
                left_source_observation=left_source,
                right_source_observation=right_source,
            )

        return PhysicalOpeningIdentityResult(
            status=EvidenceResolutionStatus.CORROBORATED,
            physical_opening_identity=PHYSICAL_OPENING_IDENTITIES_DISTINCT,
            proven_same=False,
            reason_codes=(PHYSICAL_OPENING_IDENTITY_RESOLVED,),
            left_source_observation=left_source,
            right_source_observation=right_source,
        )


__all__ = [
    "AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES",
    "AUTHORITATIVE_PHYSICAL_OPENING_IDENTITY_UNAVAILABLE",
    "AUTHORITATIVE_PHYSICAL_OPENING_SEMANTICS_UNAVAILABLE",
    "CandidateSemanticOpening",
    "INSUFFICIENT_INDEPENDENT_SOURCE_LINEAGE",
    "INVALID_STRUCTURAL_GEOMETRY",
    "JAMB_BOUNDED_TWO_FACE_INTERRUPTION",
    "MISSING_PHYSICAL_OPENING_SEMANTIC_CAPABILITY",
    "OPENING_JAMB_BOUNDARY_KIND",
    "PHYSICAL_OPENING_EXISTS",
    "PHYSICAL_OPENING_CANDIDATE_CLOSURE_RESOLVED",
    "PHYSICAL_OPENING_CANDIDATE_CLOSURE_UNRESOLVED",
    "PHYSICAL_OPENING_EXISTENCE_UNRESOLVED",
    "PHYSICAL_OPENING_IDENTITIES_DISTINCT",
    "PHYSICAL_OPENING_IDENTITY_EXISTENCE_REQUIRED",
    "PHYSICAL_OPENING_IDENTITY_RESOLVED",
    "PHYSICAL_OPENING_IDENTITY_SCOPE_MISMATCH",
    "PHYSICAL_OPENING_IDENTITY_UNRESOLVED",
    "PhysicalOpeningAuthority",
    "PhysicalOpeningCandidateClosureResult",
    "PhysicalOpeningCandidateStructureResult",
    "PhysicalOpeningExistenceRecord",
    "PhysicalOpeningExistenceResult",
    "PhysicalOpeningIdentityResult",
    "SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE",
    "STRUCTURAL_OPENING_CANDIDATE",
    "STRUCTURAL_OPENING_EXISTENCE_RESOLVED",
    "VISIBLE_SOURCE_AUTHORITY_REQUIRED",
    "VISIBLE_WALL_CONTINUATION_REQUIRED",
    "WALL_FACE_INTERRUPTION_KIND",
    "WEAK_PHYSICAL_OPENING_CANDIDATE_KINDS",
]
