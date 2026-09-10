"""Wall/room/junction/opening-host candidate contracts (W1).

Implements the schemas from ``docs/planreader_wall_room_topology_spec.md`` sections
5, 7, 8.1 and 13. This module defines data only -- no PDF extraction, no geometry
reconstruction, no benchmark evaluation. Extraction/geometry code (W2 onward) will
construct these records; nothing in this module reads a PDF or a benchmark file.

These contracts deliberately reuse rather than duplicate two things that already
exist and are already load-bearing elsewhere in this codebase:

- ``EvidenceResolutionStatus`` from ``pb_migration_contracts`` is the one fusion-
  status vocabulary for this whole migration (RAW/CANDIDATE/CORROBORATED/CONFLICT/
  ABSTAINED). The topology spec's own draft six-state ``FusionStatus`` sketch is
  folded into this real, already-merged enum rather than shipped as a second,
  competing status vocabulary: AMBIGUOUS candidates are represented as CANDIDATE
  with an explanatory reason code (see ``REASON_AMBIGUOUS``), and SUPPORTED
  candidates are CANDIDATE with a single corroborating evidence id -- the
  CANDIDATE/CORROBORATED boundary is exactly "how many independent sources agree",
  which is what these enum members already mean.
- ``MeasurementAuthorityType`` from ``pb_geometry_takeoff_model`` is the one
  authority ladder for every metre-space field below. No wall/room/opening field
  in this module may be populated above ``PROVISIONAL`` without a corresponding
  authority tier from that existing enum.

No entity in this module is ever promoted to ``pb_canonical_building``'s schema
directly by this file -- promotion (W12) is a separate, later stage gated on
``EvidenceResolutionStatus.CORROBORATED`` (see the topology spec's Section 14).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Literal, Mapping, Optional, Tuple

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_migration_contracts import EvidenceResolutionStatus

TOPOLOGY_CONTRACT_SCHEMA_VERSION = "1.0.0"

# Reason codes used across this module. Kept as named constants (not free-form
# strings scattered through call sites) so a reason code cannot silently drift
# between what this module emits and what a test or downstream reader expects.
REASON_AMBIGUOUS = "ambiguous_within_margin"
REASON_SHORT_RETURN = "short_return"
REASON_COLLINEAR_MERGE_APPLIED = "collinear_merge_applied"
REASON_THICKNESS_UNRESOLVED = "thickness_unresolved"
REASON_GAP_BELOW_MIN_WALL_WIDTH = "gap_below_min_wall_width"
REASON_RASTER_SOURCE = "raster_source"
REASON_NO_PLAUSIBLE_HOST = "no_plausible_host"


class JunctionType(str, Enum):
    """Deterministic wall-junction classification (topology spec Section 7, extended W3).

    ENDPOINT/L_CORNER/T_JUNCTION/X_CROSSING/UNRESOLVED are the original W1 members,
    unchanged in meaning. W3 adds:

    - COLLINEAR_CONTINUATION: a degree-2 node whose two incident edges are collinear
      -- normally already collapsed away by W2's ``merge_collinear_degree_two_nodes``,
      classified here only for observability when one reaches the classifier anyway
      (e.g. a caller that ran classification without first running that merge pass).
    - MULTI_WAY: five or more incident edges that pair up cleanly into collinear
      through-pairs with no leftover arm -- the same underlying pattern as
      X_CROSSING, generalized beyond four arms.
    - NEAR_JUNCTION_REVIEW: two distinct (unmerged) graph nodes closer together than
      a review band above the snap tolerance -- a possible near-miss fragmentation
      that Stage A's endpoint-snap tolerance did not bridge, flagged for human/
      richer-evidence review rather than silently left as two disconnected walls.
    - AMBIGUOUS: a node whose incident-edge pattern is partially, but not cleanly,
      structural (e.g. a through-pair plus unexplained extra arms), or whose base
      classification carries a suspiciously short, dead-end arm that could equally
      be a real short wall return or an unrelated line merely touching a wall.
    - REJECTED_NON_WALL_CROSSING: a geometric crossing between a real structural
      edge and a segment Stage A's pre-filter already excluded (hatch, dimension,
      or annotation-layer/dash convention) -- recorded explicitly so the rejection
      is visible and auditable, not merely a silent absence of a junction.
    """

    ENDPOINT = "endpoint"
    L_CORNER = "l_corner"
    T_JUNCTION = "t_junction"
    X_CROSSING = "x_crossing"
    UNRESOLVED = "unresolved"
    COLLINEAR_CONTINUATION = "collinear_continuation"
    MULTI_WAY = "multi_way"
    NEAR_JUNCTION_REVIEW = "near_junction_review"
    AMBIGUOUS = "ambiguous"
    REJECTED_NON_WALL_CROSSING = "rejected_non_wall_crossing"


# Junction types for which incident_wall_candidate_ids may legitimately be empty
# (there is no "at least one incident wall" to reference: UNRESOLVED can arise from
# a degenerate/irregular node with no clean interpretation at all, and
# NEAR_JUNCTION_REVIEW describes a *pair* of nodes rather than one node's incident
# edges -- its own incident edges are reported normally, but a review record may be
# emitted for a bare degree-0/1 node with nothing else to reference yet).
_JUNCTION_TYPES_ALLOWING_EMPTY_INCIDENT_IDS = frozenset({JunctionType.UNRESOLVED})


WallRepresentation = Literal["single_line", "double_line", "curved"]
InteriorExterior = Literal["interior", "exterior", "unresolved"]
OpeningHostStatus = Literal["hosted", "ambiguous_host", "unhosted"]


def _require_nonempty(value: str, field_name: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{field_name} must be a non-empty string")
    return clean


def _require_confidence(value: float, field_name: str = "confidence") -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{field_name} must be finite and within [0, 1]")
    return numeric


def _require_finite_nonnegative(value: Optional[float], field_name: str) -> Optional[float]:
    if value is None:
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0:
        raise ValueError(f"{field_name} must be finite and non-negative when supplied")
    return numeric


def _require_point_sequence(
    points: Tuple[Tuple[float, float], ...], field_name: str, *, min_points: int = 2
) -> Tuple[Tuple[float, float], ...]:
    if len(points) < min_points:
        raise ValueError(f"{field_name} must contain at least {min_points} points")
    cleaned = []
    for point in points:
        if len(point) != 2:
            raise ValueError(f"{field_name} entries must be (x, y) pairs")
        x, y = float(point[0]), float(point[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"{field_name} coordinates must be finite")
        cleaned.append((x, y))
    return tuple(cleaned)


def _require_unique(ids: Tuple[str, ...], field_name: str) -> Tuple[str, ...]:
    if len(set(ids)) != len(ids):
        raise ValueError(f"{field_name} must be unique")
    return ids


def _require_authority_not_above_provisional_without_tier(
    authority: MeasurementAuthorityType,
    status: EvidenceResolutionStatus,
) -> None:
    """A PROVISIONAL/assumed authority can never carry CORROBORATED status.

    This is the direct enforcement of the topology spec's Section 6/10 rule that
    a default or assumed value never becomes a firm measurement merely because
    its surrounding geometric evidence agrees well.
    """
    if authority == MeasurementAuthorityType.PROVISIONAL and status == EvidenceResolutionStatus.CORROBORATED:
        raise ValueError(
            "a PROVISIONAL measurement authority can never back a CORROBORATED entity"
        )


@dataclass(frozen=True)
class JunctionCandidate:
    """A classified (or explicitly unresolved/rejected) wall-graph junction.

    Corresponds to ``pb_vector_geometry_v130.snap_geometry``'s node output
    (as prepared by W2's ``pb_wall_room_topology_stage_a``), classified by W3's
    junction classifier. This dataclass does not itself classify anything -- it
    is the record shape the classifier writes.

    ``incident_wall_candidate_ids`` currently references **Stage-A edge ids**,
    not ``WallCandidate.candidate_id`` values -- wall-candidate assembly (W4)
    happens *after* junction classification (W3) in this workstream's own
    roadmap, so no ``WallCandidate`` exists yet at the point this dataclass is
    populated. A future W4 pass is expected to re-key these to real
    ``WallCandidate`` ids once wall-candidate assembly exists (each Stage-A
    edge is expected to become approximately one wall candidate, modulo
    further collapsing W4 may apply) -- this is a deliberate, documented
    sequencing choice, not an oversight.
    """

    node_id: str
    document_id: str
    page_id: str
    viewport_id: str
    position_pt: Tuple[float, float]
    junction_type: JunctionType
    incident_wall_candidate_ids: Tuple[str, ...]
    incident_angles_deg: Tuple[float, ...]
    status: EvidenceResolutionStatus
    confidence: float
    evidence_ids: Tuple[str, ...] = ()
    conflict_evidence_ids: Tuple[str, ...] = ()
    reason_codes: Tuple[str, ...] = ()
    schema_version: str = TOPOLOGY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.node_id, "node_id")
        _require_nonempty(self.document_id, "document_id")
        _require_nonempty(self.page_id, "page_id")
        _require_nonempty(self.viewport_id, "viewport_id")
        _require_point_sequence((self.position_pt,), "position_pt", min_points=1)
        _require_confidence(self.confidence)
        if len(self.incident_wall_candidate_ids) != len(self.incident_angles_deg):
            raise ValueError(
                "incident_wall_candidate_ids and incident_angles_deg must have equal length"
            )
        _require_unique(self.incident_wall_candidate_ids, "incident_wall_candidate_ids")
        _require_unique(self.evidence_ids, "evidence_ids")
        _require_unique(self.conflict_evidence_ids, "conflict_evidence_ids")
        if (
            self.junction_type not in _JUNCTION_TYPES_ALLOWING_EMPTY_INCIDENT_IDS
            and not self.incident_wall_candidate_ids
        ):
            raise ValueError(
                f"junction_type={self.junction_type.value!r} must reference at least one "
                "incident wall/segment id"
            )
        if self.status == EvidenceResolutionStatus.CONFLICT and not self.conflict_evidence_ids:
            raise ValueError("CONFLICT status requires conflict_evidence_ids")
        if self.status == EvidenceResolutionStatus.CORROBORATED and self.conflict_evidence_ids:
            raise ValueError("a CORROBORATED junction cannot retain unresolved conflicts")

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "document_id": self.document_id,
            "page_id": self.page_id,
            "viewport_id": self.viewport_id,
            "position_pt": list(self.position_pt),
            "junction_type": self.junction_type.value,
            "incident_wall_candidate_ids": list(self.incident_wall_candidate_ids),
            "incident_angles_deg": list(self.incident_angles_deg),
            "status": self.status.value,
            "confidence": self.confidence,
            "evidence_ids": list(self.evidence_ids),
            "conflict_evidence_ids": list(self.conflict_evidence_ids),
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
        }


class TopologyRelationshipType(str, Enum):
    """Deterministic peer relationships between wall-segment candidates (W3).

    Nothing in ``pb_migration_contracts`` or ``pb_canonical_building`` already
    models this: ``pb_canonical_building``'s ``parent_id``/``children_ids`` are
    a hierarchical (containment) relationship, not a topological peer
    relationship between two same-level wall segments meeting at a junction --
    so this is new, not a duplicate of an existing relationship system.
    """

    CONNECTED_TO = "connected_to"
    CONTINUES_AS = "continues_as"
    TERMINATES_AT = "terminates_at"
    INTERSECTS = "intersects"
    BRANCHES_FROM = "branches_from"


@dataclass(frozen=True)
class TopologyRelationship:
    """One deterministic edge-to-edge relationship produced at a junction.

    ``to_edge_id`` is ``None`` only for ``TERMINATES_AT`` (an edge ending at a
    degree-1 node has no "other" edge to relate to at that node).
    """

    relationship_id: str
    from_edge_id: str
    to_edge_id: Optional[str]
    relationship_type: TopologyRelationshipType
    via_junction_id: str
    confidence: float
    reason_codes: Tuple[str, ...] = ()
    schema_version: str = TOPOLOGY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.relationship_id, "relationship_id")
        _require_nonempty(self.from_edge_id, "from_edge_id")
        _require_nonempty(self.via_junction_id, "via_junction_id")
        _require_confidence(self.confidence)
        if self.relationship_type == TopologyRelationshipType.TERMINATES_AT:
            if self.to_edge_id is not None:
                raise ValueError("TERMINATES_AT must not carry a to_edge_id")
        else:
            if not self.to_edge_id:
                raise ValueError(f"{self.relationship_type.value} requires a to_edge_id")
            if self.to_edge_id == self.from_edge_id:
                raise ValueError("an edge cannot relate to itself")

    def to_dict(self) -> dict:
        return {
            "relationship_id": self.relationship_id,
            "from_edge_id": self.from_edge_id,
            "to_edge_id": self.to_edge_id,
            "relationship_type": self.relationship_type.value,
            "via_junction_id": self.via_junction_id,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class WallCandidate:
    """A candidate physical wall segment before canonical promotion.

    See ``docs/planreader_wall_room_topology_spec.md`` Section 5. Every metre-
    space field (``thickness_m``, ``length_m``) is ``None`` until a scale
    authority (``pb_page_scale_calibration_authority``) resolves for this
    candidate's viewport -- this dataclass never invents a default.
    """

    candidate_id: str
    viewport_id: str
    representation: WallRepresentation

    centerline_pts: Tuple[Tuple[float, float], ...]
    face_a_segment_ids: Tuple[str, ...]
    face_b_segment_ids: Optional[Tuple[str, ...]]
    is_curved: bool
    curve_control_pts: Optional[Tuple[Tuple[float, float], ...]]

    thickness_m: Optional[float]
    thickness_authority: MeasurementAuthorityType
    length_m: Optional[float]

    end_node_ids: Tuple[str, str]
    junction_types: Tuple[JunctionType, JunctionType]

    interior_exterior: InteriorExterior
    level_id: Optional[str]

    embedded_columns: Tuple[str, ...] = ()

    status: EvidenceResolutionStatus = EvidenceResolutionStatus.CANDIDATE
    confidence: float = 0.0
    supporting_evidence_ids: Tuple[str, ...] = ()
    conflicting_evidence_ids: Tuple[str, ...] = ()
    reason_codes: Tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = TOPOLOGY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.candidate_id, "candidate_id")
        _require_nonempty(self.viewport_id, "viewport_id")
        object.__setattr__(
            self, "centerline_pts", _require_point_sequence(self.centerline_pts, "centerline_pts")
        )
        _require_unique(self.face_a_segment_ids, "face_a_segment_ids")
        if not self.face_a_segment_ids:
            raise ValueError("face_a_segment_ids must reference at least one source segment")
        if self.representation == "double_line" and not self.face_b_segment_ids:
            raise ValueError("a double_line wall candidate requires face_b_segment_ids")
        if self.representation != "double_line" and self.face_b_segment_ids:
            raise ValueError("only a double_line wall candidate may carry face_b_segment_ids")
        if self.face_b_segment_ids is not None:
            _require_unique(self.face_b_segment_ids, "face_b_segment_ids")
        if self.is_curved and self.representation != "curved":
            raise ValueError("is_curved=True requires representation='curved'")
        if self.representation == "curved" and not self.is_curved:
            raise ValueError("representation='curved' requires is_curved=True")
        if self.is_curved and not self.curve_control_pts:
            raise ValueError("a curved wall candidate requires curve_control_pts")
        if not self.is_curved and self.curve_control_pts:
            raise ValueError("curve_control_pts is only valid when is_curved=True")
        if self.curve_control_pts is not None:
            object.__setattr__(
                self,
                "curve_control_pts",
                _require_point_sequence(self.curve_control_pts, "curve_control_pts", min_points=3),
            )

        object.__setattr__(
            self, "thickness_m", _require_finite_nonnegative(self.thickness_m, "thickness_m")
        )
        object.__setattr__(self, "length_m", _require_finite_nonnegative(self.length_m, "length_m"))
        if self.thickness_m is None and self.thickness_authority not in (
            MeasurementAuthorityType.PROVISIONAL,
            MeasurementAuthorityType.EXCLUDED,
        ):
            raise ValueError(
                "an unresolved thickness_m must carry a PROVISIONAL or EXCLUDED thickness_authority"
            )

        if len(self.end_node_ids) != 2 or len(self.junction_types) != 2:
            raise ValueError("end_node_ids and junction_types must each contain exactly two entries")
        if self.end_node_ids[0] == self.end_node_ids[1]:
            raise ValueError("a wall candidate cannot start and end at the same node")

        _require_unique(self.embedded_columns, "embedded_columns")
        _require_confidence(self.confidence)
        _require_unique(self.supporting_evidence_ids, "supporting_evidence_ids")
        _require_unique(self.conflicting_evidence_ids, "conflicting_evidence_ids")
        _require_authority_not_above_provisional_without_tier(self.thickness_authority, self.status)

        if self.status == EvidenceResolutionStatus.CORROBORATED and self.confidence <= 0.0:
            raise ValueError("a CORROBORATED wall candidate must carry a positive confidence")
        if self.status == EvidenceResolutionStatus.CONFLICT and not self.conflicting_evidence_ids:
            raise ValueError("CONFLICT status requires conflicting_evidence_ids")
        if self.status == EvidenceResolutionStatus.CORROBORATED and self.conflicting_evidence_ids:
            raise ValueError("a CORROBORATED wall candidate cannot retain unresolved conflicts")

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "viewport_id": self.viewport_id,
            "representation": self.representation,
            "centerline_pts": [list(p) for p in self.centerline_pts],
            "face_a_segment_ids": list(self.face_a_segment_ids),
            "face_b_segment_ids": list(self.face_b_segment_ids) if self.face_b_segment_ids else None,
            "is_curved": self.is_curved,
            "curve_control_pts": (
                [list(p) for p in self.curve_control_pts] if self.curve_control_pts else None
            ),
            "thickness_m": self.thickness_m,
            "thickness_authority": self.thickness_authority.value,
            "length_m": self.length_m,
            "end_node_ids": list(self.end_node_ids),
            "junction_types": [jt.value for jt in self.junction_types],
            "interior_exterior": self.interior_exterior,
            "level_id": self.level_id,
            "embedded_columns": list(self.embedded_columns),
            "status": self.status.value,
            "confidence": self.confidence,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "conflicting_evidence_ids": list(self.conflicting_evidence_ids),
            "reason_codes": list(self.reason_codes),
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class RoomCandidate:
    """A candidate physical room/space polygon before canonical promotion.

    Extends (does not replace) ``pb_room_face_takeoff.RoomFace`` -- every field
    of that dataclass is reproduced here unchanged in meaning, plus the new
    topology-provenance fields from the spec's Section 8.1.
    """

    # --- fields carried over from pb_room_face_takeoff.RoomFace, unchanged semantics ---
    room_ref: str
    label: str
    polygon_pdf_pts: Tuple[Tuple[float, float], ...]
    polygon_m: Optional[Tuple[Tuple[float, float], ...]]
    floor_area_m2: Optional[float]
    area_page_pts2: float
    perimeter_m: Optional[float]
    geometry_confidence: float
    evidence: Tuple[str, ...]
    source_page: int
    drawing_number: str
    scale_source: str
    calibration_confidence: float
    has_voids: bool

    # --- provenance fields added in W5: the original W1 schema had no
    # document/viewport ownership at all (only the bare `source_page` int
    # inherited from RoomFace) -- added here, matching the same
    # document_id/viewport_id convention already established on
    # WallCandidate/JunctionCandidate, rather than leaving RoomCandidate as
    # the one contract in this family without it. ---
    document_id: str
    viewport_id: str

    # `status` also migrated from a bare, RoomFace-inherited free-text string
    # ("Measured"/"Provisional measured"/"Review") to the one
    # EvidenceResolutionStatus enum already used by WallCandidate and
    # JunctionCandidate -- RoomCandidate was new and unused anywhere else
    # before W5, so this is a safe, one-time consistency correction, not a
    # breaking change to any real consumer; a second status vocabulary
    # living on just this one contract would itself have been the kind of
    # duplicate system this whole workstream is instructed to avoid.
    status: EvidenceResolutionStatus

    # --- new topology fields ---
    bounding_wall_candidate_ids: Tuple[str, ...] = ()
    adjacent_room_refs: Tuple[str, ...] = ()
    opening_refs: Tuple[str, ...] = ()
    exterior_boundary: bool = False
    explicit_area_label_m2: Optional[float] = None
    area_conflict: Optional[Mapping[str, float]] = None
    level_id: Optional[str] = None
    building_component_id: str = ""
    # Added in W5 alongside the provenance/status fields above -- RoomCandidate
    # was the only contract in this family with no reason-code channel at all,
    # despite the whole workstream's convention of never leaving a
    # non-CANDIDATE status unexplained.
    reason_codes: Tuple[str, ...] = ()
    schema_version: str = TOPOLOGY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.room_ref, "room_ref")
        _require_nonempty(self.document_id, "document_id")
        _require_nonempty(self.viewport_id, "viewport_id")
        object.__setattr__(
            self,
            "polygon_pdf_pts",
            _require_point_sequence(self.polygon_pdf_pts, "polygon_pdf_pts", min_points=3),
        )
        if self.polygon_m is not None:
            object.__setattr__(
                self, "polygon_m", _require_point_sequence(self.polygon_m, "polygon_m", min_points=3)
            )
        object.__setattr__(
            self, "area_page_pts2", _require_finite_nonnegative(self.area_page_pts2, "area_page_pts2")
        )
        object.__setattr__(
            self, "floor_area_m2", _require_finite_nonnegative(self.floor_area_m2, "floor_area_m2")
        )
        object.__setattr__(
            self, "perimeter_m", _require_finite_nonnegative(self.perimeter_m, "perimeter_m")
        )
        _require_confidence(self.geometry_confidence, "geometry_confidence")
        _require_confidence(self.calibration_confidence, "calibration_confidence")
        _require_unique(self.bounding_wall_candidate_ids, "bounding_wall_candidate_ids")
        _require_unique(self.adjacent_room_refs, "adjacent_room_refs")
        if self.room_ref in self.adjacent_room_refs:
            raise ValueError("a room cannot be adjacent to itself")
        _require_unique(self.opening_refs, "opening_refs")
        object.__setattr__(
            self,
            "explicit_area_label_m2",
            _require_finite_nonnegative(self.explicit_area_label_m2, "explicit_area_label_m2"),
        )
        if self.area_conflict is not None:
            required_keys = {"polygon_area_m2", "explicit_area_m2"}
            if set(self.area_conflict.keys()) != required_keys:
                raise ValueError(
                    "area_conflict must contain exactly 'polygon_area_m2' and 'explicit_area_m2'"
                )
            for key in required_keys:
                value = float(self.area_conflict[key])
                if not math.isfinite(value) or value < 0.0:
                    raise ValueError(f"area_conflict['{key}'] must be finite and non-negative")
        if self.status == EvidenceResolutionStatus.CONFLICT:
            raise ValueError(
                "RoomCandidate has no conflict_evidence_ids field yet -- CONFLICT status is "
                "not usable until a future stage adds one; use ABSTAINED for now"
            )

    def to_dict(self) -> dict:
        return {
            "room_ref": self.room_ref,
            "document_id": self.document_id,
            "viewport_id": self.viewport_id,
            "label": self.label,
            "polygon_pdf_pts": [list(p) for p in self.polygon_pdf_pts],
            "polygon_m": [list(p) for p in self.polygon_m] if self.polygon_m else None,
            "floor_area_m2": self.floor_area_m2,
            "area_page_pts2": self.area_page_pts2,
            "perimeter_m": self.perimeter_m,
            "geometry_confidence": self.geometry_confidence,
            "evidence": list(self.evidence),
            "source_page": self.source_page,
            "drawing_number": self.drawing_number,
            "scale_source": self.scale_source,
            "calibration_confidence": self.calibration_confidence,
            "has_voids": self.has_voids,
            "status": self.status.value,
            "bounding_wall_candidate_ids": list(self.bounding_wall_candidate_ids),
            "adjacent_room_refs": list(self.adjacent_room_refs),
            "opening_refs": list(self.opening_refs),
            "exterior_boundary": self.exterior_boundary,
            "explicit_area_label_m2": self.explicit_area_label_m2,
            "area_conflict": dict(self.area_conflict) if self.area_conflict else None,
            "level_id": self.level_id,
            "building_component_id": self.building_component_id,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class OpeningHostCandidate:
    """A wall-line gap and its (possibly ambiguous, possibly absent) wall host.

    See spec Section 13. This dataclass never assigns a schedule tag, a door/
    window classification, or a deduction -- those remain Cursor's and
    ``pb_opening_deduction_pipeline``'s responsibilities respectively. This is
    strictly "where is a gap, and which wall(s) could plausibly host it."
    """

    host_candidate_id: str
    wall_candidate_id: str
    position_along_wall_m: Optional[float]
    gap_width_m: Optional[float]
    host_status: OpeningHostStatus
    candidate_wall_ids_considered: Tuple[str, ...]
    confidence: float
    reason_codes: Tuple[str, ...] = ()
    schema_version: str = TOPOLOGY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.host_candidate_id, "host_candidate_id")
        _require_nonempty(self.wall_candidate_id, "wall_candidate_id")
        object.__setattr__(
            self,
            "position_along_wall_m",
            _require_finite_nonnegative(self.position_along_wall_m, "position_along_wall_m"),
        )
        object.__setattr__(
            self, "gap_width_m", _require_finite_nonnegative(self.gap_width_m, "gap_width_m")
        )
        _require_confidence(self.confidence)
        _require_unique(self.candidate_wall_ids_considered, "candidate_wall_ids_considered")

        if self.host_status == "hosted":
            if self.wall_candidate_id not in self.candidate_wall_ids_considered:
                raise ValueError(
                    "a hosted opening's wall_candidate_id must appear in candidate_wall_ids_considered"
                )
            if len(self.candidate_wall_ids_considered) != 1:
                raise ValueError(
                    "host_status='hosted' requires exactly one considered wall candidate "
                    "-- two or more plausible hosts is 'ambiguous_host', not 'hosted'"
                )
        elif self.host_status == "ambiguous_host":
            if len(self.candidate_wall_ids_considered) < 2:
                raise ValueError(
                    "host_status='ambiguous_host' requires at least two considered wall candidates"
                )
            if not self.reason_codes:
                raise ValueError("host_status='ambiguous_host' requires at least one reason code")
        elif self.host_status == "unhosted":
            if self.candidate_wall_ids_considered:
                raise ValueError("host_status='unhosted' must not carry considered wall candidates")
            if REASON_NO_PLAUSIBLE_HOST not in self.reason_codes:
                raise ValueError(
                    f"host_status='unhosted' requires the '{REASON_NO_PLAUSIBLE_HOST}' reason code"
                )
        else:
            raise ValueError(f"unknown host_status: {self.host_status!r}")

    def to_dict(self) -> dict:
        return {
            "host_candidate_id": self.host_candidate_id,
            "wall_candidate_id": self.wall_candidate_id,
            "position_along_wall_m": self.position_along_wall_m,
            "gap_width_m": self.gap_width_m,
            "host_status": self.host_status,
            "candidate_wall_ids_considered": list(self.candidate_wall_ids_considered),
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
        }
