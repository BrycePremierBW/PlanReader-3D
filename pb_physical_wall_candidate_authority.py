"""Producer-owned source-backed physical-wall candidate authority.

This module proves one narrow proposition only: the physical wall candidates
produced by the existing W2/W3/W4 wall pipeline for a complete exact
producer-owned visible PDF page scope.

Physical equivalence is also producer-owned here. The generic wall-identity
classifier stays fail-closed for independent provenance; this producer may
strengthen otherwise-AMBIGUOUS pair relations only when the already-reviewed
G17 source authority independently re-proves a jamb-bounded two-face opening
from the exact same immutable visible source snapshot and the six proven source
primitives map bijectively back to six W4 wall candidates. No caller-supplied
wall list, equivalence flag, completeness flag, confidence, nearest/first rule,
or geometry body can enter that proof path.

It does NOT prove opening host binding, wall role, wall height, wall thickness,
opening deductions, net wall area, FIRM/commercial publication or JobHub data.
Ordinary callers can address a scope only by lineage; they cannot supply walls,
segments, graphs, candidate lists/counts or completeness flags.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import math
import re
from types import MappingProxyType
from typing import Mapping, Optional, Sequence

import fitz

from pb_migration_contracts import EvidenceResolutionStatus
from pb_pdf_text_integrity_authority import (
    PDF_TEXT_GEOMETRY_TOLERANCE_PT,
    PDF_TEXT_MAJORITY_OVERLAP_RATIO,
)
from pb_native_page_frame import NativePageFrameUnresolved, native_page_frame
from pb_drawing_evidence_binding import DrawingViewType
from pb_physical_opening_authority import (
    JAMB_BOUNDED_TWO_FACE_INTERRUPTION, PHYSICAL_OPENING_EXISTS,
    PhysicalOpeningAuthority, PhysicalOpeningExistenceRecord,
)
from pb_physical_scale_authority import (
    PHYSICAL_SCALE_RESOLVED,
    PhysicalScaleProducer,
    PhysicalScaleSelector,
)
from pb_physical_wall_identity import (
    DuplicateW4CandidateAddress,
    PhysicalEquivalenceClass,
    PhysicalWallEquivalenceResolution,
    PhysicalWallIdentity,
    collect_physical_wall_identities,
    CandidatePairAudit,
    resolve_physical_wall_equivalence,
)
from pb_physical_wall_source_metadata_shadow import (
    PhysicalWallSourceMetadataScopeTable,
    build_physical_wall_source_metadata_scope_table,
    unavailable_physical_wall_source_metadata_scope_table,
)
from pb_source_observation_authority import ObservationSelector
from pb_source_visibility_authority import (
    NATIVE_PDF_VISIBLE_SEGMENT,
    RASTER_PDF_VISIBLE_SEGMENT,
    SourceVisibilityProducer,
    classify_native_segment_visibility,
)
from pb_vector_geometry_v130 import extract_native_page
from pb_viewport_segmentation import (
    ViewportSegmentationStatus,
    is_authoritative_derived_viewport,
    is_segment_page_viewports_product,
    segmented_viewport_producer_fingerprint,
    segment_page_viewports,
    validate_non_overlapping_viewports,
)
from pb_wall_room_topology_contracts import JunctionType, WallCandidate
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_primitive_lineage import LINEAGE_KEY, SNAP_COLLAPSE_REASON
from pb_wall_room_topology_stage_a import (
    DEFAULT_GAP_SNAP_TOLERANCE_PT,
    build_wall_graph_for_viewport,
    is_structural_candidate_segment,
)
from pb_wall_room_topology_wall_assembly import (
    W4SourceCandidateAddressCollision,
    assemble_wall_topology,
)
from pb_wall_room_topology_typed_negative_evidence import (
    collect_source_lineage_grid_evidence,
)


PHYSICAL_WALL_CANDIDATE_AUTHORITY_SCHEMA_VERSION = "1.2.0"
PHYSICAL_WALL_CANDIDATE_SCOPE_RESOLVED = "physical_wall_candidate_scope_resolved"
PHYSICAL_WALL_CANDIDATE_SCOPE_UNAVAILABLE = "physical_wall_candidate_scope_unavailable"
PHYSICAL_WALL_CANDIDATE_SCOPE_COMPLEXITY_EXCEEDED = (
    "physical_wall_candidate_scope_complexity_exceeded"
)
# Exact topology remains fail-closed on pathologically dense CAD scopes. The
# limit is a runtime-safety boundary only: exceeding it never publishes a wall
# or quantity and never changes evidence into a positive claim.
MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS = 20_000

# Dense CAD exports can encode hatch / symbol texture as tens of thousands of
# one-segment drawing paths. Those paths are not allowed to enter exact wall
# topology merely because the source omitted useful layer names. The filter
# below is intentionally source-structural rather than project-specific: it
# requires a singleton drawing path plus a repeated translation-invariant
# stroke signature. Unique short walls and unique diagonal walls therefore
# remain eligible, including green/stroked panel boundaries. Thresholds are
# page-relative for span and deliberately high for orthogonal motifs because
# orthogonal short returns are common legitimate wall geometry.
_REPEATED_MOTIF_ORTHOGONAL_REPEAT_MIN = 8
_REPEATED_MOTIF_NON_ORTHOGONAL_REPEAT_MIN = 4
_REPEATED_MOTIF_MULTI_ANGLE_REPEAT_MIN = 16
_REPEATED_MOTIF_MULTI_ANGLE_COUNT_MIN = 3
_REPEATED_MOTIF_ORTHOGONAL_SPAN_FRACTION = 0.03
_REPEATED_MOTIF_NON_ORTHOGONAL_SPAN_FRACTION = 0.10
_REPEATED_MOTIF_MULTI_ANGLE_SPAN_FRACTION = 0.006
_REPEATED_MOTIF_ORTHOGONAL_TOLERANCE_DEG = 2.0
PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE = (
    "physical_wall_candidate_source_integrity_failure"
)
PHYSICAL_WALL_CANDIDATE_IDENTITY_UNRESOLVED = (
    "physical_wall_candidate_identity_unresolved"
)
PHYSICAL_WALL_CANDIDATE_SCOPE_CROPPED_AT_PAGE_BOUNDARY = (
    "physical_wall_candidate_scope_cropped_at_page_boundary"
)
PHYSICAL_WALL_CANDIDATE_SCOPE_CROPPED_AT_VIEWPORT_BOUNDARY = (
    "physical_wall_candidate_scope_cropped_at_viewport_boundary"
)
PHYSICAL_WALL_CANDIDATE_SCOPE_BOUNDS_UNRESOLVED = (
    "physical_wall_candidate_scope_bounds_unresolved"
)
PHYSICAL_WALL_CANDIDATE_PAGE_FRAME_UNRESOLVED = (
    "physical_wall_candidate_page_frame_unresolved"
)
PHYSICAL_WALL_CANDIDATE_VIEWPORT_AUTHORITY_INVALID = (
    "physical_wall_candidate_viewport_authority_invalid"
)
PHYSICAL_WALL_CANDIDATE_VIEWPORT_LINEAGE_MISMATCH = (
    "physical_wall_candidate_viewport_lineage_mismatch"
)
PHYSICAL_WALL_CANDIDATE_SOURCE_PRIMITIVE_OWNERSHIP_AMBIGUOUS = (
    "physical_wall_candidate_source_primitive_ownership_ambiguous"
)
# Shadow-only boundary evaluation (never read by scope_complete / reason_codes).
PHYSICAL_WALL_CANDIDATE_TOUCHES_EXCLUDED_BOUNDARY_PRIMITIVE = (
    "physical_wall_candidate_touches_excluded_boundary_primitive"
)
PHYSICAL_WALL_CANDIDATE_BOUNDARY_GEOMETRY_NOT_EVALUABLE = (
    "physical_wall_candidate_boundary_geometry_not_evaluable"
)
BOUNDARY_PRIMITIVE_CROSSES_SCOPE_BOUNDARY = "crosses_scope_boundary"
BOUNDARY_PRIMITIVE_LIES_ON_SCOPE_BOUNDARY_PARTIAL = "lies_on_scope_boundary_partial"
BOUNDARY_PRIMITIVE_INSIDE_MULTIPLE_VIEWPORTS = "inside_multiple_viewports"
PHYSICAL_WALL_SCOPE_BOUNDARY_EVALUATION_SCHEMA_VERSION = "1.0.0"
BOUNDARY_EVALUATION_EVALUATED = "evaluated"
BOUNDARY_EVALUATION_UNAVAILABLE = "unavailable"

TRUSTED_EQUIVALENCE_OVERRIDE_UNKNOWN_MEMBER = (
    "trusted_equivalence_override_unknown_member"
)
TRUSTED_EQUIVALENCE_OVERRIDE_UNUSABLE_MEMBER = (
    "trusted_equivalence_override_unusable_member"
)
TRUSTED_EQUIVALENCE_OVERRIDE_CONFLICT = (
    "trusted_equivalence_override_conflicts_with_proven_relation"
)

_PRODUCER_SEAL = object()
_AUTHORITY_SEAL = object()
_VIEWPORT_SELECTOR_SEAL = object()
_COORD_TOL = 1e-6
_PARALLEL_REL_TOL = 1e-9
Point = tuple[float, float]
Line = tuple[float, float, float, float]

# Exact-coincidence tolerance for "this coordinate is the same point as that
# boundary coordinate". This is the same tolerance this module already uses
# everywhere else for point/line exactness (_line, _canonical_direction,
# _trusted_face_break, _same_gap, _segment_matches, etc.) -- not a new
# constant invented for boundary checking. A native PDF coordinate that was
# actually drawn at a page or viewport edge decodes back to that exact
# value (verified: a segment endpoint drawn at x=0.0 on an unrotated,
# unscaled page reads back as exactly 0.0), so no larger, hand-picked
# proximity tolerance is needed or used.
_BOUNDARY_COORD_TOL = _COORD_TOL


@dataclass(frozen=True)
class PhysicalWallCandidateSelector:
    """Consumer address.

    Legacy page-scope selectors remain public for compatibility. Viewport
    selectors are producer-sealed and can only be obtained from an authority
    that already materialized the authenticated viewport scope.
    """

    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    _viewport_selector_fingerprint: str = ""
    _viewport_selector_seal: object = None


@dataclass(frozen=True)
class PhysicalWallSourceEdgeFragment:
    """Producer-owned graph edge facts; consumers must re-prove source support.

    W2 edge coordinates may differ from W4's snapped node path. Merged edge
    coordinates are not necessarily exact source geometry, so retaining them
    is not itself a straightness, wall, frame or measurement proposition.
    """

    edge_id: str
    geometry: Line
    source_primitive_ids: tuple[str, ...]


@dataclass(frozen=True)
class PhysicalWallSnapCollapsedFragment(PhysicalWallSourceEdgeFragment):
    """An exact source-loss negative, not an edge in the surviving graph."""

    reason_code: str = SNAP_COLLAPSE_REASON


@dataclass(frozen=True)
class PhysicalWallCandidateRecord:
    wall_candidate_id: str
    wall_candidate: WallCandidate
    physical_identity: PhysicalWallIdentity
    schema_version: str = PHYSICAL_WALL_CANDIDATE_AUTHORITY_SCHEMA_VERSION
    source_edge_fragments: tuple[PhysicalWallSourceEdgeFragment, ...] = ()
    # Observability only: these source fragments disappeared during W2
    # snapping. They are not surviving graph edges or continuity authority.
    source_snap_collapsed_fragments: tuple[PhysicalWallSnapCollapsedFragment, ...] = ()


@dataclass(frozen=True)
class ExcludedBoundaryPrimitive:
    """A structural source primitive withheld from a viewport scope's wall graph
    because it crosses, or only partially lies on, the scope boundary."""

    category: str
    source_observation_id: str
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class PhysicalWallScopeBoundaryEvaluation:
    """Shadow, per-candidate scope-boundary evaluation.

    This is additive evidence only. It never changes ``scope_complete``,
    ``reason_codes``, records, equivalence, or any consumer decision, and it is
    not wall authority: a boundary-clean candidate is merely one whose source
    geometry is not cut by, or in contact with, anything excluded at the scope
    boundary. ``status == "unavailable"`` means NOTHING may be inferred.

    A candidate is boundary-tainted when (a) the existing per-candidate boundary
    rule flags a dangling end (page/viewport crop or unresolved bounds), or
    (b) its geometry is within ``contact_tolerance_pt`` -- the wall graph's own
    gap-snap tolerance, i.e. it would have connected had the primitive been in
    the graph -- of a structural primitive excluded at the boundary.
    """

    status: str
    reason_code: Optional[str]
    evaluated_wall_candidate_ids: tuple[str, ...]
    boundary_tainted_wall_candidate_ids: tuple[str, ...]
    boundary_taint_reason_codes: tuple[tuple[str, tuple[str, ...]], ...]
    excluded_boundary_primitives: tuple[ExcludedBoundaryPrimitive, ...]
    authenticated_frame_edge_primitive_count: int
    contact_tolerance_pt: float
    schema_version: str = PHYSICAL_WALL_SCOPE_BOUNDARY_EVALUATION_SCHEMA_VERSION

    @property
    def boundary_clean_wall_candidate_count(self) -> int:
        if self.status != BOUNDARY_EVALUATION_EVALUATED:
            return 0
        return len(self.evaluated_wall_candidate_ids) - len(
            self.boundary_tainted_wall_candidate_ids
        )

    def is_boundary_clean(self, wall_candidate_id: str) -> bool:
        """True only for an evaluated, untainted candidate of this scope."""
        if self.status != BOUNDARY_EVALUATION_EVALUATED:
            return False
        key = str(wall_candidate_id)
        return (
            key in self.evaluated_wall_candidate_ids
            and key not in self.boundary_tainted_wall_candidate_ids
        )


@dataclass(frozen=True)
class PhysicalWallCandidateScopeResult:
    status: EvidenceResolutionStatus
    scope_complete: bool
    records: tuple[PhysicalWallCandidateRecord, ...]
    source_observation_ids: tuple[str, ...]
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    reason_codes: tuple[str, ...]
    equivalence: Optional[PhysicalWallEquivalenceResolution] = None
    proposition: Optional[str] = None
    scope_kind: str = "page"
    viewport_id: Optional[str] = None
    viewport_bbox: Optional[tuple[float, float, float, float]] = None
    viewport_view_type: Optional[str] = None
    viewport_status: Optional[str] = None
    viewport_boundary_source: Optional[str] = None
    viewport_producer_fingerprint: Optional[str] = None
    viewport_sibling_set_fingerprint: Optional[str] = None
    scope_boundary_observation_ids: tuple[str, ...] = ()
    ambiguous_source_observation_ids: tuple[str, ...] = ()
    schema_version: str = PHYSICAL_WALL_CANDIDATE_AUTHORITY_SCHEMA_VERSION
    boundary_evaluation: Optional[PhysicalWallScopeBoundaryEvaluation] = None
    source_metadata_table: Optional[PhysicalWallSourceMetadataScopeTable] = None
    # Additive U2 sidecar only. It never changes wall scope status, completeness,
    # equivalence, records, or reason codes. Downstream consumers must apply
    # their own proposition-specific gates before using these CANDIDATE atoms.
    typed_semantic_evidence_atoms: tuple[object, ...] = ()


@dataclass(frozen=True)
class _ScopeKey:
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str


@dataclass(frozen=True)
class _ProvenFilledWallStrip:
    path_index: int
    face_raw_ids: tuple[str, str]
    boundary_raw_ids: tuple[str, ...]
    polygon: tuple[Point, ...]


@dataclass(frozen=True)
class _TrustedFaceBreak:
    first_raw_id: str
    second_raw_id: str
    gap_start: float
    gap_end: float
    start_point: Point
    end_point: Point
    direction: Point


def _decision_scope_id(page_id: str) -> str:
    return f"wall-source:page-{str(page_id)}"


def _viewport_selector_payload_fingerprint(
    *,
    document_id: str,
    revision_id: str,
    source_sha256: str,
    snapshot_id: str,
    page_id: str,
    decision_scope_id: str,
) -> str:
    payload = "|".join(
        (
            PHYSICAL_WALL_CANDIDATE_AUTHORITY_SCHEMA_VERSION,
            str(document_id),
            str(revision_id),
            str(source_sha256),
            str(snapshot_id),
            str(page_id),
            str(decision_scope_id),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _viewport_sibling_set_fingerprint(viewports: Sequence[object]) -> str:
    rows = []
    for viewport in sorted(viewports, key=lambda item: str(getattr(item, "view_id", ""))):
        rows.append(
            f"{getattr(viewport, 'view_id', '')}:"
            f"{segmented_viewport_producer_fingerprint(viewport)}"
        )
    return hashlib.sha256("|".join(rows).encode("utf-8")).hexdigest()


def _viewport_decision_scope_id(
    *,
    published,
    page_id: str,
    viewport,
    sibling_set_fingerprint: str,
) -> str:
    payload = "|".join(
        (
            PHYSICAL_WALL_CANDIDATE_AUTHORITY_SCHEMA_VERSION,
            str(published.revision.document_id),
            str(published.revision.revision_id),
            str(published.revision.source_sha256),
            str(published.snapshot.snapshot_id),
            str(page_id),
            str(viewport.view_id),
            segmented_viewport_producer_fingerprint(viewport),
            str(sibling_set_fingerprint),
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"wall-source:viewport:{page_id}:{viewport.view_id}:{digest}"


def _page_viewports_cache_key(*, published, page_id: str) -> tuple[str, str, str, str, str]:
    return (
        str(published.revision.document_id),
        str(published.revision.revision_id),
        str(published.revision.source_sha256),
        str(published.snapshot.snapshot_id),
        str(page_id),
    )


def _authenticated_viewports_from_rows(
    all_viewports,
) -> Optional[tuple[tuple, tuple]]:
    if all_viewports is None:
        return None
    rows = tuple(all_viewports)
    if any(not is_segment_page_viewports_product(viewport) for viewport in rows):
        return None
    # Preserve F.07's authority distinction exactly:
    # - RESOLVED vector-frame ownership remains independently authoritative;
    # - DERIVED ownership is authoritative only when the complete usable
    #   sibling set is non-overlapping, matching the migration adapter gate.
    sibling_non_overlapping = validate_non_overlapping_viewports(rows)
    eligible = tuple(
        viewport
        for viewport in rows
        if viewport.bounding_box is not None
        and (
            viewport.status == ViewportSegmentationStatus.RESOLVED.value
            or (
                sibling_non_overlapping
                and is_authoritative_derived_viewport(viewport)
            )
        )
    )
    return rows, eligible


def _authenticated_viewports(page: fitz.Page, *, page_number: int) -> Optional[tuple[tuple, tuple]]:
    return _authenticated_viewports_from_rows(
        _all_viewports(page, page_number=page_number)
    )


def _producer_owned_points_per_mm(
    *,
    scale_producer: PhysicalScaleProducer,
    published,
    page_id: str,
    viewport=None,
) -> Optional[float]:
    """Return only corroborated source-native physical scale for this scope.

    Scale is an optional refinement of the candidate gate, never a caller
    input and never identity evidence. If no producer-owned graphic scale
    exists (including DERIVED-only viewports), no absolute point-distance
    exclusion is applied; parallel overlapping candidates remain fail-closed.
    """
    selector = PhysicalScaleSelector(
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        page_id=str(page_id),
        viewport_id=None if viewport is None else str(viewport.view_id),
    )
    result = scale_producer.publish_scope(selector)
    evidence = result.evidence
    if (
        result.status is not EvidenceResolutionStatus.CORROBORATED
        or result.reason_codes != (PHYSICAL_SCALE_RESOLVED,)
        or evidence is None
        or evidence.selector != selector
    ):
        return None
    value = float(evidence.points_per_mm)
    if not math.isfinite(value) or value <= 0.0:
        return None
    return value


def _segment_length(segment: Mapping[str, object]) -> float:
    x1, y1, x2, y2 = _segment_geometry(segment)
    return math.hypot(x2 - x1, y2 - y1)


def _segment_angle_deg(segment: Mapping[str, object]) -> float:
    x1, y1, x2, y2 = _segment_geometry(segment)
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0


def _repeated_motif_signature(segment: Mapping[str, object]) -> tuple[object, ...]:
    return (
        str(segment.get("stroke") or ""),
        round(float(segment.get("width") or 0.0), 2),
        round(_segment_length(segment), 2),
        round(_segment_angle_deg(segment), 1),
    )


def _repeated_motif_style_length(segment: Mapping[str, object]) -> tuple[object, ...]:
    signature = _repeated_motif_signature(segment)
    return signature[:3]


def _is_orthogonal_angle(angle_deg: float) -> bool:
    return min(
        abs(angle_deg),
        abs(angle_deg - 90.0),
        abs(angle_deg - 180.0),
    ) <= _REPEATED_MOTIF_ORTHOGONAL_TOLERANCE_DEG


class WallPageFrameUnresolved(RuntimeError):
    """The source page frame cannot safely bound native wall geometry."""


def native_wall_scope_page_extent(page: fitz.Page) -> tuple[float, float]:
    """Return the producer-owned native page extent used by wall topology."""

    try:
        frame = native_page_frame(page)
    except NativePageFrameUnresolved as exc:
        raise WallPageFrameUnresolved(
            PHYSICAL_WALL_CANDIDATE_PAGE_FRAME_UNRESOLVED
        ) from exc
    return frame.native_width, frame.native_height


def _receipt_geometry_bbox(receipt: object) -> Optional[tuple[float, float, float, float]]:
    geometry = tuple(getattr(receipt, "geometry", ()) or ())
    if len(geometry) < 4:
        return None
    try:
        x0, y0, x1, y1 = (float(geometry[index]) for index in range(4))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        return None
    return (
        min(x0, x1),
        min(y0, y1),
        max(x0, x1),
        max(y0, y1),
    )


def _annotate_producer_owned_annotation_masks(
    segments: Sequence[dict],
    *,
    text_receipts: Sequence[object],
) -> tuple[dict, ...]:
    """Attach positive producer-owned proof to text-backing fill rectangles.

    The proof is source-structural and does not trust decoded text semantics.
    A rectangle is authenticated only when the native PDF paint stream proves
    all of the following:

    - one exact four-edge fill-only, unstroked rectangle source path;
    - a text draw occurs immediately after that rectangle in PDF paint order;
    - the text geometry is fully contained by the rectangle;
    - rectangle area is tightly text-sized rather than a page/object fill.

    Missing any proposition preserves the rectangle unchanged. The downstream
    wall filter therefore still fails closed for ordinary filled rectangles.
    """

    text_boxes_by_sequence: dict[int, list[tuple[float, float, float, float]]] = (
        defaultdict(list)
    )
    for receipt in text_receipts:
        sequence_number = getattr(receipt, "sequence_number", None)
        try:
            sequence_number = int(sequence_number)
        except (TypeError, ValueError):
            continue
        bbox = _receipt_geometry_bbox(receipt)
        if bbox is not None:
            text_boxes_by_sequence[sequence_number].append(bbox)

    rect_groups: dict[tuple[object, object], list[dict]] = defaultdict(list)
    for segment in segments:
        if str(segment.get("kind") or "") != "rect_edge":
            continue
        rect_groups[
            (segment.get("path_index"), segment.get("item_index"))
        ].append(segment)

    proven_ids: set[int] = set()
    for group in rect_groups.values():
        if len(group) != 4:
            continue
        if {segment.get("edge_index") for segment in group} != {0, 1, 2, 3}:
            continue
        if any(bool(segment.get("stroke_present", False)) for segment in group):
            continue
        if not all(bool(segment.get("fill_present", False)) for segment in group):
            continue

        sequence_values = {segment.get("sequence_number") for segment in group}
        if len(sequence_values) != 1:
            continue
        sequence_number = next(iter(sequence_values))
        try:
            sequence_number = int(sequence_number)
        except (TypeError, ValueError):
            continue
        text_boxes = text_boxes_by_sequence.get(sequence_number + 1, ())
        if not text_boxes:
            continue

        xs = [
            float(value)
            for segment in group
            for value in (segment["x1"], segment["x2"])
        ]
        ys = [
            float(value)
            for segment in group
            for value in (segment["y1"], segment["y2"])
        ]
        rect_bbox = (min(xs), min(ys), max(xs), max(ys))
        rx0, ry0, rx1, ry1 = rect_bbox
        rect_width = rx1 - rx0
        rect_height = ry1 - ry0
        if rect_width <= 0.0 or rect_height <= 0.0:
            continue

        tx0 = min(box[0] for box in text_boxes)
        ty0 = min(box[1] for box in text_boxes)
        tx1 = max(box[2] for box in text_boxes)
        ty1 = max(box[3] for box in text_boxes)
        text_width = tx1 - tx0
        text_height = ty1 - ty0
        if text_width <= 0.0 or text_height <= 0.0:
            continue

        tol = PDF_TEXT_GEOMETRY_TOLERANCE_PT
        if (
            tx0 < rx0 - tol
            or ty0 < ry0 - tol
            or tx1 > rx1 + tol
            or ty1 > ry1 + tol
        ):
            continue
        rect_area = rect_width * rect_height
        text_area = text_width * text_height
        if text_area <= 0.0:
            continue
        text_coverage = min(1.0, text_area / rect_area)
        if text_coverage < PDF_TEXT_MAJORITY_OVERLAP_RATIO:
            continue

        proven_ids.update(id(segment) for segment in group)

    annotated: list[dict] = []
    for original in segments:
        segment = dict(original)
        if id(original) in proven_ids:
            segment.update(
                {
                    "annotation_mask_authority": "producer_owned",
                    "annotation_mask_text_sized": True,
                    "annotation_text_overlap": True,
                    "physical_wall_authority": False,
                    "participates_in_source_physical_object": False,
                }
            )
        annotated.append(segment)
    return tuple(annotated)


def _is_proven_annotation_mask_edge(
    segment: Mapping[str, object],
) -> bool:
    """Return True only for producer-authenticated annotation-mask edges.

    Fill-only rectangles are ambiguous by default: they may be wipeouts,
    filled wall bodies, equipment, columns, hatches, or other legitimate
    physical geometry. The wall topology layer therefore cannot infer
    annotation semantics from fill/stroke state alone.

    Positive filtering requires upstream producer-owned proof of all material
    propositions: text-sized geometry, spatial text association, explicit
    absence of physical-wall authority, and non-participation in any larger
    source-owned physical object. Missing proof fails closed by preserving the
    segment.
    """

    return (
        str(segment.get("kind") or "") == "rect_edge"
        and not bool(segment.get("stroke_present", False))
        and bool(segment.get("fill_present", False))
        and str(segment.get("annotation_mask_authority") or "") == "producer_owned"
        and segment.get("annotation_mask_text_sized") is True
        and segment.get("annotation_text_overlap") is True
        and segment.get("physical_wall_authority") is False
        and segment.get("participates_in_source_physical_object") is False
    )

def _filter_repeated_non_physical_drafting_primitives(
    segments: Sequence[dict],
    *,
    page_width: float,
    page_height: float,
    preserved_source_primitive_ids: frozenset[str] = frozenset(),
) -> tuple[dict, ...]:
    """Exclude only source-proven dense singleton drafting motifs.

    A segment is never rejected on length, colour, angle, or repetition alone.
    It must be a one-segment source path and belong to a repeated exact-ish
    source stroke family. Orthogonal families require much stronger repetition
    because legitimate wall returns are commonly orthogonal. Multi-angle motif
    families provide an additional hatch/symbol proof.
    """
    path_counts = Counter(segment.get("path_index") for segment in segments)
    singleton_lines = tuple(
        segment
        for segment in segments
        if str(segment.get("kind") or "") == "line"
        and path_counts.get(segment.get("path_index"), 0) == 1
    )
    singleton_ids = {id(segment) for segment in singleton_lines}

    # Dense CAD pages can contain tens of thousands of singleton primitives.
    # Length, angle and the two motif keys are pure functions of one immutable
    # source segment, so compute them once and reuse them in every census and
    # classification pass. This changes no threshold or filtering decision.
    motif_by_segment_id: dict[
        int, tuple[float, float, tuple[object, ...], tuple[object, ...], float]
    ] = {}
    signature_counts: Counter[tuple[object, ...]] = Counter()
    by_style_length: dict[tuple[object, ...], Counter[float]] = defaultdict(Counter)
    for segment in singleton_lines:
        length = _segment_length(segment)
        angle = _segment_angle_deg(segment)
        signature = (
            str(segment.get("stroke") or ""),
            round(float(segment.get("width") or 0.0), 2),
            round(length, 2),
            round(angle, 1),
        )
        style_length = signature[:3]
        angle_key = float(signature[3])
        motif_by_segment_id[id(segment)] = (
            length,
            angle,
            signature,
            style_length,
            angle_key,
        )
        signature_counts[signature] += 1
        by_style_length[style_length][angle_key] += 1

    multi_angle_styles = {
        style
        for style, angle_counts in by_style_length.items()
        if sum(
            count >= _REPEATED_MOTIF_MULTI_ANGLE_REPEAT_MIN
            for count in angle_counts.values()
        ) >= _REPEATED_MOTIF_MULTI_ANGLE_COUNT_MIN
    }

    page_span = min(float(page_width), float(page_height))
    orthogonal_span = page_span * _REPEATED_MOTIF_ORTHOGONAL_SPAN_FRACTION
    non_orthogonal_span = page_span * _REPEATED_MOTIF_NON_ORTHOGONAL_SPAN_FRACTION
    multi_angle_span = page_span * _REPEATED_MOTIF_MULTI_ANGLE_SPAN_FRACTION

    kept: list[dict] = []
    for segment in segments:
        # A fill-only PDF rectangle is not automatically an annotation wipeout.
        # Filled rectangles can also be legitimate source-owned physical
        # geometry. Prune its synthetic rect_edge linework only when an
        # upstream producer has explicitly authenticated the rectangle as a
        # text-associated annotation mask and proved it does not participate in
        # a physical wall/object. Missing proof preserves the source geometry.
        if _is_proven_annotation_mask_edge(segment):
            continue
        if str(segment.get("id") or "") in preserved_source_primitive_ids:
            # Only six-support source-proven G17 wall face edges are protected;
            # the producer does not infer or certify a complete opening count.
            kept.append(segment)
            continue
        if id(segment) not in singleton_ids:
            kept.append(segment)
            continue
        length, angle, signature, style_length, angle_key = motif_by_segment_id[
            id(segment)
        ]
        repeated = signature_counts[signature]
        multi_angle_member = (
            length <= multi_angle_span
            and style_length in multi_angle_styles
            and by_style_length[style_length][angle_key]
            >= _REPEATED_MOTIF_MULTI_ANGLE_REPEAT_MIN
        )
        if _is_orthogonal_angle(angle):
            decorative = (
                length <= orthogonal_span
                and repeated >= _REPEATED_MOTIF_ORTHOGONAL_REPEAT_MIN
            ) or multi_angle_member
        else:
            decorative = (
                length <= non_orthogonal_span
                and repeated >= _REPEATED_MOTIF_NON_ORTHOGONAL_REPEAT_MIN
            ) or multi_angle_member
        if not decorative:
            kept.append(segment)
    return tuple(kept)

def filtered_wall_topology_source_segment_count(
    segments: Sequence[dict],
    *,
    page_width: float,
    page_height: float,
) -> int:
    """Return the runtime-safety census after generic drafting filtering.

    This is a census only, not positive wall authority. It deliberately uses
    the exact same producer-owned drafting-motif/annotation-mask filter as the
    physical wall authority before the topology safety gate. Final authority
    still rechecks the complete native+raster scope.
    """
    return len(
        _filter_repeated_non_physical_drafting_primitives(
            segments,
            page_width=page_width,
            page_height=page_height,
        )
    )


def _segment_geometry(segment: Mapping[str, object]) -> Line:
    return (
        float(segment["x1"]),
        float(segment["y1"]),
        float(segment["x2"]),
        float(segment["y2"]),
    )


def _segment_fully_inside_bbox(segment: Mapping[str, object], bbox: Sequence[float]) -> bool:
    x1, y1, x2, y2 = _segment_geometry(segment)
    return _inside_rect((x1, y1), x0=float(bbox[0]), y0=float(bbox[1]), x1=float(bbox[2]), y1=float(bbox[3])) and _inside_rect(
        (x2, y2), x0=float(bbox[0]), y0=float(bbox[1]), x1=float(bbox[2]), y1=float(bbox[3])
    )


def _segment_intersects_bbox(segment: Mapping[str, object], bbox: Sequence[float]) -> bool:
    x1, y1, x2, y2 = _segment_geometry(segment)
    xmin, ymin, xmax, ymax = (float(value) for value in bbox)
    if _inside_rect((x1, y1), x0=xmin, y0=ymin, x1=xmax, y1=ymax) or _inside_rect(
        (x2, y2), x0=xmin, y0=ymin, x1=xmax, y1=ymax
    ):
        return True
    dx, dy = x2 - x1, y2 - y1
    lower, upper = 0.0, 1.0
    for p, q in (
        (-dx, x1 - xmin),
        (dx, xmax - x1),
        (-dy, y1 - ymin),
        (dy, ymax - y1),
    ):
        if p == 0.0:
            if q < 0.0:
                return False
            continue
        ratio = q / p
        if p < 0.0:
            if ratio > upper:
                return False
            lower = max(lower, ratio)
        else:
            if ratio < lower:
                return False
            upper = min(upper, ratio)
    return lower <= upper


def _segment_lies_on_bbox_edge(segment: Mapping[str, object], bbox: Sequence[float]) -> bool:
    x1, y1, x2, y2 = _segment_geometry(segment)
    xmin, ymin, xmax, ymax = (float(value) for value in bbox)
    return (
        (abs(x1 - xmin) <= _BOUNDARY_COORD_TOL and abs(x2 - xmin) <= _BOUNDARY_COORD_TOL)
        or (abs(x1 - xmax) <= _BOUNDARY_COORD_TOL and abs(x2 - xmax) <= _BOUNDARY_COORD_TOL)
        or (abs(y1 - ymin) <= _BOUNDARY_COORD_TOL and abs(y2 - ymin) <= _BOUNDARY_COORD_TOL)
        or (abs(y1 - ymax) <= _BOUNDARY_COORD_TOL and abs(y2 - ymax) <= _BOUNDARY_COORD_TOL)
    )


def _segment_is_authenticated_vector_frame_edge(
    segment: Mapping[str, object],
    *,
    viewport,
) -> bool:
    """Recognize only a whole edge of F.07's authenticated vector frame.

    This is not a semantic wall exclusion. It is the exact producer-owned
    boundary primitive already used to establish the RESOLVED viewport. A
    partial line merely lying on that boundary remains ambiguous.
    """
    if (
        viewport.bounding_box is None
        or viewport.status != ViewportSegmentationStatus.RESOLVED.value
        or str(viewport.boundary_source) != "vector_frame"
    ):
        return False
    x1, y1, x2, y2 = _segment_geometry(segment)
    xmin, ymin, xmax, ymax = (float(value) for value in viewport.bounding_box)

    def same_point(left: Point, right: Point) -> bool:
        return (
            abs(left[0] - right[0]) <= _BOUNDARY_COORD_TOL
            and abs(left[1] - right[1]) <= _BOUNDARY_COORD_TOL
        )

    segment_ends = ((x1, y1), (x2, y2))
    frame_edges = (
        ((xmin, ymin), (xmax, ymin)),
        ((xmax, ymin), (xmax, ymax)),
        ((xmax, ymax), (xmin, ymax)),
        ((xmin, ymax), (xmin, ymin)),
    )
    return any(
        (
            same_point(segment_ends[0], edge[0])
            and same_point(segment_ends[1], edge[1])
        )
        or (
            same_point(segment_ends[0], edge[1])
            and same_point(segment_ends[1], edge[0])
        )
        for edge in frame_edges
    )


def _blocked(selector: PhysicalWallCandidateSelector, reason: str) -> PhysicalWallCandidateScopeResult:
    return PhysicalWallCandidateScopeResult(
        status=EvidenceResolutionStatus.ABSTAINED,
        scope_complete=False,
        records=(),
        source_observation_ids=(),
        document_id=str(selector.document_id),
        revision_id=str(selector.revision_id),
        source_sha256=str(selector.source_sha256),
        snapshot_id=str(selector.snapshot_id),
        page_id=str(selector.page_id),
        decision_scope_id=str(selector.decision_scope_id),
        reason_codes=(reason,),
    )


def _visible_observations_by_page(
    *,
    source_producer: SourceVisibilityProducer,
    published,
) -> dict[str, tuple[tuple[str, object], ...]]:
    """Resolve immutable visible observations once and index exact page ownership.

    Every visible observation is still authenticated through the existing source
    visibility authority. This only avoids repeating the same authentication for
    every requested wall page.
    """
    visibility = source_producer.authority()
    by_page: dict[str, list[tuple[str, object]]] = {}
    try:
        resolved_visible = visibility.authenticated_visible_observations(published)
    except RuntimeError as exc:
        raise RuntimeError(
            PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE
        ) from exc
    for observation_id, observation in resolved_visible:
        by_page.setdefault(str(observation.page_id), []).append(
            (observation_id, observation)
        )
    return {
        page_id: tuple(rows)
        for page_id, rows in by_page.items()
    }


def _text_receipts_by_page(
    *,
    source_producer: SourceVisibilityProducer,
    published,
) -> dict[str, tuple[object, ...]]:
    """Resolve producer-owned text receipts once and index exact page ownership.

    Receipt geometry and paint sequence are usable here even when decoded text
    semantics fail integrity checks: annotation-mask proof depends only on
    source paint structure, never on the text content.
    """

    authority = source_producer.text_integrity_authority()
    by_page: dict[str, list[object]] = {}
    for observation_id in published.text_observation_ids:
        result = authority.resolve_text(
            ObservationSelector(
                document_id=published.revision.document_id,
                revision_id=published.revision.revision_id,
                source_sha256=published.revision.source_sha256,
                snapshot_id=published.snapshot.snapshot_id,
                observation_id=observation_id,
            )
        )
        receipt = result.receipt
        if receipt is None:
            continue
        by_page.setdefault(str(receipt.page_id), []).append(receipt)
    return {
        page_id: tuple(rows)
        for page_id, rows in by_page.items()
    }


def _source_page_segments(
    *,
    source_producer: SourceVisibilityProducer,
    published,
    source_bytes: bytes,
    page_id: str,
    decision_scope_id: str,
    resolved_visible_observations: Optional[Sequence[tuple[str, object]]] = None,
    resolved_text_receipts: Optional[Sequence[object]] = None,
) -> tuple[list[dict], tuple[str, ...], float, float]:
    """Rebuild W2 inputs from exact bytes and exact receipted visible membership.

    Also returns the page's own (width, height) in points, so callers can
    determine whether a wall's dangling end actually terminates inside the
    drawing (a real wall end) or merely at the page edge (the wall's true
    continuation is unknown -- it may simply be cropped by this sheet).
    """

    observation_cache_key = (
        None
        if resolved_visible_observations is None
        else tuple(str(row[0]) for row in resolved_visible_observations)
    )
    page_cache_key = (
        str(published.revision.document_id),
        str(published.revision.revision_id),
        str(published.revision.source_sha256),
        str(published.snapshot.snapshot_id),
        str(page_id),
        str(decision_scope_id),
        observation_cache_key,
    )
    page_cache = source_producer._physical_wall_page_segments_cache
    cached_page = page_cache.get(page_cache_key)
    if cached_page is not None:
        cached_segments, cached_observation_ids, cached_width, cached_height = cached_page
        return (
            [dict(segment) for segment in cached_segments],
            cached_observation_ids,
            cached_width,
            cached_height,
        )

    visibility = source_producer.authority()
    native_visible_by_raw_id: dict[str, tuple[str, tuple[float, ...]]] = {}
    raster_visible: list[tuple[str, str, tuple[float, ...]]] = []
    page_visible_ids: list[str] = []

    if resolved_visible_observations is None:
        page_rows: list[tuple[str, object]] = []
        for observation_id in published.visible_observation_ids:
            result = visibility.resolve_visible(
                ObservationSelector(
                    document_id=published.revision.document_id,
                    revision_id=published.revision.revision_id,
                    source_sha256=published.revision.source_sha256,
                    snapshot_id=published.snapshot.snapshot_id,
                    observation_id=observation_id,
                )
            )
            observation = result.observation
            if (
                result.status is not EvidenceResolutionStatus.CORROBORATED
                or observation is None
            ):
                raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
            if observation.page_id == page_id:
                page_rows.append((observation_id, observation))
    else:
        page_rows = list(resolved_visible_observations)

    for observation_id, observation in page_rows:
        if str(observation.page_id) != str(page_id):
            raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)

        geometry = tuple(float(value) for value in observation.geometry)
        if len(geometry) != 4:
            raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)

        if observation.observation_kind == NATIVE_PDF_VISIBLE_SEGMENT:
            prefix = "visible:segment:"
            if not observation.source_primitive_ref.startswith(prefix):
                raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
            raw_id = observation.source_primitive_ref[len(prefix) :]
            if not raw_id or raw_id in native_visible_by_raw_id:
                raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
            native_visible_by_raw_id[raw_id] = (observation_id, geometry)
        elif observation.observation_kind == RASTER_PDF_VISIBLE_SEGMENT:
            prefix = "visible:raster_segment:"
            if not observation.source_primitive_ref.startswith(prefix):
                raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
            raster_ref = observation.source_primitive_ref[len("visible:") :]
            if not raster_ref:
                raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
            raster_visible.append((observation_id, raster_ref, geometry))
        else:
            raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)

        page_visible_ids.append(observation_id)

    try:
        page_number = int(page_id)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE) from exc
    if page_number < 1:
        raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)

    cached_native = source_producer._producer._cached_native_page(
        published.revision.source_sha256, page_number
    )
    native = (
        None
        if cached_native is None or cached_native.failed
        else cached_native.native_page
    )
    pdf = fitz.open(stream=source_bytes, filetype="pdf")
    try:
        if page_number > int(pdf.page_count):
            raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
        page = pdf.load_page(page_number - 1)
        # Native ingest already decoded this exact immutable page. Reuse the
        # producer-owned parse so wall reconstruction does not rebuild the same
        # drawings and words. Page-frame authority still reads /Rotate from the
        # exact PDF page because that metadata is not part of the native decode.
        if native is None:
            native = extract_native_page(page)
        page_width, page_height = native_wall_scope_page_extent(page)
    finally:
        pdf.close()

    segments: list[dict] = []
    native_visible_ids: set[str] = set()
    for source_segment in native.get("segments") or ():
        decision = classify_native_segment_visibility(source_segment)
        if not decision.visible:
            continue
        raw_id = str(source_segment.get("id") or "").strip()
        if not raw_id:
            raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
        expected = native_visible_by_raw_id.get(raw_id)
        if expected is None:
            raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
        observation_id, observation_geometry = expected
        geometry = (
            float(source_segment["x1"]),
            float(source_segment["y1"]),
            float(source_segment["x2"]),
            float(source_segment["y2"]),
        )
        if tuple(geometry) != tuple(observation_geometry):
            raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
        native_visible_ids.add(observation_id)
        segment = dict(source_segment)
        segment["document_id"] = published.revision.document_id
        segment["page_id"] = page_id
        segment["viewport_id"] = decision_scope_id
        segment["source_observation_id"] = observation_id
        segments.append(segment)

    if native_visible_ids != {
        observation_id
        for observation_id, _geometry in native_visible_by_raw_id.values()
    }:
        raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)

    text_receipts = (
        tuple(resolved_text_receipts)
        if resolved_text_receipts is not None
        else _text_receipts_by_page(
            source_producer=source_producer,
            published=published,
        ).get(str(page_id), ())
    )
    segments = list(
        _annotate_producer_owned_annotation_masks(
            segments,
            text_receipts=text_receipts,
        )
    )

    # Raster-visible observations have already passed the producer-owned
    # visibility authority, including page-render provenance, image hash, DPI,
    # pixel geometry and parent-lineage checks.  Feed their exact page-point
    # geometry into the same W2-W5 topology pipeline as native segments while
    # leaving graphic attributes explicitly unknown.  No caller-supplied
    # pixels, segments, transforms or wall classifications enter this path.
    for observation_id, raster_ref, geometry in sorted(raster_visible):
        x1, y1, x2, y2 = geometry
        segments.append(
            {
                "id": raster_ref,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "kind": "line",
                "kind_present": True,
                "width": 0.0,
                "width_present": False,
                "stroke": None,
                "stroke_present": False,
                "fill": None,
                "fill_present": False,
                "layer": "",
                "layer_present": False,
                "dashes": "",
                "dashes_present": False,
                "clip": None,
                "clip_present": False,
                "clip_known": True,
                "document_id": published.revision.document_id,
                "page_id": page_id,
                "viewport_id": decision_scope_id,
                "source_observation_id": observation_id,
                "source_kind": RASTER_PDF_VISIBLE_SEGMENT,
            }
        )

    if native_visible_ids | {item[0] for item in raster_visible} != set(page_visible_ids):
        raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)

    source_observation_ids = tuple(sorted(page_visible_ids))
    page_cache[page_cache_key] = (
        tuple(dict(segment) for segment in segments),
        source_observation_ids,
        page_width,
        page_height,
    )
    return (
        segments,
        source_observation_ids,
        page_width,
        page_height,
    )


def _dangling_ends(wall: WallCandidate) -> list[Point]:
    """Return the coordinates of this wall's ends that are genuinely
    dangling (``JunctionType.ENDPOINT`` -- not connected to any other wall).

    An end that meets another wall (any other junction type) is a real,
    resolved terminus regardless of where it happens to sit; it is never a
    candidate for "cropped" classification.
    """
    if not wall.centerline_pts or len(wall.centerline_pts) < 2:
        return []
    if len(wall.junction_types) != 2:
        return []
    ends = (
        (wall.centerline_pts[0], wall.junction_types[0]),
        (wall.centerline_pts[-1], wall.junction_types[1]),
    )
    return [point for point, junction_type in ends if junction_type == JunctionType.ENDPOINT]


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(
        point[0] - (start[0] + t * dx), point[1] - (start[1] + t * dy)
    )


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orient(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p: Point, q: Point, r: Point) -> bool:
        return (
            min(p[0], r[0]) <= q[0] <= max(p[0], r[0])
            and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])
        )

    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    if (
        0.0 not in (o1, o2, o3, o4)
        and ((o1 > 0.0) != (o2 > 0.0))
        and ((o3 > 0.0) != (o4 > 0.0))
    ):
        return True
    return (
        (o1 == 0.0 and on_segment(a, c, b))
        or (o2 == 0.0 and on_segment(a, d, b))
        or (o3 == 0.0 and on_segment(c, a, d))
        or (o4 == 0.0 and on_segment(c, b, d))
    )


def _segment_segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    """Minimum distance between two segments; total (never raises).

    Non-finite input is reported as distance 0.0 so that an unprovable contact is
    treated conservatively as contact.
    """
    if not all(math.isfinite(v) for pt in (a, b, c, d) for v in pt):
        return 0.0
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _boundary_excluded_primitive(
    segment: Mapping[str, object], category: str
) -> ExcludedBoundaryPrimitive:
    x1, y1, x2, y2 = _segment_geometry(segment)
    return ExcludedBoundaryPrimitive(
        category=category,
        source_observation_id=str(segment.get("source_observation_id") or ""),
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
    )


def _evaluate_scope_boundary(
    *,
    ordered_walls: Sequence[WallCandidate],
    wall_boundary_reasons: Mapping[str, str],
    excluded_boundary_primitives: Sequence[ExcludedBoundaryPrimitive],
    authenticated_frame_edge_primitive_count: int,
    contact_tolerance_pt: float = DEFAULT_GAP_SNAP_TOLERANCE_PT,
) -> PhysicalWallScopeBoundaryEvaluation:
    """Classify each wall candidate of one scope as boundary-clean or tainted.

    Pure and deterministic. Does not read or alter scope completeness.
    """
    primitives = tuple(
        sorted(
            excluded_boundary_primitives,
            key=lambda row: (
                row.category,
                row.x1,
                row.y1,
                row.x2,
                row.y2,
                row.source_observation_id,
            ),
        )
    )
    evaluated = tuple(sorted(str(wall.candidate_id) for wall in ordered_walls))
    taint: dict[str, tuple[str, ...]] = {}
    for wall in ordered_walls:
        wall_id = str(wall.candidate_id)
        reasons: list[str] = []
        existing = wall_boundary_reasons.get(wall_id)
        if existing:
            reasons.append(existing)
        if primitives:
            if wall.representation != "single_line":
                # Source geometry of a paired/curved candidate is not its
                # centerline; contact cannot be proven absent -> tainted.
                reasons.append(
                    PHYSICAL_WALL_CANDIDATE_BOUNDARY_GEOMETRY_NOT_EVALUABLE
                )
            else:
                points = tuple(wall.centerline_pts)
                touched = False
                for start, end in zip(points, points[1:]):
                    first = (float(start[0]), float(start[1]))
                    second = (float(end[0]), float(end[1]))
                    for primitive in primitives:
                        if (
                            _segment_segment_distance(
                                first,
                                second,
                                (primitive.x1, primitive.y1),
                                (primitive.x2, primitive.y2),
                            )
                            <= contact_tolerance_pt
                        ):
                            touched = True
                            break
                    if touched:
                        break
                if touched:
                    reasons.append(
                        PHYSICAL_WALL_CANDIDATE_TOUCHES_EXCLUDED_BOUNDARY_PRIMITIVE
                    )
        if reasons:
            taint[wall_id] = tuple(dict.fromkeys(reasons))
    return PhysicalWallScopeBoundaryEvaluation(
        status=BOUNDARY_EVALUATION_EVALUATED,
        reason_code=None,
        evaluated_wall_candidate_ids=evaluated,
        boundary_tainted_wall_candidate_ids=tuple(sorted(taint)),
        boundary_taint_reason_codes=tuple(sorted(taint.items())),
        excluded_boundary_primitives=primitives,
        authenticated_frame_edge_primitive_count=int(
            authenticated_frame_edge_primitive_count
        ),
        contact_tolerance_pt=float(contact_tolerance_pt),
    )


def _on_rect_boundary(
    point: Point, *, x0: float, y0: float, x1: float, y1: float, tol: float = _BOUNDARY_COORD_TOL
) -> bool:
    x, y = point
    return (
        abs(x - x0) <= tol
        or abs(x - x1) <= tol
        or abs(y - y0) <= tol
        or abs(y - y1) <= tol
    )


def _inside_rect(
    point: Point, *, x0: float, y0: float, x1: float, y1: float, tol: float = _BOUNDARY_COORD_TOL
) -> bool:
    x, y = point
    return (x0 - tol) <= x <= (x1 + tol) and (y0 - tol) <= y <= (y1 + tol)


def _resolved_viewports(page: fitz.Page, *, page_number: int) -> Optional[list]:
    """Return this page's RESOLVED-status segmented viewports, or ``None``
    if segmentation itself could not be run at all (a hard failure, not
    "no viewport structure exists").

    Only ``RESOLVED`` viewports (a real drawn vector frame) are treated as
    an authenticated boundary. ``DERIVED`` viewports are page-space
    partitions inferred from title placement alone with no real drawn
    boundary primitive -- exactly the case already established elsewhere in
    this codebase as insufficient proof of a physical boundary -- and
    ``AMBIGUOUS``/``UNSUPPORTED`` viewports carry no usable geometry at all.
    """
    all_viewports = _all_viewports(page, page_number=page_number)
    if all_viewports is None:
        return None
    return [v for v in all_viewports if v.status == ViewportSegmentationStatus.RESOLVED.value and v.bounding_box]


def _all_viewports(page: fitz.Page, *, page_number: int) -> Optional[list]:
    """Return every segmented viewport regardless of status, or ``None`` if
    segmentation itself raised. An empty list here means genuinely no
    sub-viewport structure was attempted (no title anchors at all) -- a
    non-empty list with no RESOLVED entries means structure was attempted
    but could not be authenticated, which is a different, stricter state.
    """
    try:
        return segment_page_viewports(page, page_number=page_number)
    except Exception:
        return None


def _wall_scope_relevant_viewports(all_viewports):
    """Return only viewport structure that can bound physical wall topology.

    Legends, schedules, and specifications are non-spatial reference regions.
    Their frames may own reference content, but they cannot define or crop a
    physical wall decision scope merely because they have an authenticated
    bounding box. Physical drawing types and unknown bounded/derived regions
    remain conservative and fail-closed.
    """

    non_spatial_types = {
        DrawingViewType.LEGEND.value,
        DrawingViewType.SCHEDULE.value,
        DrawingViewType.SPECIFICATION.value,
    }
    return [
        viewport
        for viewport in all_viewports
        if str(getattr(viewport, "view_type", "") or "")
        not in non_spatial_types
    ]


def _scope_boundary_reason_from_viewports(
    wall: WallCandidate,
    *,
    all_viewports,
    page_width: float,
    page_height: float,
) -> Optional[str]:
    dangling = _dangling_ends(wall)
    if not dangling:
        return None

    for point in dangling:
        if _on_rect_boundary(point, x0=0.0, y0=0.0, x1=page_width, y1=page_height):
            return PHYSICAL_WALL_CANDIDATE_SCOPE_CROPPED_AT_PAGE_BOUNDARY

        if all_viewports is None:
            # Viewport segmentation itself failed outright: whether this
            # sheet has real sub-viewport structure this end might be
            # cropped against is genuinely unknown.
            return PHYSICAL_WALL_CANDIDATE_SCOPE_BOUNDS_UNRESOLVED

        relevant_viewports = _wall_scope_relevant_viewports(all_viewports)
        if not relevant_viewports:
            # No physical/spatial viewport structure is present. Unbounded
            # legend/schedule/specification titles are reference content, not
            # evidence that a physical wall scope may be cropped elsewhere on
            # the sheet. The page boundary remains the applicable scope.
            continue

        resolved_viewports = [
            v
            for v in relevant_viewports
            if v.status == ViewportSegmentationStatus.RESOLVED.value
            and v.bounding_box
        ]

        containing = [
            vp
            for vp in resolved_viewports
            if _inside_rect(point, x0=vp.bounding_box[0], y0=vp.bounding_box[1], x1=vp.bounding_box[2], y1=vp.bounding_box[3])
        ]
        if not containing:
            # This page has authenticated viewport structure, but this
            # dangling end falls outside every RESOLVED viewport's bounds
            # (e.g. only DERIVED/AMBIGUOUS regions cover it) -- its true
            # scope cannot be authenticated from this page alone.
            return PHYSICAL_WALL_CANDIDATE_SCOPE_BOUNDS_UNRESOLVED
        if any(
            _on_rect_boundary(point, x0=vp.bounding_box[0], y0=vp.bounding_box[1], x1=vp.bounding_box[2], y1=vp.bounding_box[3])
            for vp in containing
        ):
            return PHYSICAL_WALL_CANDIDATE_SCOPE_CROPPED_AT_VIEWPORT_BOUNDARY

    return None


def _scope_boundary_reason(
    wall: WallCandidate,
    *,
    page: fitz.Page,
    page_number: int,
    page_width: float,
    page_height: float,
) -> Optional[str]:
    """Classify this wall's scope-completeness boundary state.

    Returns ``None`` when every dangling end is a RESOLVED_INTERIOR_TERMINUS
    (either no dangling end exists at all, or every dangling end sits
    strictly inside both the page and any containing RESOLVED viewport).
    Otherwise returns the specific reason code for the first problem found:
    PAGE boundary, VIEWPORT boundary, or unresolved scope bounds.

    This compatibility wrapper performs segmentation once for a standalone
    call. Page-scope assembly precomputes the same immutable segmentation result
    once and reuses it across all wall candidates.
    """
    return _scope_boundary_reason_from_viewports(
        wall,
        all_viewports=_all_viewports(page, page_number=page_number),
        page_width=page_width,
        page_height=page_height,
    )


def _viewport_scope_boundary_reason(
    wall: WallCandidate,
    *,
    bbox: Sequence[float],
    page_width: float,
    page_height: float,
) -> Optional[str]:
    dangling = _dangling_ends(wall)
    for point in dangling:
        if _on_rect_boundary(
            point,
            x0=0.0,
            y0=0.0,
            x1=page_width,
            y1=page_height,
        ):
            return PHYSICAL_WALL_CANDIDATE_SCOPE_CROPPED_AT_PAGE_BOUNDARY
        if _on_rect_boundary(
            point,
            x0=float(bbox[0]),
            y0=float(bbox[1]),
            x1=float(bbox[2]),
            y1=float(bbox[3]),
        ):
            return PHYSICAL_WALL_CANDIDATE_SCOPE_CROPPED_AT_VIEWPORT_BOUNDARY
    return None


def _line(values: Sequence[float]) -> Optional[Line]:
    if len(values) != 4:
        return None
    try:
        line = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in line):
        return None
    if math.hypot(line[2] - line[0], line[3] - line[1]) <= _COORD_TOL:
        return None
    return line  # type: ignore[return-value]


def _canonical_direction(line: Line) -> Point:
    dx, dy = line[2] - line[0], line[3] - line[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    if ux < -_COORD_TOL or (abs(ux) <= _COORD_TOL and uy < 0.0):
        ux, uy = -ux, -uy
    return (ux, uy)


def _projection(point: Point, direction: Point) -> float:
    return point[0] * direction[0] + point[1] * direction[1]


def _cross(left: Point, right: Point) -> float:
    return left[0] * right[1] - left[1] * right[0]


def _parallel(left: Line, right: Line) -> bool:
    ldx, ldy = left[2] - left[0], left[3] - left[1]
    rdx, rdy = right[2] - right[0], right[3] - right[1]
    llen = math.hypot(ldx, ldy)
    rlen = math.hypot(rdx, rdy)
    return abs(ldx * rdy - ldy * rdx) <= _PARALLEL_REL_TOL * llen * rlen


def _collinear(left: Line, right: Line) -> bool:
    if not _parallel(left, right):
        return False
    direction = _canonical_direction(left)
    return abs(
        _cross(direction, (right[0] - left[0], right[1] - left[1]))
    ) <= _COORD_TOL


def _endpoint_at_projection(line: Line, direction: Point, target: float) -> Optional[Point]:
    for point in ((line[0], line[1]), (line[2], line[3])):
        if abs(_projection(point, direction) - target) <= _COORD_TOL:
            return point
    return None


def _trusted_face_break(
    first_raw_id: str,
    first_line: Line,
    second_raw_id: str,
    second_line: Line,
) -> Optional[_TrustedFaceBreak]:
    if not _collinear(first_line, second_line):
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
        left_id, left_line, left_values = first_raw_id, first_line, first_values
        right_id, right_line, right_values = second_raw_id, second_line, second_values
    else:
        left_id, left_line, left_values = second_raw_id, second_line, second_values
        right_id, right_line, right_values = first_raw_id, first_line, first_values
    gap_start, gap_end = left_values[1], right_values[0]
    if gap_end - gap_start <= _COORD_TOL:
        return None
    start_point = _endpoint_at_projection(left_line, direction, gap_start)
    end_point = _endpoint_at_projection(right_line, direction, gap_end)
    if start_point is None or end_point is None:
        return None
    return _TrustedFaceBreak(
        first_raw_id=left_id,
        second_raw_id=right_id,
        gap_start=gap_start,
        gap_end=gap_end,
        start_point=start_point,
        end_point=end_point,
        direction=direction,
    )


def _same_gap(left: _TrustedFaceBreak, right: _TrustedFaceBreak) -> bool:
    if abs(left.gap_start - right.gap_start) > _COORD_TOL:
        return False
    if abs(left.gap_end - right.gap_end) > _COORD_TOL:
        return False
    dot = left.direction[0] * right.direction[0] + left.direction[1] * right.direction[1]
    return abs(abs(dot) - 1.0) <= _PARALLEL_REL_TOL


def _distinct_parallel_axes(left: _TrustedFaceBreak, right: _TrustedFaceBreak) -> bool:
    delta = (
        right.start_point[0] - left.start_point[0],
        right.start_point[1] - left.start_point[1],
    )
    return abs(_cross(left.direction, delta)) > _COORD_TOL


def _segment_matches(line: Line, first: Point, second: Point) -> bool:
    start = (line[0], line[1])
    end = (line[2], line[3])
    direct = (
        abs(start[0] - first[0]) <= _COORD_TOL
        and abs(start[1] - first[1]) <= _COORD_TOL
        and abs(end[0] - second[0]) <= _COORD_TOL
        and abs(end[1] - second[1]) <= _COORD_TOL
    )
    reverse = (
        abs(start[0] - second[0]) <= _COORD_TOL
        and abs(start[1] - second[1]) <= _COORD_TOL
        and abs(end[0] - first[0]) <= _COORD_TOL
        and abs(end[1] - first[1]) <= _COORD_TOL
    )
    return direct or reverse



def _line_length(line: Line) -> float:
    return math.hypot(line[2] - line[0], line[3] - line[1])


def _same_point(left: Point, right: Point) -> bool:
    return (
        abs(left[0] - right[0]) <= _COORD_TOL
        and abs(left[1] - right[1]) <= _COORD_TOL
    )


def _closed_four_edge_cycle(
    entries: Sequence[tuple[str, Line]],
) -> Optional[tuple[tuple[str, ...], tuple[Point, ...]]]:
    if len(entries) != 4:
        return None
    adjacency: dict[Point, list[tuple[str, Point]]] = {}
    canonical_points: list[Point] = []

    def canonical(point: Point) -> Point:
        for existing in canonical_points:
            if _same_point(existing, point):
                return existing
        canonical_points.append(point)
        return point

    for raw_id, line in entries:
        start = canonical((line[0], line[1]))
        end = canonical((line[2], line[3]))
        if _same_point(start, end):
            return None
        adjacency.setdefault(start, []).append((raw_id, end))
        adjacency.setdefault(end, []).append((raw_id, start))
    if len(adjacency) != 4 or any(len(items) != 2 for items in adjacency.values()):
        return None

    first = min(adjacency)
    ordered_ids: list[str] = []
    ordered_points: list[Point] = [first]
    current = first
    previous_id: Optional[str] = None
    for _ in range(4):
        options = sorted(
            (item for item in adjacency[current] if item[0] != previous_id),
            key=lambda item: item[0],
        )
        if not options:
            return None
        raw_id, nxt = options[0]
        if raw_id in ordered_ids:
            if len(ordered_ids) == 3 and _same_point(nxt, first):
                ordered_ids.append(raw_id)
                ordered_points.append(first)
                break
            return None
        ordered_ids.append(raw_id)
        ordered_points.append(nxt)
        previous_id = raw_id
        current = nxt
    if len(ordered_ids) != 4 or not _same_point(ordered_points[-1], first):
        return None
    if len(set(ordered_ids)) != 4:
        return None
    return tuple(ordered_ids), tuple(ordered_points[:-1])


def _proven_filled_wall_strips(
    segments: Sequence[Mapping[str, object]],
) -> tuple[_ProvenFilledWallStrip, ...]:
    """Prove wall strips from one immutable native filled drawing path.

    This is intentionally stronger than parallel-line pairing. A strip exists
    only when one source drawing path supplies exactly four line primitives,
    every primitive carries the same explicit structural/bearing layer and
    explicit fill, the primitives form one closed cycle, and exactly two
    opposite sides are dominant parallel faces. No proximity, nearest/first
    candidate, confidence score, text, OCR, or benchmark identity is used.
    """
    by_path: dict[int, list[Mapping[str, object]]] = {}
    for segment in segments:
        path_index = segment.get("path_index")
        raw_id = str(segment.get("id") or "")
        if path_index is None or not raw_id or str(segment.get("kind") or "") != "line":
            continue
        try:
            path_key = int(path_index)
        except (TypeError, ValueError):
            continue
        by_path.setdefault(path_key, []).append(segment)

    strips: list[_ProvenFilledWallStrip] = []
    for path_index, members in sorted(by_path.items()):
        if len(members) != 4:
            continue
        layers = {
            str(member.get("layer") or "").strip().lower()
            for member in members
            if bool(member.get("layer_present", str(member.get("layer") or "").strip()))
        }
        if len(layers) != 1:
            continue
        layer = next(iter(layers), "")
        if "structural" not in layer or not any(token in layer for token in ("bearing", "wall")):
            continue
        if not all(
            bool(member.get("fill_present", member.get("fill") is not None))
            and member.get("fill") is not None
            for member in members
        ):
            continue

        entries = [
            (str(member["id"]), _segment_geometry(member))
            for member in members
        ]
        cycle = _closed_four_edge_cycle(entries)
        if cycle is None:
            continue
        ordered_ids, polygon = cycle
        line_by_id = {raw_id: line for raw_id, line in entries}
        lengths = {raw_id: _line_length(line_by_id[raw_id]) for raw_id in ordered_ids}
        ranked = sorted(ordered_ids, key=lambda raw_id: (-lengths[raw_id], raw_id))
        face_ids = tuple(sorted(ranked[:2]))
        connector_ids = tuple(ranked[2:])
        if not _parallel(line_by_id[face_ids[0]], line_by_id[face_ids[1]]):
            continue
        if _collinear(line_by_id[face_ids[0]], line_by_id[face_ids[1]]):
            continue
        if min(lengths[raw_id] for raw_id in face_ids) <= (
            3.0 * max(lengths[raw_id] for raw_id in connector_ids)
        ):
            continue
        # The dominant sides must be opposite in the source cycle, not adjacent.
        positions = sorted(ordered_ids.index(raw_id) for raw_id in face_ids)
        if (positions[1] - positions[0]) != 2:
            continue
        strips.append(
            _ProvenFilledWallStrip(
                path_index=path_index,
                face_raw_ids=face_ids,
                boundary_raw_ids=tuple(sorted(ordered_ids)),
                polygon=polygon,
            )
        )
    return tuple(strips)


def _point_in_convex_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    if len(polygon) < 3:
        return False
    signs: list[int] = []
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        value = _cross(
            (second[0] - first[0], second[1] - first[1]),
            (point[0] - first[0], point[1] - first[1]),
        )
        if abs(value) <= _COORD_TOL:
            continue
        signs.append(1 if value > 0.0 else -1)
    return not signs or all(sign == signs[0] for sign in signs)


def _segment_contained_by_strip(
    segment: Mapping[str, object],
    strip: _ProvenFilledWallStrip,
) -> bool:
    line = _segment_geometry(segment)
    return _point_in_convex_polygon((line[0], line[1]), strip.polygon) and _point_in_convex_polygon(
        (line[2], line[3]), strip.polygon
    )


def _filter_proven_wall_strip_geometry(
    segments: Sequence[Mapping[str, object]],
    strips: Sequence[_ProvenFilledWallStrip],
) -> tuple[dict, ...]:
    """Keep wall faces while suppressing proven subordinate strip geometry.

    Source-path end closures and non-parallel cross-strip strokes belong to the
    already-proven filled wall assembly and cannot independently mint walls.
    A source-tagged grid axis is excluded only when its complete primitive is
    geometrically contained by that same proven wall strip; the layer string by
    itself remains non-authoritative, preserving fail-closed A-GRID behavior.
    """
    face_ids = {raw_id for strip in strips for raw_id in strip.face_raw_ids}
    boundary_ids = {raw_id for strip in strips for raw_id in strip.boundary_raw_ids}
    segment_by_id = {
        str(segment.get("id") or ""): segment
        for segment in segments
        if str(segment.get("id") or "")
    }
    strip_face_lines = {
        strip.path_index: (
            _segment_geometry(segment_by_id[strip.face_raw_ids[0]])
            if strip.face_raw_ids[0] in segment_by_id
            else None
        )
        for strip in strips
    }
    kept: list[dict] = []
    for original in segments:
        segment = dict(original)
        raw_id = str(segment.get("id") or "")
        if raw_id in face_ids:
            kept.append(segment)
            continue
        if raw_id in boundary_ids:
            continue

        excluded = False
        for strip in strips:
            if not _segment_contained_by_strip(segment, strip):
                continue
            layer = str(segment.get("layer") or "").strip().lower()
            if "grid" in layer or "axis" in layer:
                excluded = True
                break
            line = _segment_geometry(segment)
            face_line = strip_face_lines.get(strip.path_index)
            if face_line is not None and not _parallel(line, face_line):
                excluded = True
                break
        if not excluded:
            kept.append(segment)
    return tuple(kept)


def _producer_wall_strip_relation_overrides(
    *,
    records: Sequence[PhysicalWallCandidateRecord],
    strips: Sequence[_ProvenFilledWallStrip],
) -> dict[tuple[str, str], PhysicalEquivalenceClass]:
    overrides: dict[tuple[str, str], PhysicalEquivalenceClass] = {}
    for strip in strips:
        face_ids = set(strip.face_raw_ids)
        member_ids = sorted(
            {
                record.wall_candidate_id
                for record in records
                if face_ids & set(record.physical_identity.source_primitive_ids)
            }
        )
        if len(member_ids) < 2:
            continue
        for index, left_id in enumerate(member_ids):
            for right_id in member_ids[index + 1 :]:
                overrides[(left_id, right_id)] = PhysicalEquivalenceClass.SAME_PHYSICAL_WALL
    return overrides


def _opening_raw_relation_sets(
    raw_lines: Mapping[str, Line],
) -> dict[tuple[str, str], set[PhysicalEquivalenceClass]]:
    """Derive relations only for a complete six-primitive G17 opening pattern."""
    if len(raw_lines) != 6:
        return {}
    items = sorted(raw_lines.items())
    breaks: list[_TrustedFaceBreak] = []
    for index, (left_id, left_line) in enumerate(items):
        for right_id, right_line in items[index + 1 :]:
            candidate = _trusted_face_break(left_id, left_line, right_id, right_line)
            if candidate is not None:
                breaks.append(candidate)

    relation_sets: dict[tuple[str, str], set[PhysicalEquivalenceClass]] = {}
    all_ids = set(raw_lines)
    for index, first in enumerate(breaks):
        for second in breaks[index + 1 :]:
            if not _same_gap(first, second) or not _distinct_parallel_axes(first, second):
                continue
            face_ids = {
                first.first_raw_id,
                first.second_raw_id,
                second.first_raw_id,
                second.second_raw_id,
            }
            if len(face_ids) != 4:
                continue
            remaining = sorted(all_ids - face_ids)
            if len(remaining) != 2:
                continue
            start_matches = [
                raw_id
                for raw_id in remaining
                if _segment_matches(
                    raw_lines[raw_id], first.start_point, second.start_point
                )
            ]
            end_matches = [
                raw_id
                for raw_id in remaining
                if _segment_matches(
                    raw_lines[raw_id], first.end_point, second.end_point
                )
            ]
            if len(start_matches) != 1 or len(end_matches) != 1:
                continue
            if start_matches[0] == end_matches[0]:
                continue

            same_pairs = {
                tuple(sorted((first.first_raw_id, second.first_raw_id))),
                tuple(sorted((first.second_raw_id, second.second_raw_id))),
            }
            pattern_ids = sorted(face_ids | {start_matches[0], end_matches[0]})
            if len(pattern_ids) != 6:
                continue
            for left_index, left_id in enumerate(pattern_ids):
                for right_id in pattern_ids[left_index + 1 :]:
                    pair = tuple(sorted((left_id, right_id)))
                    classification = (
                        PhysicalEquivalenceClass.SAME_PHYSICAL_WALL
                        if pair in same_pairs
                        else PhysicalEquivalenceClass.DISTINCT_PHYSICAL_WALLS
                    )
                    relation_sets.setdefault(pair, set()).add(classification)
    return relation_sets


def _producer_proven_page_opening_records(
    *, source_producer: SourceVisibilityProducer, published, page_id: str,
    physical_opening_authority: PhysicalOpeningAuthority,
    resolved_visible_observations: Optional[Sequence[tuple[str, object]]] = None,
    proof_scope_fingerprint: str = "direct-full-page",
) -> tuple[PhysicalOpeningExistenceRecord, ...]:
    """Share the full-page positive proof inventory, with fresh integrity.

    This is individual existence evidence only. It never supplies a count or
    semantic universe completeness. Prove every authenticated page observation
    once; no caller candidate list or preflight geometry narrows that universe.
    """
    if type(physical_opening_authority) is not PhysicalOpeningAuthority:
        raise TypeError("physical_opening_authority must be producer-owned")
    reader = physical_opening_authority._source_visibility_authority
    if (reader is None
            or reader._source_authority._store is not source_producer._producer._store
            or (physical_opening_authority._source_visibility_producer is not None
                and physical_opening_authority._source_visibility_producer is not source_producer)):
        raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
    visibility = source_producer.authority()
    # A damaged competitor can invalidate a cached uniqueness proof even when
    # the opening's own six source observations are unchanged.
    authenticated = visibility.authenticated_visible_observations(published)
    authenticated_by_id = {
        observation_id: observation for observation_id, observation in authenticated
    }
    # Source-visible IDs are the authority's original observation traversal.
    # The old W4/G17 loop proved this order directly from the published
    # snapshot; an authenticated page index may return an equivalent set in
    # a different order and silently change representative host ownership.
    rows = tuple(
        (observation_id, authenticated_by_id[observation_id])
        for observation_id in published.visible_observation_ids
        if observation_id in authenticated_by_id
        and str(authenticated_by_id[observation_id].page_id) == str(page_id)
    )
    if (resolved_visible_observations is not None
            and (len(resolved_visible_observations) != len(rows)
                 or dict(resolved_visible_observations) != dict(rows))):
        raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
    key = (published.revision.document_id, published.revision.revision_id,
           published.revision.source_sha256, published.snapshot.snapshot_id,
           str(page_id), str(proof_scope_fingerprint))
    cached = physical_opening_authority._wall_source_opening_page_proof_cache.get(key)
    if cached is not None:
        return cached
    proven: dict[str, PhysicalOpeningExistenceRecord] = {}
    for observation_id, observation in rows:
        if str(observation.page_id) != str(page_id):
            raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
        result = physical_opening_authority.prove_existence(ObservationSelector(
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256=published.revision.source_sha256,
            snapshot_id=published.snapshot.snapshot_id, observation_id=observation_id))
        opening = result.existence_record
        if (result.status is EvidenceResolutionStatus.CORROBORATED
                and result.proposition == PHYSICAL_OPENING_EXISTS
                and opening is not None and str(opening.page_id) == str(page_id)):
            proven[opening.record_id] = opening
    # Preserve first authenticated source-observation witness order. The
    # previous W4 path consumed dict insertion order, which controls the
    # representative provenance of competing/adjacent physical openings.
    # Sorting hashed record IDs can silently alter host binding precedence.
    records = tuple(proven.values())
    physical_opening_authority._wall_source_opening_page_proof_cache[key] = records
    return records


def _producer_proven_opening_wall_face_source_ids(
    *, source_producer: SourceVisibilityProducer, published, page_id: str,
    physical_opening_authority: PhysicalOpeningAuthority,
    resolved_visible_observations: Optional[Sequence[tuple[str, object]]] = None,
) -> frozenset[str]:
    """Reauthenticate complete opening representatives before motif pruning.

    Global enumeration completeness is not required for an individual positive
    object. Every contributing opening and all six supports are independently
    re-proven against the same producer snapshot; only its two SAME face pairs
    may preserve geometry. The result establishes neither counts nor wall role.
    """
    visibility = source_producer.authority()
    try:
        # A damaged competitor outside an opening's six supports can invalidate
        # the old uniqueness proof. Reauthenticate the complete source snapshot
        # before consuming any cached positive opening representative.
        openings = _producer_proven_page_opening_records(
            source_producer=source_producer, published=published, page_id=page_id,
            physical_opening_authority=physical_opening_authority,
            resolved_visible_observations=resolved_visible_observations,
            proof_scope_fingerprint="source-face-pre-motif")
    except RuntimeError:
        return frozenset()
    protected: set[str] = set()
    for opening in openings:
        if (opening.snapshot_id != published.snapshot.snapshot_id
                or str(opening.page_id) != str(page_id)
                or opening.structural_pattern != JAMB_BOUNDED_TWO_FACE_INTERRUPTION
                or len(opening.source_observation_ids) != 6):
            continue
        raw_lines: dict[str, Line] = {}
        for observation_id in opening.source_observation_ids:
            resolved = visibility.resolve_visible(ObservationSelector(
                document_id=opening.document_id, revision_id=opening.revision_id,
                source_sha256=opening.source_sha256, snapshot_id=opening.snapshot_id,
                observation_id=observation_id))
            observation = resolved.observation
            if (resolved.status is not EvidenceResolutionStatus.CORROBORATED
                    or observation is None or str(observation.page_id) != str(page_id)):
                break
            prefix = ("visible:segment:" if observation.observation_kind == NATIVE_PDF_VISIBLE_SEGMENT
                      else "visible:" if observation.observation_kind == RASTER_PDF_VISIBLE_SEGMENT
                      else None)
            ref = str(observation.source_primitive_ref or "")
            if prefix is None or not ref.startswith(prefix):
                break
            raw_id = ref[len(prefix):]
            line = _line(observation.geometry)
            if not raw_id or raw_id in raw_lines or line is None:
                break
            raw_lines[raw_id] = line
        if len(raw_lines) != 6:
            continue
        relations = _opening_raw_relation_sets(raw_lines)
        same_pairs = [pair for pair, classes in relations.items()
                      if classes == {PhysicalEquivalenceClass.SAME_PHYSICAL_WALL}]
        faces = {raw_id for pair in same_pairs for raw_id in pair}
        if len(same_pairs) == 2 and len(faces) == 4:
            protected.update(faces)
    return frozenset(protected)


def _producer_opening_relation_overrides(
    *,
    source_producer: SourceVisibilityProducer,
    published,
    page_id: str,
    records: Sequence[PhysicalWallCandidateRecord],
    resolved_visible_observations: Optional[Sequence[tuple[str, object]]] = None,
    physical_opening_authority: Optional[PhysicalOpeningAuthority] = None,
) -> dict[tuple[str, str], PhysicalEquivalenceClass]:
    """Re-prove G17 source openings and map their exact primitives to W4 candidates."""
    by_raw_id: dict[str, list[PhysicalWallCandidateRecord]] = {}
    for record in records:
        for raw_id in record.physical_identity.source_primitive_ids:
            by_raw_id.setdefault(str(raw_id), []).append(record)

    # An opening override is accepted only when its six source primitives map
    # to six distinct wall candidates below. Fewer than six candidate records
    # can therefore never contribute an override.
    if len(records) < 6 or len(by_raw_id) < 6:
        return {}

    visibility = source_producer.authority()
    opening_authority = (
        physical_opening_authority
        if physical_opening_authority is not None
        else PhysicalOpeningAuthority.from_source_visibility_producer(source_producer)
    )

    if resolved_visible_observations is None:
        page_visible_rows: list[tuple[str, object]] = []
        for observation_id in published.visible_observation_ids:
            selector = ObservationSelector(
                document_id=published.revision.document_id,
                revision_id=published.revision.revision_id,
                source_sha256=published.revision.source_sha256,
                snapshot_id=published.snapshot.snapshot_id,
                observation_id=observation_id,
            )
            visible = visibility.resolve_visible(selector)
            if (
                visible.status is not EvidenceResolutionStatus.CORROBORATED
                or visible.observation is None
            ):
                continue
            if str(visible.observation.page_id) == str(page_id):
                page_visible_rows.append((observation_id, visible.observation))
    else:
        page_visible_rows = list(resolved_visible_observations)

    page_observation_by_id = {
        observation_id: observation
        for observation_id, observation in page_visible_rows
    }

    prefix = "visible:segment:"

    # Share complete, freshly authenticated page proofs between W4 scopes.
    proven_records = _producer_proven_page_opening_records(
        source_producer=source_producer, published=published, page_id=page_id,
        physical_opening_authority=opening_authority,
        resolved_visible_observations=page_visible_rows,
        # Complete G17 page proofs are never narrowed by the W4 scope.
        # Partition *reuse* by exact producer-owned wall candidate identity,
        # because separate W4 scopes must not inherit a warmed proof cache
        # created under another physical wall scope.
        proof_scope_fingerprint=hashlib.sha256(repr(tuple(sorted(
            (str(record.wall_candidate_id), tuple(sorted(
                str(raw_id) for raw_id in record.physical_identity.source_primitive_ids
            ))) for record in records
        ))).encode("utf-8")).hexdigest())

    candidate_relation_sets: dict[
        tuple[str, str], set[PhysicalEquivalenceClass]
    ] = {}

    for existence in proven_records:
        raw_lines: dict[str, Line] = {}
        valid = True
        for observation_id in existence.source_observation_ids:  # type: ignore[attr-defined]
            observation = page_observation_by_id.get(observation_id)
            if observation is None and resolved_visible_observations is None:
                resolved = visibility.resolve_visible(
                    ObservationSelector(
                        document_id=existence.document_id,  # type: ignore[attr-defined]
                        revision_id=existence.revision_id,  # type: ignore[attr-defined]
                        source_sha256=existence.source_sha256,  # type: ignore[attr-defined]
                        snapshot_id=existence.snapshot_id,  # type: ignore[attr-defined]
                        observation_id=observation_id,
                    )
                )
                if resolved.status is EvidenceResolutionStatus.CORROBORATED:
                    observation = resolved.observation
            if (
                observation is None
                or str(observation.page_id) != str(page_id)
                or not observation.source_primitive_ref.startswith(prefix)
            ):
                valid = False
                break
            raw_id = observation.source_primitive_ref[len(prefix) :]
            geometry = _line(observation.geometry)
            if not raw_id or geometry is None or raw_id in raw_lines:
                valid = False
                break
            raw_lines[raw_id] = geometry
        if not valid or len(raw_lines) != 6:
            continue

        raw_relations = _opening_raw_relation_sets(raw_lines)
        if not raw_relations:
            continue

        candidate_for_raw: dict[str, str] = {}
        for raw_id in raw_lines:
            matches = by_raw_id.get(raw_id, [])
            if len(matches) != 1:
                valid = False
                break
            candidate_for_raw[raw_id] = matches[0].wall_candidate_id

        if valid and len(set(candidate_for_raw.values())) == 6:
            # Historical complete translation: when every opening primitive is
            # itself represented by one W4 candidate, retain the full SAME /
            # DISTINCT relation set exactly as before.
            for (left_raw, right_raw), classifications in raw_relations.items():
                left_id = candidate_for_raw[left_raw]
                right_id = candidate_for_raw[right_raw]
                if left_id == right_id:
                    valid = False
                    break
                pair = tuple(sorted((left_id, right_id)))
                candidate_relation_sets.setdefault(pair, set()).update(classifications)
            if not valid:
                continue
            continue

        # A complete authenticated G17 opening proves two SAME wall-face pairs
        # independently of whether its jamb / frame primitives become W4 wall
        # candidates. Do not discard that positive wall identity evidence just
        # because non-wall opening geometry is absent downstream. Partial
        # translation is intentionally SAME-only: each face primitive must have
        # exactly one W4 owner, and no DISTINCT relation is inferred unless the
        # historical all-six mapping above is complete.
        for (left_raw, right_raw), classifications in raw_relations.items():
            if classifications != {PhysicalEquivalenceClass.SAME_PHYSICAL_WALL}:
                continue
            left_matches = by_raw_id.get(left_raw, [])
            right_matches = by_raw_id.get(right_raw, [])
            if len(left_matches) != 1 or len(right_matches) != 1:
                continue
            left_id = left_matches[0].wall_candidate_id
            right_id = right_matches[0].wall_candidate_id
            if left_id == right_id:
                continue
            pair = tuple(sorted((left_id, right_id)))
            candidate_relation_sets.setdefault(pair, set()).update(classifications)

    return {
        pair: next(iter(classifications))
        for pair, classifications in candidate_relation_sets.items()
        if len(classifications) == 1
    }



def _path_is_collinear_with_source_line(
    path: Sequence[Point],
    source_line: Line,
) -> bool:
    """Require every reconstructed path point to lie on one exact source line."""
    if len(path) < 2:
        return False
    direction = _canonical_direction(source_line)
    origin = (source_line[0], source_line[1])
    for point in path:
        offset = (float(point[0]) - origin[0], float(point[1]) - origin[1])
        if abs(_cross(direction, offset)) > _COORD_TOL:
            return False
    return True


def _projected_path_interval(
    path: Sequence[Point],
    source_line: Line,
) -> Optional[tuple[float, float]]:
    if len(path) < 2:
        return None
    direction = _canonical_direction(source_line)
    values = [
        _projection((float(point[0]), float(point[1])), direction)
        for point in path
    ]
    lower, upper = min(values), max(values)
    if upper - lower <= _COORD_TOL:
        return None
    return (lower, upper)


def _record_source_face_intervals_from_graph(
    *,
    record: PhysicalWallCandidateRecord,
    raw_id: str,
    source_line: Line,
    edges_by_id: Mapping[str, Mapping[str, object]],
) -> tuple[tuple[float, float], ...]:
    """Project only graph edges explicitly descended from one native primitive.

    W4 centerlines may legitimately bend at reconstructed junctions even when
    one contributing edge is an exact fragment of a single immutable source
    face. Physical SAME proof must therefore inspect the lineage-bearing edge
    fragments themselves, not require every point of the assembled centerline
    to remain collinear with that source primitive.
    """
    direction = _canonical_direction(source_line)
    intervals: list[tuple[float, float]] = []
    for edge_id in record.physical_identity.edge_ids:
        edge = edges_by_id.get(str(edge_id))
        if edge is None:
            continue
        lineage = edge.get(LINEAGE_KEY) or {}
        source_ids = {
            str(value)
            for value in tuple(lineage.get("source_primitive_ids") or ())
            if value not in (None, "")
        }
        if raw_id not in source_ids:
            continue
        try:
            edge_line = (
                float(edge["x1"]),
                float(edge["y1"]),
                float(edge["x2"]),
                float(edge["y2"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        # Exact source ancestry is necessary but not sufficient: the edge must
        # also lie on the native primitive. This rejects junction branches that
        # inherited plural lineage at an intersection.
        if not _collinear(edge_line, source_line):
            continue
        if abs(_cross(direction, (
            edge_line[0] - source_line[0],
            edge_line[1] - source_line[1],
        ))) > _COORD_TOL:
            continue
        values = (
            _projection((edge_line[0], edge_line[1]), direction),
            _projection((edge_line[2], edge_line[3]), direction),
        )
        lower, upper = min(values), max(values)
        if upper - lower > _COORD_TOL:
            intervals.append((lower, upper))
    return tuple(sorted(set(intervals)))


def _interval_sets_overlap_or_snap(
    left: Sequence[tuple[float, float]],
    right: Sequence[tuple[float, float]],
) -> bool:
    for left_interval in left:
        for right_interval in right:
            overlap = min(left_interval[1], right_interval[1]) - max(
                left_interval[0], right_interval[0]
            )
            if overlap > _COORD_TOL:
                return True
            gap = max(left_interval[0], right_interval[0]) - min(
                left_interval[1], right_interval[1]
            )
            if gap < 0.0:
                gap = 0.0
            if gap <= DEFAULT_GAP_SNAP_TOLERANCE_PT:
                return True
    return False


def _producer_shared_source_face_relation_overrides(
    *,
    segments: Sequence[Mapping[str, object]],
    records: Sequence[PhysicalWallCandidateRecord],
    graph: Optional[Mapping[str, object]] = None,
) -> dict[tuple[str, str], PhysicalEquivalenceClass]:
    """Prove duplicate W4 fragments descended from one exact native wall face.

    Comparison is narrowed by immutable source primitive id rather than spatial
    proximity. SAME requires a shared native Structural/Bearing primitive, both
    reconstructed paths lying collinearly on that exact source line, and either
    real longitudinal overlap or a residual gap no larger than Stage A's existing
    drafting/snap tolerance. The latter is valid only because the immutable native
    source primitive itself is one continuous line across the gap. Nearby
    independent walls, perpendicular junction branches, raster-only geometry and
    larger disconnected fragments abstain.
    """
    segment_by_id = {
        str(segment.get("id") or ""): segment
        for segment in segments
        if str(segment.get("id") or "")
    }
    records_by_raw_id: dict[str, list[PhysicalWallCandidateRecord]] = {}
    for record in records:
        identity = record.physical_identity
        if not identity.usable or identity.path_fingerprint is None:
            continue
        for raw_id in identity.source_primitive_ids:
            records_by_raw_id.setdefault(str(raw_id), []).append(record)

    relation_sets: dict[
        tuple[str, str], set[PhysicalEquivalenceClass]
    ] = {}
    graph_edges_by_id: dict[str, Mapping[str, object]] = {}
    if graph is not None:
        graph_edges_by_id = {
            str(edge.get("id")): edge
            for edge in tuple(graph.get("edges") or ())
            if isinstance(edge, Mapping) and edge.get("id") not in (None, "")
        }

    for raw_id, owners in sorted(records_by_raw_id.items()):
        if len(owners) < 2:
            continue
        source = segment_by_id.get(raw_id)
        if source is None:
            continue
        if source.get("source_kind") == RASTER_PDF_VISIBLE_SEGMENT:
            continue
        layer = str(source.get("layer") or "").strip().lower()
        layer_tokens = set(re.findall(r"[a-z0-9]+", layer))
        if not {"structural", "bearing"} <= layer_tokens:
            continue
        source_line = _line(
            (
                source.get("x1"),
                source.get("y1"),
                source.get("x2"),
                source.get("y2"),
            )
        )
        if source_line is None:
            continue

        ordered = sorted(owners, key=lambda item: item.wall_candidate_id)
        graph_intervals = {}
        if graph is not None:
            graph_intervals = {
                record.wall_candidate_id: _record_source_face_intervals_from_graph(
                    record=record,
                    raw_id=raw_id,
                    source_line=source_line,
                    edges_by_id=graph_edges_by_id,
                )
                for record in ordered
            }

        for index, left in enumerate(ordered):
            left_path = tuple(left.physical_identity.path_fingerprint or ())
            left_interval = None
            if graph is None:
                if not _path_is_collinear_with_source_line(left_path, source_line):
                    continue
                left_interval = _projected_path_interval(left_path, source_line)
                if left_interval is None:
                    continue
            elif not graph_intervals.get(left.wall_candidate_id):
                continue

            for right in ordered[index + 1 :]:
                if graph is None:
                    right_path = tuple(right.physical_identity.path_fingerprint or ())
                    if not _path_is_collinear_with_source_line(right_path, source_line):
                        continue
                    right_interval = _projected_path_interval(right_path, source_line)
                    if right_interval is None:
                        continue
                    if not _interval_sets_overlap_or_snap((left_interval,), (right_interval,)):
                        continue
                else:
                    right_intervals = graph_intervals.get(right.wall_candidate_id, ())
                    if not right_intervals:
                        continue
                    if not _interval_sets_overlap_or_snap(
                        graph_intervals[left.wall_candidate_id],
                        right_intervals,
                    ):
                        continue

                pair = tuple(
                    sorted((left.wall_candidate_id, right.wall_candidate_id))
                )
                relation_sets.setdefault(pair, set()).add(
                    PhysicalEquivalenceClass.SAME_PHYSICAL_WALL
                )

    return {
        pair: next(iter(classifications))
        for pair, classifications in relation_sets.items()
        if len(classifications) == 1
    }


def _union_find_groups(
    pairs: Sequence[tuple[str, str]], members: Sequence[str]
) -> list[list[str]]:
    parent = {member: member for member in members}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for left, right in pairs:
        if left in parent and right in parent:
            union(left, right)
    groups: dict[str, list[str]] = {}
    for member in members:
        groups.setdefault(find(member), []).append(member)
    return [sorted(group) for group in groups.values()]


def _apply_trusted_relation_overrides(
    identities: Sequence[PhysicalWallIdentity],
    baseline: PhysicalWallEquivalenceResolution,
    overrides: Mapping[tuple[str, str], PhysicalEquivalenceClass],
    *,
    allow_proven_same_over_distinct: bool = False,
) -> PhysicalWallEquivalenceResolution:
    """Reconcile source-proven relations without changing generic classifier semantics."""
    usable = [identity for identity in identities if identity.usable]
    if not overrides:
        return baseline

    pair_map = {
        tuple(sorted((left, right))): classification
        for left, right, classification in baseline.pair_classifications
    }
    member_id_set = {identity.wall_candidate_id for identity in usable}
    known_id_set = {
        identity.wall_candidate_id
        for identity in identities
        if identity is not None
    }
    unusable_id_set = known_id_set - member_id_set
    restored_pairs = baseline.candidate_pair_audit.trusted_override_pairs_restored
    rejected_pairs = baseline.candidate_pair_audit.trusted_override_pairs_rejected
    rejection_reason_counts = dict(
        baseline.candidate_pair_audit.trusted_override_rejection_reason_counts
    )
    for pair, classification in overrides.items():
        key = tuple(sorted(pair))
        current = pair_map.get(key)
        if current is None:
            # The candidate gate saw no plausible same-wall relationship, but
            # a producer has since proven one from source. Positive evidence
            # outranks the gate, so restore the relation rather than dropping
            # it. Pairs outside the usable member set are explicitly rejected.
            if key[0] in member_id_set and key[1] in member_id_set:
                pair_map[key] = classification.value
                restored_pairs += 1
            else:
                rejected_pairs += 1
                if key[0] not in known_id_set or key[1] not in known_id_set:
                    reason = TRUSTED_EQUIVALENCE_OVERRIDE_UNKNOWN_MEMBER
                elif key[0] in unusable_id_set or key[1] in unusable_id_set:
                    reason = TRUSTED_EQUIVALENCE_OVERRIDE_UNUSABLE_MEMBER
                else:
                    reason = TRUSTED_EQUIVALENCE_OVERRIDE_UNKNOWN_MEMBER
                rejection_reason_counts[reason] = (
                    rejection_reason_counts.get(reason, 0) + 1
                )
            continue
        if current == classification.value:
            # Deterministic idempotent replay is accepted as a no-op.
            continue
        if (
            current == PhysicalEquivalenceClass.AMBIGUOUS_PHYSICAL_EQUIVALENCE.value
            or (
                allow_proven_same_over_distinct
                and classification is PhysicalEquivalenceClass.SAME_PHYSICAL_WALL
                and current == PhysicalEquivalenceClass.DISTINCT_PHYSICAL_WALLS.value
            )
        ):
            pair_map[key] = classification.value
        else:
            rejected_pairs += 1
            rejection_reason_counts[
                TRUSTED_EQUIVALENCE_OVERRIDE_CONFLICT
            ] = rejection_reason_counts.get(
                TRUSTED_EQUIVALENCE_OVERRIDE_CONFLICT, 0
            ) + 1

    member_ids = [identity.wall_candidate_id for identity in usable]
    same_links: list[tuple[str, str]] = []
    ambiguous_links: list[tuple[str, str]] = []
    distinct_links: list[tuple[str, str]] = []
    for pair, classification in pair_map.items():
        if classification == PhysicalEquivalenceClass.SAME_PHYSICAL_WALL.value:
            same_links.append(pair)
        elif classification == PhysicalEquivalenceClass.AMBIGUOUS_PHYSICAL_EQUIVALENCE.value:
            ambiguous_links.append(pair)
        elif classification == PhysicalEquivalenceClass.DISTINCT_PHYSICAL_WALLS.value:
            distinct_links.append(pair)

    distinct_neighbors: dict[str, set[str]] = {}
    for left, right in distinct_links:
        distinct_neighbors.setdefault(left, set()).add(right)
        distinct_neighbors.setdefault(right, set()).add(left)

    # A proven SAME subgroup remains positive identity evidence even when one
    # of its members has unresolved relations to candidates outside that group.
    # This does not make the full candidate universe publishable: publication
    # below still uses SAME + AMBIGUOUS components and therefore remains
    # fail-closed. A positive DISTINCT relation inside the SAME-connected
    # subgroup is contradictory and withholds that subgroup entirely.
    positive_same_groups: list[tuple[str, ...]] = []
    if same_links:
        for component in _union_find_groups(same_links, member_ids):
            if len(component) < 2:
                continue
            component_set = set(component)
            contradictory = any(
                neighbour in component_set
                for wall_id in component
                for neighbour in distinct_neighbors.get(wall_id, ())
            )
            if not contradictory:
                positive_same_groups.append(tuple(sorted(component)))

    related_links = same_links + ambiguous_links
    components = _union_find_groups(related_links, member_ids) if member_ids else []
    ambiguous_edges = {frozenset(pair) for pair in ambiguous_links}
    same_edges = {frozenset(pair) for pair in same_links}
    # Recompute usable-pair publication from the reconciled graph, but preserve
    # the original fail-closed blockers for identities that were unusable
    # before trusted relation reconciliation.
    blockers: dict[str, list[str]] = {
        wall_id: list(baseline.blocking_reasons_by_wall_id.get(wall_id, ()))
        for wall_id in sorted(unusable_id_set)
        if baseline.blocking_reasons_by_wall_id.get(wall_id)
    }
    ambiguous_walls: set[str] = set()
    same_groups: list[tuple[str, ...]] = []
    representatives: list[str] = []

    for component in components:
        has_ambiguous = any(
            frozenset((left, right)) in ambiguous_edges
            for index, left in enumerate(component)
            for right in component[index + 1 :]
        )
        has_same = any(
            frozenset((left, right)) in same_edges
            for index, left in enumerate(component)
            for right in component[index + 1 :]
        )
        component_set = set(component)
        has_distinct_conflict = has_same and any(
            neighbour in component_set
            for wall_id in component
            for neighbour in distinct_neighbors.get(wall_id, ())
        )
        if has_distinct_conflict:
            ambiguous_walls.update(component)
            for wall_id in component:
                blockers.setdefault(wall_id, []).append(
                    "conflicting_physical_wall_equivalence"
                )
            continue
        if has_ambiguous:
            ambiguous_walls.update(component)
            for wall_id in component:
                blockers.setdefault(wall_id, []).append(
                    "ambiguous_physical_wall_equivalence"
                )
            continue
        if has_same and len(component) > 1:
            group = tuple(sorted(component))
            same_groups.append(group)
            representative = sorted(group)[0]
            representatives.append(representative)
            for wall_id in group:
                if wall_id != representative:
                    blockers.setdefault(wall_id, []).append(
                        f"equivalent_physical_wall_represented_by:{representative}"
                    )
            continue
        representatives.extend(
            wall_id for wall_id in component if wall_id not in blockers
        )

    linked = {wall_id for component in components for wall_id in component}
    for wall_id in member_ids:
        if wall_id not in linked and wall_id not in blockers:
            representatives.append(wall_id)

    # Retain producer-proven SAME subgroups for downstream identity
    # normalization even when ambient ambiguity blocks global publication.
    # Final publication ordering is canonical so caller/input ordering cannot
    # alter semantic results.
    same_groups = sorted(set((*same_groups, *positive_same_groups)))

    representatives = sorted(set(representatives))
    abstained = sorted(
        wall_id
        for wall_id in known_id_set
        if wall_id in blockers
    )
    return PhysicalWallEquivalenceResolution(
        scope_viewport_id=baseline.scope_viewport_id,
        representative_wall_ids=tuple(representatives),
        abstained_wall_ids=tuple(abstained),
        equivalence_groups=tuple(same_groups),
        ambiguous_wall_ids=tuple(sorted(ambiguous_walls)),
        same_wall_ids=tuple(
            sorted({wall_id for group in same_groups for wall_id in group})
        ),
        pair_classifications=tuple(
            sorted((left, right, classification) for (left, right), classification in pair_map.items())
        ),
        blocking_reasons_by_wall_id={
            wall_id: tuple(dict.fromkeys(reasons))
            for wall_id, reasons in blockers.items()
            if reasons
        },
        candidate_pair_audit=CandidatePairAudit(
            # Preserve the gate census exactly. Restored trusted pairs are
            # recorded separately and must not rewrite why the gate excluded
            # the original pair.
            total_pairs=baseline.candidate_pair_audit.total_pairs,
            considered_pairs=baseline.candidate_pair_audit.considered_pairs,
            excluded_pairs=baseline.candidate_pair_audit.excluded_pairs,
            exclusion_reason_counts=dict(
                baseline.candidate_pair_audit.exclusion_reason_counts
            ),
            trusted_override_pairs_restored=restored_pairs,
            trusted_override_pairs_rejected=rejected_pairs,
            trusted_override_rejection_reason_counts=dict(
                sorted(rejection_reason_counts.items())
            ),
            verified_points_per_mm=(
                baseline.candidate_pair_audit.verified_points_per_mm
            ),
            candidate_wall_body_band_pt=(
                baseline.candidate_pair_audit.candidate_wall_body_band_pt
            ),
        ),
    )


def _source_snap_collapsed_fragment_inventory(graph, identities):
    """Retain exact W2 negatives beside their uniquely adjacent W4 owner.

    Both source endpoints need surviving same-ancestor edges meeting at the
    same snapped node, and one usable identity must own both. This is a
    source-loss audit, never permission to bridge a missing graph edge.
    """
    endpoints = defaultdict(list)
    owners = defaultdict(set)
    for candidate_id, identity in identities.items():
        if identity.usable:
            for edge_id in identity.edge_ids:
                owners[str(edge_id)].add(candidate_id)
    for edge in graph.get("edges", ()):
        line = _line(_segment_geometry(edge))
        parents = frozenset(str(p) for p in (edge.get(LINEAGE_KEY) or {}).get(
            "source_primitive_ids", ()))
        if line is None or not parents:
            continue
        for point, node in ((line[:2], edge.get("a")), (line[2:], edge.get("b"))):
            if node is not None:
                for parent in parents:
                    endpoints[(point, parent)].append((str(edge["id"]), node, parents))
    inventory = defaultdict(list)
    surviving_ids = {str(edge["id"]) for edge in graph.get("edges", ())}
    collapsed = tuple(graph.get("snap_collapsed_fragments", ()))
    id_counts = Counter(str(fragment.get("id") or "") for fragment in collapsed)
    for fragment in collapsed:
        fragment_id = str(fragment.get("id") or "")
        line = _line(_segment_geometry(fragment))
        parents = frozenset(str(p) for p in (fragment.get(LINEAGE_KEY) or {}).get(
            "source_primitive_ids", ()))
        if (fragment.get("reason") != SNAP_COLLAPSE_REASON or not fragment_id
                or fragment_id in surviving_ids or id_counts[fragment_id] != 1
                or line is None or not parents):
            continue
        parent = min(parents)  # Index only; all parents are checked below.
        candidates = set()
        for left_id, left_node, left_parents in endpoints[(line[:2], parent)]:
            for right_id, right_node, right_parents in endpoints[(line[2:], parent)]:
                if (left_id == right_id or left_node != right_node
                        or not parents <= left_parents & right_parents):
                    continue
                candidates.update(owners[left_id] & owners[right_id])
        if len(candidates) != 1:
            continue
        candidate_id = next(iter(candidates))
        if not parents <= set(identities[candidate_id].source_primitive_ids):
            continue
        inventory[candidate_id].append(PhysicalWallSnapCollapsedFragment(
            edge_id=fragment_id, geometry=line,
            source_primitive_ids=tuple(sorted(parents))))
    return {candidate_id: tuple(sorted(rows, key=lambda row: row.edge_id))
            for candidate_id, rows in inventory.items()}


def _assemble_source_owned_w4_identities_or_unavailable(
    *,
    graph,
    junctions,
    relationships,
    scope_id: str,
):
    """Fail closed on provenance-ambiguous W4 candidate addresses.

    Only known W4 identity-collision errors become unavailable scope. Every
    other unexpected assembly error still propagates for engineering diagnosis.
    This function never invents a wall candidate or equivalence relation.
    """
    try:
        walls, rekeyed_junctions = assemble_wall_topology(
            graph, junctions, relationships, viewport_id=scope_id
        )
        identities = collect_physical_wall_identities(walls, graph)
    except (W4SourceCandidateAddressCollision, DuplicateW4CandidateAddress):
        # No producer evidence can decide which source W4 row owns the address.
        # The caller emits a complete-scope ABSTAIN, not a guessed identity.
        return None
    return walls, rekeyed_junctions, identities


def _assemble_scope_result(
    *,
    source_producer: SourceVisibilityProducer,
    published,
    page_id: str,
    selector: PhysicalWallCandidateSelector,
    segments: Sequence[dict],
    source_observation_ids: Sequence[str],
    page_width: float,
    page_height: float,
    source_bytes: bytes,
    viewport=None,
    sibling_set_fingerprint: Optional[str] = None,
    pre_boundary_reasons: Sequence[str] = (),
    scope_boundary_observation_ids: Sequence[str] = (),
    ambiguous_source_observation_ids: Sequence[str] = (),
    points_per_mm: Optional[float] = None,
    resolved_visible_observations: Optional[Sequence[tuple[str, object]]] = None,
    physical_opening_authority: Optional[PhysicalOpeningAuthority] = None,
    excluded_boundary_primitives: Sequence[ExcludedBoundaryPrimitive] = (),
    authenticated_frame_edge_primitive_count: int = 0,
) -> PhysicalWallCandidateScopeResult:
    scope_id = selector.decision_scope_id
    # Source-proven face protection is DIAGNOSTIC ONLY until the original
    # Lot16/W4 candidate, host and frame identity preservation is proved.
    # The pre-motif helper remains available for standalone producer-owned
    # source analysis and positive fixture tests; calling it here would run a
    # second whole-page source proof and rekey live physical wall topology.
    topology_segments = _filter_repeated_non_physical_drafting_primitives(
        segments,
        page_width=page_width,
        page_height=page_height,
    )
    if len(topology_segments) > MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS:
        return _blocked(
            selector,
            PHYSICAL_WALL_CANDIDATE_SCOPE_COMPLEXITY_EXCEEDED,
        )
    proven_wall_strips = _proven_filled_wall_strips(topology_segments)
    graph_segments = _filter_proven_wall_strip_geometry(
        topology_segments,
        proven_wall_strips,
    )
    graph = build_wall_graph_for_viewport(graph_segments)
    try:
        typed_semantic_evidence_atoms = tuple(
            collect_source_lineage_grid_evidence(
                graph,
                document_id=published.revision.document_id,
                page_id=page_id,
                viewport_id=scope_id,
            )
        )
    except Exception:  # pragma: no cover - additive semantic sidecar is fail-open
        typed_semantic_evidence_atoms = ()
    junctions, relationships = classify_junctions(
        graph,
        document_id=published.revision.document_id,
        page_id=page_id,
        viewport_id=scope_id,
    )
    assembled = _assemble_source_owned_w4_identities_or_unavailable(
        graph=graph,
        junctions=junctions,
        relationships=relationships,
        scope_id=scope_id,
    )
    if assembled is None:
        return _blocked(selector, PHYSICAL_WALL_CANDIDATE_IDENTITY_UNRESOLVED)
    walls, _rekeyed_junctions, identities = assembled
    collapsed_source_fragments = _source_snap_collapsed_fragment_inventory(graph, identities)
    graph_edges = {str(edge["id"]): edge for edge in graph["edges"]}

    ordered_walls = sorted(walls, key=lambda item: item.candidate_id)
    records: list[PhysicalWallCandidateRecord] = []
    ordered_identities: list[PhysicalWallIdentity] = []
    for wall in ordered_walls:
        identity = identities.get(wall.candidate_id)
        if identity is None or not identity.usable:
            return _blocked(selector, PHYSICAL_WALL_CANDIDATE_IDENTITY_UNRESOLVED)
        records.append(
            PhysicalWallCandidateRecord(
                wall_candidate_id=wall.candidate_id,
                wall_candidate=wall,
                physical_identity=identity,
                source_snap_collapsed_fragments=collapsed_source_fragments.get(wall.candidate_id, ()),
                source_edge_fragments=tuple(
                    PhysicalWallSourceEdgeFragment(
                        edge_id=str(edge_id),
                        geometry=_segment_geometry(graph_edges[str(edge_id)]),
                        source_primitive_ids=tuple(sorted(set(
                            str(value) for value in
                            (graph_edges[str(edge_id)].get(LINEAGE_KEY) or {}).get(
                                "source_primitive_ids", ())
                        ))),
                    )
                    for edge_id in sorted(identity.edge_ids)
                    if str(edge_id) in graph_edges
                ),
            )
        )
        ordered_identities.append(identity)

    # Shadow-only native graphic-state census. This reads the exact visible
    # source segments before topology filtering and cannot alter any authority
    # decision, record, equivalence class, completeness flag or reason code.
    try:
        source_metadata_table = build_physical_wall_source_metadata_scope_table(
            records=tuple(records),
            source_segments=tuple(segments),
            page_id=page_id,
            decision_scope_id=scope_id,
        )
    except Exception as exc:  # pragma: no cover - shadow metadata is fail-open
        source_metadata_table = unavailable_physical_wall_source_metadata_scope_table(
            page_id=page_id,
            decision_scope_id=scope_id,
            reason_code=f"source_metadata_shadow_error:{type(exc).__name__}",
        )

    baseline_equivalence = resolve_physical_wall_equivalence(
        tuple(ordered_identities),
        walls_by_id={wall.candidate_id: wall for wall in ordered_walls},
        points_per_mm=points_per_mm,
    )
    strip_overrides = _producer_wall_strip_relation_overrides(
        records=tuple(records),
        strips=proven_wall_strips,
    )
    equivalence = _apply_trusted_relation_overrides(
        tuple(ordered_identities),
        baseline_equivalence,
        strip_overrides,
        allow_proven_same_over_distinct=True,
    )
    shared_face_overrides = _producer_shared_source_face_relation_overrides(
        segments=graph_segments,
        records=tuple(records),
        graph=graph,
    )
    equivalence = _apply_trusted_relation_overrides(
        tuple(ordered_identities),
        equivalence,
        shared_face_overrides,
        allow_proven_same_over_distinct=True,
    )
    trusted_overrides = _producer_opening_relation_overrides(
        source_producer=source_producer,
        published=published,
        page_id=page_id,
        records=tuple(records),
        resolved_visible_observations=resolved_visible_observations,
        physical_opening_authority=physical_opening_authority,
    )
    equivalence = _apply_trusted_relation_overrides(
        tuple(ordered_identities),
        equivalence,
        trusted_overrides,
    )

    boundary_reasons: list[str] = list(pre_boundary_reasons)
    wall_boundary_reasons: dict[str, str] = {}
    boundary_pdf = fitz.open(stream=source_bytes, filetype="pdf")
    try:
        boundary_page = boundary_pdf.load_page(int(page_id) - 1)
        page_viewports = (
            _all_viewports(boundary_page, page_number=int(page_id))
            if viewport is None
            else None
        )
        if viewport is None:
            source_producer._physical_wall_page_viewports_cache[
                _page_viewports_cache_key(
                    published=published,
                    page_id=page_id,
                )
            ] = (
                None
                if page_viewports is None
                else tuple(page_viewports)
            )
        for wall in ordered_walls:
            if viewport is None:
                reason = _scope_boundary_reason_from_viewports(
                    wall,
                    all_viewports=page_viewports,
                    page_width=page_width,
                    page_height=page_height,
                )
            else:
                reason = _viewport_scope_boundary_reason(
                    wall,
                    bbox=viewport.bounding_box,
                    page_width=page_width,
                    page_height=page_height,
                )
            if reason is not None:
                boundary_reasons.append(reason)
                wall_boundary_reasons[str(wall.candidate_id)] = reason
    finally:
        boundary_pdf.close()

    # Shadow-only: never influences scope_complete or reason_codes below.
    try:
        boundary_evaluation = _evaluate_scope_boundary(
            ordered_walls=ordered_walls,
            wall_boundary_reasons=wall_boundary_reasons,
            excluded_boundary_primitives=tuple(excluded_boundary_primitives),
            authenticated_frame_edge_primitive_count=(
                authenticated_frame_edge_primitive_count
            ),
        )
    except Exception as exc:  # pragma: no cover - shadow metadata must never break live
        boundary_evaluation = PhysicalWallScopeBoundaryEvaluation(
            status=BOUNDARY_EVALUATION_UNAVAILABLE,
            reason_code=f"boundary_evaluation_error:{type(exc).__name__}",
            evaluated_wall_candidate_ids=(),
            boundary_tainted_wall_candidate_ids=(),
            boundary_taint_reason_codes=(),
            excluded_boundary_primitives=(),
            authenticated_frame_edge_primitive_count=0,
            contact_tolerance_pt=float(DEFAULT_GAP_SNAP_TOLERANCE_PT),
        )

    cropped = bool(boundary_reasons)
    reason_codes = (
        (PHYSICAL_WALL_CANDIDATE_SCOPE_RESOLVED, *dict.fromkeys(boundary_reasons))
        if cropped
        else (PHYSICAL_WALL_CANDIDATE_SCOPE_RESOLVED,)
    )
    viewport_bbox = (
        None
        if viewport is None or viewport.bounding_box is None
        else tuple(float(value) for value in viewport.bounding_box)
    )
    return PhysicalWallCandidateScopeResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=not cropped,
        records=tuple(records),
        source_observation_ids=tuple(sorted(dict.fromkeys(source_observation_ids))),
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        page_id=page_id,
        decision_scope_id=scope_id,
        reason_codes=reason_codes,
        equivalence=equivalence,
        proposition=PHYSICAL_WALL_CANDIDATE_SCOPE_RESOLVED,
        scope_kind="page" if viewport is None else "viewport",
        viewport_id=None if viewport is None else str(viewport.view_id),
        viewport_bbox=viewport_bbox,
        viewport_view_type=None if viewport is None else str(viewport.view_type),
        viewport_status=None if viewport is None else str(viewport.status),
        viewport_boundary_source=None if viewport is None else str(viewport.boundary_source),
        viewport_producer_fingerprint=(
            None if viewport is None else segmented_viewport_producer_fingerprint(viewport)
        ),
        viewport_sibling_set_fingerprint=sibling_set_fingerprint,
        scope_boundary_observation_ids=tuple(
            sorted(dict.fromkeys(scope_boundary_observation_ids))
        ),
        ambiguous_source_observation_ids=tuple(
            sorted(dict.fromkeys(ambiguous_source_observation_ids))
        ),
        boundary_evaluation=boundary_evaluation,
        source_metadata_table=source_metadata_table,
        typed_semantic_evidence_atoms=typed_semantic_evidence_atoms,
    )


def _build_scope_result(
    *,
    source_producer: SourceVisibilityProducer,
    published,
    source_bytes: bytes,
    page_id: str,
    resolved_visible_observations: Optional[Sequence[tuple[str, object]]] = None,
    resolved_text_receipts: Optional[Sequence[object]] = None,
    physical_opening_authority: Optional[PhysicalOpeningAuthority] = None,
    physical_scale_producer: Optional[PhysicalScaleProducer] = None,
) -> PhysicalWallCandidateScopeResult:
    scope_id = _decision_scope_id(page_id)
    selector = PhysicalWallCandidateSelector(
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        page_id=page_id,
        decision_scope_id=scope_id,
    )
    page_number = int(page_id)
    # Page-wide wall authority is page-local. A scoped native ingestion hashes
    # and inventories the complete immutable PDF while decoding only the addressed
    # source pages, so coverage.state is intentionally "partial" for that mode.
    # Require this page itself to be decoded successfully; unrelated pages must
    # not block an otherwise authenticated page scope.
    if (
        page_number not in published.coverage.decoded_pages
        or page_number in published.coverage.failed_pages
    ):
        return _blocked(selector, PHYSICAL_WALL_CANDIDATE_SCOPE_UNAVAILABLE)

    try:
        segments, source_observation_ids, page_width, page_height = _source_page_segments(
            source_producer=source_producer,
            published=published,
            source_bytes=source_bytes,
            page_id=page_id,
            decision_scope_id=scope_id,
            resolved_visible_observations=resolved_visible_observations,
            resolved_text_receipts=resolved_text_receipts,
        )
    except WallPageFrameUnresolved:
        return _blocked(selector, PHYSICAL_WALL_CANDIDATE_PAGE_FRAME_UNRESOLVED)
    scale_producer = (
        physical_scale_producer
        if physical_scale_producer is not None
        else source_producer.physical_scale_producer()
    )
    points_per_mm = _producer_owned_points_per_mm(
        scale_producer=scale_producer,
        published=published,
        page_id=page_id,
    )
    return _assemble_scope_result(
        source_producer=source_producer,
        published=published,
        page_id=page_id,
        selector=selector,
        segments=segments,
        source_observation_ids=source_observation_ids,
        page_width=page_width,
        page_height=page_height,
        source_bytes=source_bytes,
        points_per_mm=points_per_mm,
        resolved_visible_observations=resolved_visible_observations,
        physical_opening_authority=physical_opening_authority,
    )


def _build_authenticated_viewport_scope_results(
    *,
    source_producer: SourceVisibilityProducer,
    published,
    source_bytes: bytes,
    page_id: str,
    resolved_visible_observations: Optional[Sequence[tuple[str, object]]] = None,
    resolved_text_receipts: Optional[Sequence[object]] = None,
    physical_opening_authority: Optional[PhysicalOpeningAuthority] = None,
    physical_scale_producer: Optional[PhysicalScaleProducer] = None,
) -> tuple[PhysicalWallCandidateScopeResult, ...]:
    page_number = int(page_id)
    # A viewport scope is page-local authority. A scoped native ingestion still
    # hashes the complete immutable PDF and inventories the document, while
    # fully decoding the addressed page. Do not require unrelated pages to be
    # decoded before proving this page's authenticated viewport universe.
    if (
        page_number not in published.coverage.decoded_pages
        or page_number in published.coverage.failed_pages
    ):
        return ()

    page_scope_id = _decision_scope_id(page_id)
    try:
        page_segments, _page_observation_ids, page_width, page_height = _source_page_segments(
            source_producer=source_producer,
            published=published,
            source_bytes=source_bytes,
            page_id=page_id,
            decision_scope_id=page_scope_id,
            resolved_visible_observations=resolved_visible_observations,
            resolved_text_receipts=resolved_text_receipts,
        )
    except WallPageFrameUnresolved:
        return ()
    viewport_cache_key = _page_viewports_cache_key(
        published=published,
        page_id=page_id,
    )
    viewport_cache = source_producer._physical_wall_page_viewports_cache
    if viewport_cache_key in viewport_cache:
        page_viewports = viewport_cache[viewport_cache_key]
    else:
        pdf = fitz.open(stream=source_bytes, filetype="pdf")
        try:
            page = pdf.load_page(page_number - 1)
            page_viewports = _all_viewports(page, page_number=page_number)
        finally:
            pdf.close()
        viewport_cache[viewport_cache_key] = (
            None
            if page_viewports is None
            else tuple(page_viewports)
        )

    authenticated = _authenticated_viewports_from_rows(page_viewports)
    if authenticated is None:
        return ()
    all_viewports, eligible = authenticated
    if not eligible:
        return ()
    sibling_fingerprint = _viewport_sibling_set_fingerprint(all_viewports)
    scale_producer = (
        physical_scale_producer
        if physical_scale_producer is not None
        else source_producer.physical_scale_producer()
    )

    results: list[PhysicalWallCandidateScopeResult] = []
    for viewport in eligible:
        assert viewport.bounding_box is not None
        scope_id = _viewport_decision_scope_id(
            published=published,
            page_id=page_id,
            viewport=viewport,
            sibling_set_fingerprint=sibling_fingerprint,
        )
        selector = PhysicalWallCandidateSelector(
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256=published.revision.source_sha256,
            snapshot_id=published.snapshot.snapshot_id,
            page_id=page_id,
            decision_scope_id=scope_id,
        )
        points_per_mm = _producer_owned_points_per_mm(
            scale_producer=scale_producer,
            published=published,
            page_id=page_id,
            viewport=viewport,
        )
        owned: list[dict] = []
        owned_observation_ids: list[str] = []
        boundary_observation_ids: list[str] = []
        ambiguous_observation_ids: list[str] = []
        pre_boundary_reasons: list[str] = []
        excluded_primitives: list[ExcludedBoundaryPrimitive] = []
        frame_edge_count = 0

        for segment in page_segments:
            observation_id = str(segment.get("source_observation_id") or "")
            owners = [
                other
                for other in eligible
                if other.bounding_box is not None
                and _segment_fully_inside_bbox(segment, other.bounding_box)
            ]
            target_owned = any(other.view_id == viewport.view_id for other in owners)
            structural, _exclude_reasons = is_structural_candidate_segment(segment)

            if target_owned and len(owners) == 1 and not _segment_lies_on_bbox_edge(
                segment, viewport.bounding_box
            ):
                scoped = dict(segment)
                scoped["viewport_id"] = scope_id
                owned.append(scoped)
                if observation_id:
                    owned_observation_ids.append(observation_id)
                continue

            if target_owned and _segment_is_authenticated_vector_frame_edge(
                segment, viewport=viewport
            ):
                # Exact F.07 vector-frame boundary evidence is not drawing
                # content. It is excluded by ownership provenance, not by
                # proximity to text or a project-specific semantic rule.
                frame_edge_count += 1
                continue

            if target_owned and (
                len(owners) > 1
                or _segment_lies_on_bbox_edge(segment, viewport.bounding_box)
            ):
                if structural:
                    pre_boundary_reasons.append(
                        PHYSICAL_WALL_CANDIDATE_SOURCE_PRIMITIVE_OWNERSHIP_AMBIGUOUS
                    )
                    if observation_id:
                        ambiguous_observation_ids.append(observation_id)
                    excluded_primitives.append(
                        _boundary_excluded_primitive(
                            segment,
                            BOUNDARY_PRIMITIVE_INSIDE_MULTIPLE_VIEWPORTS
                            if len(owners) > 1
                            else BOUNDARY_PRIMITIVE_LIES_ON_SCOPE_BOUNDARY_PARTIAL,
                        )
                    )
                continue

            if _segment_intersects_bbox(segment, viewport.bounding_box) and structural:
                pre_boundary_reasons.append(
                    PHYSICAL_WALL_CANDIDATE_SCOPE_CROPPED_AT_VIEWPORT_BOUNDARY
                )
                if observation_id:
                    boundary_observation_ids.append(observation_id)
                excluded_primitives.append(
                    _boundary_excluded_primitive(
                        segment, BOUNDARY_PRIMITIVE_CROSSES_SCOPE_BOUNDARY
                    )
                )

        results.append(
            _assemble_scope_result(
                source_producer=source_producer,
                published=published,
                page_id=page_id,
                selector=selector,
                segments=owned,
                source_observation_ids=owned_observation_ids,
                page_width=page_width,
                page_height=page_height,
                source_bytes=source_bytes,
                viewport=viewport,
                sibling_set_fingerprint=sibling_fingerprint,
                points_per_mm=points_per_mm,
                pre_boundary_reasons=pre_boundary_reasons,
                scope_boundary_observation_ids=boundary_observation_ids,
                ambiguous_source_observation_ids=ambiguous_observation_ids,
                resolved_visible_observations=resolved_visible_observations,
                physical_opening_authority=physical_opening_authority,
                excluded_boundary_primitives=tuple(excluded_primitives),
                authenticated_frame_edge_primitive_count=frame_edge_count,
            )
        )
    return tuple(results)


class PhysicalWallCandidateProducer:
    """Trusted writer derived only from an already-ingested visibility producer."""

    def __init__(self, scopes: Mapping[_ScopeKey, PhysicalWallCandidateScopeResult], *, _seal=None) -> None:
        if _seal is not _PRODUCER_SEAL:
            raise TypeError(
                "PhysicalWallCandidateProducer must be obtained from "
                "from_source_visibility_producer()"
            )
        self._scopes = MappingProxyType(dict(scopes))

    @classmethod
    def from_authenticated_viewports(
        cls,
        source_visibility_producer,
        *,
        page_ids: Optional[Sequence[str]] = None,
    ):
        """Build authenticated F.07 viewport scopes only.

        The legacy page-wide authority remains available through
        from_source_visibility_producer(). Keeping this constructor viewport-only
        avoids rebuilding the full page wall graph before resolving narrower
        authenticated drawing universes.

        Callers may address source pages only. Viewport geometry, membership,
        completeness, source primitives and wall candidates are resolved from
        the immutable source by this producer.
        """
        return cls._from_source_visibility_producer(
            source_visibility_producer,
            page_ids=page_ids,
            include_authenticated_viewports=True,
            include_page_scopes=False,
        )

    @classmethod
    def from_source_visibility_producer(
        cls,
        source_visibility_producer,
        *,
        page_ids: Optional[Sequence[str]] = None,
    ):
        return cls._from_source_visibility_producer(
            source_visibility_producer,
            page_ids=page_ids,
            include_authenticated_viewports=False,
            include_page_scopes=True,
        )

    @classmethod
    def _from_source_visibility_producer(
        cls,
        source_visibility_producer,
        *,
        page_ids: Optional[Sequence[str]],
        include_authenticated_viewports: bool,
        include_page_scopes: bool,
    ):
        """Build wall scopes, optionally narrowed by source page address.

        page_ids is addressing only: it can select which already-decoded source
        pages are materialized, but it cannot inject geometry, candidates,
        completeness, roles, quantities, or any other evidence-shaped input.
        The legacy no-argument behavior remains the complete decoded-page build.
        """
        if type(source_visibility_producer) is not SourceVisibilityProducer:
            raise TypeError(
                "source_visibility_producer must be an actual SourceVisibilityProducer"
            )

        selected_page_ids: Optional[set[str]] = None
        if page_ids is not None:
            selected_page_ids = {
                str(page_id).strip()
                for page_id in page_ids
                if str(page_id).strip()
            }
            if not selected_page_ids:
                raise ValueError("page_ids must contain at least one source page")

        # Preserve the current mainline raster-wall path while keeping page
        # addressing operationally narrow. Validate the requested source pages
        # against producer-owned decode coverage first, then render raster
        # fallback only for those pages. No caller pixels, segments, DPI,
        # thresholds, labels, or quantities enter this path.
        for revision_id in tuple(
            sorted(source_visibility_producer._published_by_revision)
        ):
            pre_augmented = source_visibility_producer._published_by_revision[
                revision_id
            ]
            decoded_page_ids = {
                str(int(page_number))
                for page_number in pre_augmented.coverage.decoded_pages
            }
            if (
                selected_page_ids is not None
                and not selected_page_ids <= decoded_page_ids
            ):
                raise ValueError(PHYSICAL_WALL_CANDIDATE_SCOPE_UNAVAILABLE)
            source_visibility_producer.augment_with_raster_visible_segments(
                revision_id,
                page_ids=(
                    tuple(
                        sorted(
                            selected_page_ids,
                            key=lambda value: int(value),
                        )
                    )
                    if selected_page_ids is not None
                    else None
                ),
            )

        published_by_revision = dict(source_visibility_producer._published_by_revision)
        store = source_visibility_producer._producer._store
        scopes: dict[_ScopeKey, PhysicalWallCandidateScopeResult] = {}

        for revision_id, published in sorted(published_by_revision.items()):
            if source_visibility_producer._producer.current_revision_id(
                published.revision.document_id
            ) != revision_id:
                continue
            source_bytes = store.source_bytes_by_revision.get(revision_id)
            if source_bytes is None:
                raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)
            digest = hashlib.sha256(source_bytes).hexdigest()
            if digest != published.revision.source_sha256:
                raise RuntimeError(PHYSICAL_WALL_CANDIDATE_SOURCE_INTEGRITY_FAILURE)

            decoded_page_ids = {
                str(int(page_number))
                for page_number in published.coverage.decoded_pages
            }
            if selected_page_ids is not None and not selected_page_ids <= decoded_page_ids:
                raise ValueError(PHYSICAL_WALL_CANDIDATE_SCOPE_UNAVAILABLE)
            materialized_page_ids = (
                sorted(selected_page_ids, key=lambda value: int(value))
                if selected_page_ids is not None
                else sorted(decoded_page_ids, key=lambda value: int(value))
            )
            visible_by_page = _visible_observations_by_page(
                source_producer=source_visibility_producer,
                published=published,
            )
            text_receipts_by_page = _text_receipts_by_page(
                source_producer=source_visibility_producer,
                published=published,
            )
            physical_opening_authority = (
                source_visibility_producer.physical_opening_authority()
            )
            physical_scale_producer = (
                source_visibility_producer.physical_scale_producer()
            )

            for page_id in materialized_page_ids:
                page_visible_observations = visible_by_page.get(page_id, ())
                if include_page_scopes:
                    result = _build_scope_result(
                        source_producer=source_visibility_producer,
                        published=published,
                        source_bytes=source_bytes,
                        page_id=page_id,
                        resolved_visible_observations=page_visible_observations,
                        resolved_text_receipts=text_receipts_by_page.get(page_id, ()),
                        physical_opening_authority=physical_opening_authority,
                        physical_scale_producer=physical_scale_producer,
                    )
                    key = _ScopeKey(
                        document_id=result.document_id,
                        revision_id=result.revision_id,
                        source_sha256=result.source_sha256,
                        snapshot_id=result.snapshot_id,
                        page_id=result.page_id,
                        decision_scope_id=result.decision_scope_id,
                    )
                    scopes[key] = result

                if include_authenticated_viewports:
                    for viewport_result in _build_authenticated_viewport_scope_results(
                        source_producer=source_visibility_producer,
                        published=published,
                        source_bytes=source_bytes,
                        page_id=page_id,
                        resolved_visible_observations=page_visible_observations,
                        resolved_text_receipts=text_receipts_by_page.get(page_id, ()),
                        physical_opening_authority=physical_opening_authority,
                        physical_scale_producer=physical_scale_producer,
                    ):
                        viewport_key = _ScopeKey(
                            document_id=viewport_result.document_id,
                            revision_id=viewport_result.revision_id,
                            source_sha256=viewport_result.source_sha256,
                            snapshot_id=viewport_result.snapshot_id,
                            page_id=viewport_result.page_id,
                            decision_scope_id=viewport_result.decision_scope_id,
                        )
                        scopes[viewport_key] = viewport_result

        return cls(scopes, _seal=_PRODUCER_SEAL)

    def authority(self):
        return PhysicalWallCandidateAuthority(self._scopes, _seal=_AUTHORITY_SEAL)


class PhysicalWallCandidateAuthority:
    """Read-only exact-scope resolver. Construction is producer-sealed."""

    def __init__(self, scopes: Mapping[_ScopeKey, PhysicalWallCandidateScopeResult], *, _seal=None) -> None:
        if _seal is not _AUTHORITY_SEAL:
            raise TypeError(
                "PhysicalWallCandidateAuthority must be obtained from "
                "PhysicalWallCandidateProducer.authority()"
            )
        self._scopes = MappingProxyType(dict(scopes))

    def resolve_scope(self, selector):
        if not isinstance(selector, PhysicalWallCandidateSelector):
            raise TypeError("selector must be PhysicalWallCandidateSelector")

        scope_id = str(selector.decision_scope_id)
        is_page_scope = scope_id == _decision_scope_id(selector.page_id)
        is_viewport_scope = scope_id.startswith(
            f"wall-source:viewport:{selector.page_id}:"
        )
        if not is_page_scope and not is_viewport_scope:
            return _blocked(selector, PHYSICAL_WALL_CANDIDATE_SCOPE_UNAVAILABLE)
        if is_viewport_scope:
            expected_fingerprint = _viewport_selector_payload_fingerprint(
                document_id=selector.document_id,
                revision_id=selector.revision_id,
                source_sha256=selector.source_sha256,
                snapshot_id=selector.snapshot_id,
                page_id=selector.page_id,
                decision_scope_id=selector.decision_scope_id,
            )
            seal = selector._viewport_selector_seal
            if (
                not isinstance(seal, tuple)
                or len(seal) != 2
                or seal[0] is not _VIEWPORT_SELECTOR_SEAL
                or seal[1] != expected_fingerprint
                or selector._viewport_selector_fingerprint != expected_fingerprint
            ):
                return _blocked(
                    selector,
                    PHYSICAL_WALL_CANDIDATE_VIEWPORT_AUTHORITY_INVALID,
                )

        key = _ScopeKey(
            document_id=str(selector.document_id),
            revision_id=str(selector.revision_id),
            source_sha256=str(selector.source_sha256),
            snapshot_id=str(selector.snapshot_id),
            page_id=str(selector.page_id),
            decision_scope_id=str(selector.decision_scope_id),
        )
        result = self._scopes.get(key)
        if result is None:
            return _blocked(selector, PHYSICAL_WALL_CANDIDATE_SCOPE_UNAVAILABLE)
        return result

    @staticmethod
    def _selector_for_result(
        result: PhysicalWallCandidateScopeResult,
    ) -> PhysicalWallCandidateSelector:
        if result.scope_kind != "viewport":
            return PhysicalWallCandidateSelector(
                document_id=result.document_id,
                revision_id=result.revision_id,
                source_sha256=result.source_sha256,
                snapshot_id=result.snapshot_id,
                page_id=result.page_id,
                decision_scope_id=result.decision_scope_id,
            )
        fingerprint = _viewport_selector_payload_fingerprint(
            document_id=result.document_id,
            revision_id=result.revision_id,
            source_sha256=result.source_sha256,
            snapshot_id=result.snapshot_id,
            page_id=result.page_id,
            decision_scope_id=result.decision_scope_id,
        )
        return PhysicalWallCandidateSelector(
            document_id=result.document_id,
            revision_id=result.revision_id,
            source_sha256=result.source_sha256,
            snapshot_id=result.snapshot_id,
            page_id=result.page_id,
            decision_scope_id=result.decision_scope_id,
            _viewport_selector_fingerprint=fingerprint,
            _viewport_selector_seal=(_VIEWPORT_SELECTOR_SEAL, fingerprint),
        )

    def selector_for_viewport(
        self,
        *,
        document_id: str,
        revision_id: str,
        source_sha256: str,
        snapshot_id: str,
        page_id: str,
        viewport_id: str,
    ) -> Optional[PhysicalWallCandidateSelector]:
        """Return a sealed address only for a materialized authenticated viewport."""
        matches = [
            result
            for result in self._scopes.values()
            if result.scope_kind == "viewport"
            and result.document_id == str(document_id)
            and result.revision_id == str(revision_id)
            and result.source_sha256 == str(source_sha256)
            and result.snapshot_id == str(snapshot_id)
            and result.page_id == str(page_id)
            and result.viewport_id == str(viewport_id)
        ]
        if len(matches) != 1:
            return None
        return self._selector_for_result(matches[0])

    def selectors_for_authenticated_viewports(
        self,
        *,
        document_id: str,
        revision_id: str,
        source_sha256: str,
        snapshot_id: str,
        page_id: str,
        view_type: Optional[str] = None,
    ) -> tuple[PhysicalWallCandidateSelector, ...]:
        """Return sealed selectors for producer-materialized viewport scopes.

        This is addressing only. It cannot create viewport geometry, change
        scope completeness, or promote a wall result. Optional view_type merely
        filters the producer-owned viewport classification already sealed into
        each scope.
        """

        expected_view_type = None if view_type is None else str(view_type)
        matches = [
            result
            for result in self._scopes.values()
            if result.scope_kind == "viewport"
            and result.document_id == str(document_id)
            and result.revision_id == str(revision_id)
            and result.source_sha256 == str(source_sha256)
            and result.snapshot_id == str(snapshot_id)
            and result.page_id == str(page_id)
            and (
                expected_view_type is None
                or result.viewport_view_type == expected_view_type
            )
        ]
        matches.sort(
            key=lambda result: (
                str(result.viewport_id or ""),
                str(result.decision_scope_id),
            )
        )
        return tuple(self._selector_for_result(result) for result in matches)

    def selector_for_decision_scope(
        self,
        *,
        document_id: str,
        revision_id: str,
        source_sha256: str,
        snapshot_id: str,
        page_id: str,
        decision_scope_id: str,
    ) -> Optional[PhysicalWallCandidateSelector]:
        """Reissue a valid selector only for an exact producer-owned scope."""
        key = _ScopeKey(
            document_id=str(document_id),
            revision_id=str(revision_id),
            source_sha256=str(source_sha256),
            snapshot_id=str(snapshot_id),
            page_id=str(page_id),
            decision_scope_id=str(decision_scope_id),
        )
        result = self._scopes.get(key)
        if result is None:
            return None
        return self._selector_for_result(result)


__all__ = [
    "PHYSICAL_WALL_CANDIDATE_AUTHORITY_SCHEMA_VERSION",
    "PHYSICAL_WALL_CANDIDATE_PAGE_FRAME_UNRESOLVED",
    "PHYSICAL_WALL_CANDIDATE_SCOPE_BOUNDS_UNRESOLVED",
    "BOUNDARY_EVALUATION_EVALUATED",
    "BOUNDARY_EVALUATION_UNAVAILABLE",
    "BOUNDARY_PRIMITIVE_CROSSES_SCOPE_BOUNDARY",
    "BOUNDARY_PRIMITIVE_INSIDE_MULTIPLE_VIEWPORTS",
    "BOUNDARY_PRIMITIVE_LIES_ON_SCOPE_BOUNDARY_PARTIAL",
    "ExcludedBoundaryPrimitive",
    "PHYSICAL_WALL_CANDIDATE_BOUNDARY_GEOMETRY_NOT_EVALUABLE",
    "PHYSICAL_WALL_CANDIDATE_TOUCHES_EXCLUDED_BOUNDARY_PRIMITIVE",
    "PhysicalWallScopeBoundaryEvaluation",
    "PHYSICAL_WALL_CANDIDATE_SCOPE_CROPPED_AT_PAGE_BOUNDARY",
    "PHYSICAL_WALL_CANDIDATE_SCOPE_CROPPED_AT_VIEWPORT_BOUNDARY",
    "PHYSICAL_WALL_CANDIDATE_SCOPE_RESOLVED",
    "PHYSICAL_WALL_CANDIDATE_SCOPE_UNAVAILABLE",
    "PHYSICAL_WALL_CANDIDATE_SOURCE_PRIMITIVE_OWNERSHIP_AMBIGUOUS",
    "PHYSICAL_WALL_CANDIDATE_VIEWPORT_AUTHORITY_INVALID",
    "PHYSICAL_WALL_CANDIDATE_VIEWPORT_LINEAGE_MISMATCH",
    "WallPageFrameUnresolved",
    "native_wall_scope_page_extent",
    "PhysicalWallCandidateAuthority",
    "PhysicalWallCandidateProducer",
    "PhysicalWallCandidateRecord",
    "PhysicalWallSourceEdgeFragment",
    "PhysicalWallSnapCollapsedFragment",
    "PhysicalWallCandidateScopeResult",
    "PhysicalWallCandidateSelector",
]
