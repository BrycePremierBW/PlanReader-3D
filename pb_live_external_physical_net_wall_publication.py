"""Physical external net-wall publication from source-owned geometry.

This path is intentionally separate from trade/finish opening-deduction policy.
For structural/perimeter wall quantity, every authenticated physical opening void
in a complete source opening universe is geometric absence from its authenticated
host whole wall. No ODTARGET/ODRULE declaration is required or accepted here.

The function accepts only producer-owned compositions. It replays gross wall and
whole-wall role authorities, replays every physical opening void, proves complete
opening coverage, maps voids to canonical whole-wall frame identities, and then
subtracts the exact union of wall-local void rectangles from each authenticated
EXTERNAL gross wall.

No caller-supplied wall list, role, area, opening count, deduction decision,
benchmark expectation, or fallback enters the numeric path.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional

from shapely.geometry import box

from pb_live_gross_wall_geometry_composition import LiveGrossWallGeometryComposition
from pb_live_physical_opening_void_composition import LivePhysicalOpeningVoidComposition
from pb_live_wall_opening_authority_composition import LiveWallOpeningAuthorityComposition
from pb_live_whole_wall_role_composition import LiveWholeWallRoleComposition
from pb_migration_contracts import EvidenceResolutionStatus, QuantityEvidence, stable_contract_id
from pb_net_wall_boolean_union_authority import subtract_void_union_from_wall_polygon
from pb_wall_role_authority import WallRoleClassification


LIVE_EXTERNAL_PHYSICAL_NET_WALL_SCHEMA_VERSION = "1.1.0"

LIVE_EXTERNAL_PHYSICAL_NET_WALL_RESOLVED = (
    "live_external_physical_net_wall_publication_resolved"
)
LIVE_EXTERNAL_PHYSICAL_NET_WALL_UPSTREAM_INCOMPLETE = (
    "live_external_physical_net_wall_publication_upstream_incomplete"
)
LIVE_EXTERNAL_PHYSICAL_NET_WALL_LINEAGE_MISMATCH = (
    "live_external_physical_net_wall_publication_lineage_mismatch"
)
LIVE_EXTERNAL_PHYSICAL_NET_WALL_VOID_UNRESOLVED = (
    "live_external_physical_net_wall_publication_void_unresolved"
)
LIVE_EXTERNAL_PHYSICAL_NET_WALL_ROLE_UNRESOLVED = (
    "live_external_physical_net_wall_publication_role_unresolved"
)
LIVE_EXTERNAL_PHYSICAL_NET_WALL_DUPLICATE_WALL = (
    "live_external_physical_net_wall_publication_duplicate_wall"
)
LIVE_EXTERNAL_PHYSICAL_NET_WALL_NO_EXTERNAL_WALLS = (
    "live_external_physical_net_wall_publication_no_external_walls"
)
LIVE_EXTERNAL_PHYSICAL_NET_WALL_GEOMETRY_INVALID = (
    "live_external_physical_net_wall_publication_geometry_invalid"
)

PERIMETER_WALLING_SEMANTIC_KEY = "perimeter_walling"
CANONICAL_WALL_OBJECT_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class CanonicalWallPlanMember:
    """Authenticated plan-space geometry retained for one wall member candidate."""

    wall_candidate_id: str
    physical_identity_id: Optional[str]
    viewport_id: str
    centerline_pts: tuple[tuple[float, float], ...]
    curve_control_pts: tuple[tuple[float, float], ...]
    is_curved: bool
    thickness_m: Optional[float]
    length_m: Optional[float]
    level_id: Optional[str]
    end_node_ids: tuple[str, str]
    junction_types: tuple[str, str]
    source_primitive_ids: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    coordinate_space: str = "source_page_points"

    def to_dict(self) -> dict:
        return {
            "wall_candidate_id": self.wall_candidate_id,
            "physical_identity_id": self.physical_identity_id,
            "viewport_id": self.viewport_id,
            "centerline_pts": [list(point) for point in self.centerline_pts],
            "curve_control_pts": [list(point) for point in self.curve_control_pts],
            "is_curved": self.is_curved,
            "thickness_m": self.thickness_m,
            "length_m": self.length_m,
            "level_id": self.level_id,
            "end_node_ids": list(self.end_node_ids),
            "junction_types": list(self.junction_types),
            "source_primitive_ids": list(self.source_primitive_ids),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "coordinate_space": self.coordinate_space,
        }


@dataclass(frozen=True)
class CanonicalOpeningVoidGeometry:
    """Authenticated opening relationship + wall-local void geometry."""

    opening_identity_id: str
    physical_void_record_id: str
    host_binding_record_id: str
    opening_universe_record_id: str
    width_record_id: str
    height_record_id: str
    vertical_placement_record_id: str
    wall_local_frame_id: str
    profile_kind: str
    coordinate_unit: str
    u0: float
    u1: float
    z0: float
    z1: float

    @property
    def width_m(self) -> float:
        return float(self.u1) - float(self.u0)

    @property
    def height_m(self) -> float:
        return float(self.z1) - float(self.z0)

    def to_dict(self) -> dict:
        return {
            "opening_identity_id": self.opening_identity_id,
            "physical_void_record_id": self.physical_void_record_id,
            "host_binding_record_id": self.host_binding_record_id,
            "opening_universe_record_id": self.opening_universe_record_id,
            "width_record_id": self.width_record_id,
            "height_record_id": self.height_record_id,
            "vertical_placement_record_id": self.vertical_placement_record_id,
            "wall_local_frame_id": self.wall_local_frame_id,
            "profile_kind": self.profile_kind,
            "coordinate_unit": self.coordinate_unit,
            "u0": self.u0,
            "u1": self.u1,
            "z0": self.z0,
            "z1": self.z1,
            "width_m": self.width_m,
            "height_m": self.height_m,
        }


@dataclass(frozen=True)
class LiveCanonicalWallObject:
    """Persistent semantic wall snapshot; quantities are derived from this object."""

    canonical_wall_id: str
    physical_wall_id: Optional[str]
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    wall_local_frame_id: Optional[str]
    role: Optional[str]
    coordinate_unit: Optional[str]
    length_m: Optional[float]
    height_m: Optional[float]
    gross_area_m2: Optional[float]
    net_area_m2: Optional[float]
    gross_polygon_wkb_hex: Optional[str]
    net_polygon_wkb_hex: Optional[str]
    member_wall_candidate_ids: tuple[str, ...]
    plan_members: tuple[CanonicalWallPlanMember, ...]
    level_ids: tuple[str, ...]
    opening_identity_ids: tuple[str, ...]
    opening_voids: tuple[CanonicalOpeningVoidGeometry, ...]
    gross_geometry_record_id: Optional[str]
    whole_wall_role_record_id: Optional[str]
    evidence_ids: tuple[str, ...]
    schema_version: str = CANONICAL_WALL_OBJECT_SCHEMA_VERSION
    identity_status: str = "physical_resolved"
    physical_identity_resolved: bool = True

    @property
    def geometry_complete(self) -> bool:
        return bool(
            self.plan_members
            and all(member.centerline_pts for member in self.plan_members)
        )

    @property
    def metric_geometry_complete(self) -> bool:
        return bool(
            self.length_m is not None
            and self.height_m is not None
            and self.gross_area_m2 is not None
            and self.gross_polygon_wkb_hex
        )

    @property
    def quantity_complete(self) -> bool:
        return self.net_area_m2 is not None and bool(self.net_polygon_wkb_hex)

    def to_dict(self) -> dict:
        return {
            "canonical_wall_id": self.canonical_wall_id,
            "physical_wall_id": self.physical_wall_id,
            "document_id": self.document_id,
            "revision_id": self.revision_id,
            "source_sha256": self.source_sha256,
            "snapshot_id": self.snapshot_id,
            "page_id": self.page_id,
            "decision_scope_id": self.decision_scope_id,
            "wall_local_frame_id": self.wall_local_frame_id,
            "role": self.role,
            "coordinate_unit": self.coordinate_unit,
            "length_m": self.length_m,
            "height_m": self.height_m,
            "gross_area_m2": self.gross_area_m2,
            "net_area_m2": self.net_area_m2,
            "gross_polygon_wkb_hex": self.gross_polygon_wkb_hex,
            "net_polygon_wkb_hex": self.net_polygon_wkb_hex,
            "member_wall_candidate_ids": list(self.member_wall_candidate_ids),
            "plan_members": [member.to_dict() for member in self.plan_members],
            "level_ids": list(self.level_ids),
            "opening_identity_ids": list(self.opening_identity_ids),
            "opening_voids": [void.to_dict() for void in self.opening_voids],
            "gross_geometry_record_id": self.gross_geometry_record_id,
            "whole_wall_role_record_id": self.whole_wall_role_record_id,
            "evidence_ids": list(self.evidence_ids),
            "identity_status": self.identity_status,
            "physical_identity_resolved": self.physical_identity_resolved,
            "geometry_complete": self.geometry_complete,
            "metric_geometry_complete": self.metric_geometry_complete,
            "quantity_complete": self.quantity_complete,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class LiveExternalPhysicalNetWallPublication:
    revision_id: str
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]
    quantity_evidence: Optional[QuantityEvidence]
    canonical_walls: tuple[LiveCanonicalWallObject, ...]
    external_wall_ids: tuple[str, ...]
    gross_geometry_record_ids: tuple[str, ...]
    whole_wall_role_record_ids: tuple[str, ...]
    physical_void_record_ids: tuple[str, ...]
    opening_universe_record_ids: tuple[str, ...]
    schema_version: str = LIVE_EXTERNAL_PHYSICAL_NET_WALL_SCHEMA_VERSION


def _clean(value: object) -> str:
    return str(value or "").strip()


def _reasons(*values: object) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        if isinstance(value, (tuple, list)):
            out.extend(_clean(item) for item in value if _clean(item))
        elif _clean(value):
            out.append(_clean(value))
    return tuple(dict.fromkeys(out))


def _blocked(
    *,
    revision_id: str,
    status: EvidenceResolutionStatus,
    reason: str,
    extra_reasons: tuple[str, ...] = (),
) -> LiveExternalPhysicalNetWallPublication:
    if status is EvidenceResolutionStatus.CORROBORATED:
        status = EvidenceResolutionStatus.ABSTAINED
    return LiveExternalPhysicalNetWallPublication(
        revision_id=revision_id,
        status=status,
        reason_codes=_reasons(reason, extra_reasons),
        quantity_evidence=None,
        canonical_walls=(),
        external_wall_ids=(),
        gross_geometry_record_ids=(),
        whole_wall_role_record_ids=(),
        physical_void_record_ids=(),
        opening_universe_record_ids=(),
    )


def _lineage_tuple(value) -> tuple[str, str, str, str, str, str]:
    return (
        _clean(value.document_id),
        _clean(value.revision_id),
        _clean(value.source_sha256),
        _clean(value.snapshot_id),
        _clean(value.page_id),
        _clean(value.decision_scope_id),
    )


def _enum_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return _clean(raw)


def _canonical_plan_members(
    wall_opening_composition: LiveWallOpeningAuthorityComposition,
    gross_record: object,
) -> tuple[CanonicalWallPlanMember, ...]:
    """Rehydrate authenticated plan geometry without changing quantity authority."""

    authority = wall_opening_composition.physical_wall_candidate_authority
    if authority is None:
        return ()
    selector = authority.selector_for_decision_scope(
        document_id=_clean(gross_record.document_id),
        revision_id=_clean(gross_record.revision_id),
        source_sha256=_clean(gross_record.source_sha256),
        snapshot_id=_clean(gross_record.snapshot_id),
        page_id=_clean(gross_record.page_id),
        decision_scope_id=_clean(gross_record.decision_scope_id),
    )
    if selector is None:
        return ()
    scope = authority.resolve_scope(selector)
    if scope.status is not EvidenceResolutionStatus.CORROBORATED:
        return ()

    records_by_id = {record.wall_candidate_id: record for record in scope.records}
    out: list[CanonicalWallPlanMember] = []
    for member_id in tuple(gross_record.member_wall_candidate_ids):
        record = records_by_id.get(_clean(member_id))
        if record is None:
            return ()
        wall = record.wall_candidate
        identity = record.physical_identity
        out.append(
            CanonicalWallPlanMember(
                wall_candidate_id=_clean(record.wall_candidate_id),
                physical_identity_id=(
                    _clean(identity.physical_identity_id)
                    if identity.physical_identity_id
                    else None
                ),
                viewport_id=_clean(wall.viewport_id),
                centerline_pts=tuple(
                    (float(point[0]), float(point[1]))
                    for point in wall.centerline_pts
                ),
                curve_control_pts=tuple(
                    (float(point[0]), float(point[1]))
                    for point in (wall.curve_control_pts or ())
                ),
                is_curved=bool(wall.is_curved),
                thickness_m=(
                    float(wall.thickness_m)
                    if wall.thickness_m is not None
                    else None
                ),
                length_m=(
                    float(wall.length_m) if wall.length_m is not None else None
                ),
                level_id=_clean(wall.level_id) or None,
                end_node_ids=(
                    _clean(wall.end_node_ids[0]),
                    _clean(wall.end_node_ids[1]),
                ),
                junction_types=tuple(
                    _enum_value(value) for value in wall.junction_types
                ),
                source_primitive_ids=tuple(identity.source_primitive_ids),
                supporting_evidence_ids=tuple(wall.supporting_evidence_ids),
            )
        )
    return tuple(out)


def compose_live_external_physical_net_wall_publication(
    *,
    wall_opening_composition: LiveWallOpeningAuthorityComposition,
    physical_void_composition: LivePhysicalOpeningVoidComposition,
    gross_wall_composition: LiveGrossWallGeometryComposition,
    whole_wall_role_composition: LiveWholeWallRoleComposition,
) -> LiveExternalPhysicalNetWallPublication:
    """Publish source-authenticated external whole-wall physical net area."""

    if type(wall_opening_composition) is not LiveWallOpeningAuthorityComposition:
        raise TypeError(
            "wall_opening_composition must be LiveWallOpeningAuthorityComposition"
        )
    if type(physical_void_composition) is not LivePhysicalOpeningVoidComposition:
        raise TypeError(
            "physical_void_composition must be LivePhysicalOpeningVoidComposition"
        )
    if type(gross_wall_composition) is not LiveGrossWallGeometryComposition:
        raise TypeError(
            "gross_wall_composition must be LiveGrossWallGeometryComposition"
        )
    if type(whole_wall_role_composition) is not LiveWholeWallRoleComposition:
        raise TypeError(
            "whole_wall_role_composition must be LiveWholeWallRoleComposition"
        )

    revision_id = _clean(wall_opening_composition.revision_id)
    if (
        _clean(physical_void_composition.revision_id) != revision_id
        or _clean(gross_wall_composition.revision_id) != revision_id
        or _clean(whole_wall_role_composition.revision_id) != revision_id
    ):
        return _blocked(
            revision_id=revision_id,
            status=EvidenceResolutionStatus.CONFLICT,
            reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_LINEAGE_MISMATCH,
        )

    if (
        wall_opening_composition.status is not EvidenceResolutionStatus.CORROBORATED
        or gross_wall_composition.status is not EvidenceResolutionStatus.CORROBORATED
        or whole_wall_role_composition.status
        is not EvidenceResolutionStatus.CORROBORATED
        or gross_wall_composition.gross_wall_geometry_authority is None
        or whole_wall_role_composition.whole_wall_role_authority is None
        or not gross_wall_composition.traces
    ):
        return _blocked(
            revision_id=revision_id,
            status=EvidenceResolutionStatus.ABSTAINED,
            reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_UPSTREAM_INCOMPLETE,
            extra_reasons=_reasons(
                wall_opening_composition.reason_codes,
                gross_wall_composition.reason_codes,
                whole_wall_role_composition.reason_codes,
            ),
        )

    wall_ids = tuple(
        _clean(trace.physical_wall_id) for trace in gross_wall_composition.traces
    )
    if (
        any(not wall_id for wall_id in wall_ids)
        or len(set(wall_ids)) != len(wall_ids)
    ):
        return _blocked(
            revision_id=revision_id,
            status=EvidenceResolutionStatus.CONFLICT,
            reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_DUPLICATE_WALL,
        )

    expected_opening_ids = tuple(
        _clean(trace.opening_identity_id)
        for trace in wall_opening_composition.opening_bindings
        if _clean(trace.opening_identity_id)
    )
    if len(set(expected_opening_ids)) != len(expected_opening_ids):
        return _blocked(
            revision_id=revision_id,
            status=EvidenceResolutionStatus.CONFLICT,
            reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_UPSTREAM_INCOMPLETE,
        )

    if expected_opening_ids:
        trace_ids = tuple(
            _clean(trace.opening_identity_id)
            for trace in physical_void_composition.traces
        )
        trace_opening_ids = set(trace_ids)
        if (
            any(not opening_id for opening_id in trace_ids)
            or len(trace_opening_ids) != len(trace_ids)
        ):
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_VOID_UNRESOLVED,
            )
        if (
            physical_void_composition.status
            is not EvidenceResolutionStatus.CORROBORATED
            or trace_opening_ids != set(expected_opening_ids)
            or set(physical_void_composition.void_selectors)
            != set(expected_opening_ids)
        ):
            return _blocked(
                revision_id=revision_id,
                status=(
                    EvidenceResolutionStatus.CONFLICT
                    if physical_void_composition.status
                    is EvidenceResolutionStatus.CONFLICT
                    else EvidenceResolutionStatus.ABSTAINED
                ),
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_VOID_UNRESOLVED,
                extra_reasons=tuple(physical_void_composition.reason_codes),
            )
    elif physical_void_composition.traces or physical_void_composition.void_selectors:
        return _blocked(
            revision_id=revision_id,
            status=EvidenceResolutionStatus.CONFLICT,
            reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_VOID_UNRESOLVED,
        )

    gross_authority = gross_wall_composition.gross_wall_geometry_authority
    role_authority = whole_wall_role_composition.whole_wall_role_authority

    gross_records = {}
    role_records = {}
    universe_record_ids: list[str] = []

    for trace in gross_wall_composition.traces:
        wall_id = _clean(trace.physical_wall_id)
        gross_selector = gross_wall_composition.gross_selectors.get(wall_id)
        role_selector = whole_wall_role_composition.role_selectors.get(wall_id)
        universe = wall_opening_composition.opening_universe_results.get(
            _clean(trace.page_id)
        )
        if (
            gross_selector is None
            or role_selector is None
            or universe is None
            or universe.status is not EvidenceResolutionStatus.CORROBORATED
            or universe.record is None
            or not universe.record.decision_scope_complete
        ):
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.ABSTAINED,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_UPSTREAM_INCOMPLETE,
            )

        gross_result = gross_authority.resolve(gross_selector)
        role_result = role_authority.resolve(role_selector)
        gross_record = gross_result.record
        role_record = role_result.record
        if (
            gross_result.status is not EvidenceResolutionStatus.CORROBORATED
            or gross_record is None
        ):
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.ABSTAINED,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_UPSTREAM_INCOMPLETE,
                extra_reasons=tuple(gross_result.reason_codes),
            )
        if (
            role_result.status is not EvidenceResolutionStatus.CORROBORATED
            or role_record is None
            or role_record.role is WallRoleClassification.UNRESOLVED
        ):
            return _blocked(
                revision_id=revision_id,
                status=(
                    EvidenceResolutionStatus.CONFLICT
                    if role_result.status is EvidenceResolutionStatus.CONFLICT
                    else EvidenceResolutionStatus.ABSTAINED
                ),
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_ROLE_UNRESOLVED,
                extra_reasons=tuple(role_result.reason_codes),
            )

        if (
            _lineage_tuple(gross_selector) != _lineage_tuple(gross_record)
            or _lineage_tuple(role_selector) != _lineage_tuple(role_record)
            or _lineage_tuple(gross_record) != _lineage_tuple(role_record)
            or _clean(gross_record.physical_wall_id) != wall_id
            or _clean(role_record.physical_wall_id) != wall_id
            or _clean(role_record.gross_geometry_record_id)
            != _clean(gross_record.record_id)
        ):
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_LINEAGE_MISMATCH,
            )

        if (
            not math.isfinite(float(gross_record.length_m))
            or not math.isfinite(float(gross_record.height_m))
            or not math.isfinite(float(gross_record.gross_area_m2))
            or float(gross_record.length_m) <= 0.0
            or float(gross_record.height_m) <= 0.0
            or float(gross_record.gross_area_m2) <= 0.0
        ):
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_GEOMETRY_INVALID,
            )

        expected_gross_area = float(gross_record.length_m) * float(
            gross_record.height_m
        )
        if not math.isclose(
            expected_gross_area,
            float(gross_record.gross_area_m2),
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_GEOMETRY_INVALID,
            )

        gross_records[wall_id] = gross_record
        role_records[wall_id] = role_record
        universe_record_ids.append(_clean(universe.record.record_id))

    voids_by_wall: dict[str, list[object]] = {wall_id: [] for wall_id in wall_ids}
    all_void_record_ids: list[str] = []

    for opening_id in expected_opening_ids:
        selector = physical_void_composition.void_selectors.get(opening_id)
        if selector is None:
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.ABSTAINED,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_VOID_UNRESOLVED,
            )
        authority = physical_void_composition.physical_opening_void_authorities.get(
            _clean(selector.page_id)
        )
        if authority is None:
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.ABSTAINED,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_VOID_UNRESOLVED,
            )
        result = authority.resolve(selector)
        record = result.record
        if (
            result.status is not EvidenceResolutionStatus.CORROBORATED
            or record is None
            or _clean(record.opening_identity_id) != opening_id
            or _lineage_tuple(selector) != _lineage_tuple(record)
        ):
            return _blocked(
                revision_id=revision_id,
                status=(
                    EvidenceResolutionStatus.CONFLICT
                    if result.status is EvidenceResolutionStatus.CONFLICT
                    else EvidenceResolutionStatus.ABSTAINED
                ),
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_VOID_UNRESOLVED,
                extra_reasons=tuple(result.reason_codes),
            )

        wall_id = _clean(record.wall_local_frame_id)
        gross_record = gross_records.get(wall_id)
        if gross_record is None:
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_LINEAGE_MISMATCH,
            )
        if (
            _clean(record.page_id) != _clean(gross_record.page_id)
            or _clean(record.decision_scope_id)
            != _clean(gross_record.decision_scope_id)
            or _clean(record.revision_id) != revision_id
        ):
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_LINEAGE_MISMATCH,
            )

        u0 = float(record.u0)
        u1 = float(record.u1)
        z0 = float(record.z0)
        z1 = float(record.z1)
        if (
            not all(math.isfinite(v) for v in (u0, u1, z0, z1))
            or u0 < 0.0
            or z0 < 0.0
            or u1 <= u0
            or z1 <= z0
            or u1 > float(gross_record.length_m) + 1e-9
            or z1 > float(gross_record.height_m) + 1e-9
        ):
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_GEOMETRY_INVALID,
            )

        voids_by_wall[wall_id].append(record)
        all_void_record_ids.append(_clean(record.record_id))

    external_wall_ids: list[str] = []
    external_gross_ids: list[str] = []
    external_role_ids: list[str] = []
    net_values: list[float] = []
    external_void_ids: list[str] = []
    canonical_walls: list[LiveCanonicalWallObject] = []

    for wall_id in wall_ids:
        role_record = role_records[wall_id]
        if role_record.role is not WallRoleClassification.EXTERNAL:
            continue

        gross_record = gross_records[wall_id]
        gross_polygon = box(
            0.0,
            0.0,
            float(gross_record.length_m),
            float(gross_record.height_m),
        )
        void_records = voids_by_wall.get(wall_id, [])
        void_polygons = [
            box(float(v.u0), float(v.z0), float(v.u1), float(v.z1))
            for v in void_records
        ]
        try:
            net_polygon = subtract_void_union_from_wall_polygon(
                gross_polygon,
                void_polygons,
            )
        except ValueError:
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_GEOMETRY_INVALID,
            )

        net_area = float(net_polygon.area)
        if not math.isfinite(net_area) or net_area < 0.0:
            return _blocked(
                revision_id=revision_id,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_GEOMETRY_INVALID,
            )

        plan_members = _canonical_plan_members(
            wall_opening_composition,
            gross_record,
        )
        opening_voids = tuple(
            CanonicalOpeningVoidGeometry(
                opening_identity_id=_clean(void.opening_identity_id),
                physical_void_record_id=_clean(void.record_id),
                host_binding_record_id=_clean(void.host_binding_record_id),
                opening_universe_record_id=_clean(void.opening_universe_record_id),
                width_record_id=_clean(void.width_record_id),
                height_record_id=_clean(void.height_record_id),
                vertical_placement_record_id=_clean(void.vertical_placement_record_id),
                wall_local_frame_id=_clean(void.wall_local_frame_id),
                profile_kind=_clean(void.profile_kind),
                coordinate_unit=_clean(void.coordinate_unit),
                u0=float(void.u0),
                u1=float(void.u1),
                z0=float(void.z0),
                z1=float(void.z1),
            )
            for void in void_records
        )
        canonical_evidence_ids = tuple(
            dict.fromkeys(
                (
                    _clean(gross_record.record_id),
                    _clean(role_record.record_id),
                    *(_clean(void.record_id) for void in void_records),
                    *(
                        evidence_id
                        for member in plan_members
                        for evidence_id in member.supporting_evidence_ids
                    ),
                )
            )
        )
        canonical_walls.append(
            LiveCanonicalWallObject(
                canonical_wall_id=wall_id,
                physical_wall_id=wall_id,
                document_id=_clean(gross_record.document_id),
                revision_id=_clean(gross_record.revision_id),
                source_sha256=_clean(gross_record.source_sha256),
                snapshot_id=_clean(gross_record.snapshot_id),
                page_id=_clean(gross_record.page_id),
                decision_scope_id=_clean(gross_record.decision_scope_id),
                wall_local_frame_id=_clean(gross_record.wall_local_frame_id),
                role=_enum_value(role_record.role),
                coordinate_unit=_clean(gross_record.coordinate_unit),
                length_m=float(gross_record.length_m),
                height_m=float(gross_record.height_m),
                gross_area_m2=float(gross_record.gross_area_m2),
                net_area_m2=net_area,
                gross_polygon_wkb_hex=_clean(gross_record.polygon_wkb_hex),
                net_polygon_wkb_hex=str(net_polygon.wkb_hex),
                member_wall_candidate_ids=tuple(
                    _clean(value)
                    for value in gross_record.member_wall_candidate_ids
                ),
                plan_members=plan_members,
                level_ids=tuple(
                    dict.fromkeys(
                        member.level_id
                        for member in plan_members
                        if member.level_id
                    )
                ),
                opening_identity_ids=tuple(
                    _clean(void.opening_identity_id) for void in void_records
                ),
                opening_voids=opening_voids,
                gross_geometry_record_id=_clean(gross_record.record_id),
                whole_wall_role_record_id=_clean(role_record.record_id),
                evidence_ids=canonical_evidence_ids,
            )
        )

        external_wall_ids.append(wall_id)
        external_gross_ids.append(_clean(gross_record.record_id))
        external_role_ids.append(_clean(role_record.record_id))
        external_void_ids.extend(_clean(v.record_id) for v in void_records)
        net_values.append(net_area)

    if not external_wall_ids:
        return _blocked(
            revision_id=revision_id,
            status=EvidenceResolutionStatus.ABSTAINED,
            reason=LIVE_EXTERNAL_PHYSICAL_NET_WALL_NO_EXTERNAL_WALLS,
        )

    value = round(math.fsum(net_values), 6)
    evidence = QuantityEvidence(
        quantity_id=stable_contract_id(
            "external_physical_net_wall_area",
            {
                "revision_id": revision_id,
                "physical_wall_ids": tuple(external_wall_ids),
                "gross_geometry_record_ids": tuple(external_gross_ids),
                "whole_wall_role_record_ids": tuple(external_role_ids),
                "physical_void_record_ids": tuple(external_void_ids),
                "opening_universe_record_ids": tuple(dict.fromkeys(universe_record_ids)),
                "value_m2": value,
            },
        ),
        family="wall_net_area",
        semantic_key=PERIMETER_WALLING_SEMANTIC_KEY,
        value=value,
        unit="m2",
        input_entity_ids=tuple(external_wall_ids),
        formula=(
            "sum(gross_wall_polygon - union(all authenticated physical opening "
            "voids in each source-authenticated external whole wall))"
        ),
        formula_version="1.0.0",
        evidence_ids=tuple(
            dict.fromkeys(
                (
                    *external_gross_ids,
                    *external_role_ids,
                    *external_void_ids,
                    *universe_record_ids,
                )
            )
        ),
        authority=(
            "pb_live_external_physical_net_wall_publication."
            "compose_live_external_physical_net_wall_publication"
        ),
        status="corroborated",
        confidence=1.0,
        abstained=False,
        blocking_reasons=(),
        reason_codes=(LIVE_EXTERNAL_PHYSICAL_NET_WALL_RESOLVED,),
        metadata={
            "revision_id": revision_id,
            "external_wall_ids": tuple(external_wall_ids),
            "canonical_wall_object_ids": tuple(
                wall.canonical_wall_id for wall in canonical_walls
            ),
            "gross_geometry_record_ids": tuple(external_gross_ids),
            "whole_wall_role_record_ids": tuple(external_role_ids),
            "physical_void_record_ids": tuple(external_void_ids),
            "opening_universe_record_ids": tuple(
                dict.fromkeys(universe_record_ids)
            ),
            "deduction_policy": "physical_geometry_not_trade_finish_policy",
        },
    )
    return LiveExternalPhysicalNetWallPublication(
        revision_id=revision_id,
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=(LIVE_EXTERNAL_PHYSICAL_NET_WALL_RESOLVED,),
        quantity_evidence=evidence,
        canonical_walls=tuple(canonical_walls),
        external_wall_ids=tuple(external_wall_ids),
        gross_geometry_record_ids=tuple(external_gross_ids),
        whole_wall_role_record_ids=tuple(external_role_ids),
        physical_void_record_ids=tuple(external_void_ids),
        opening_universe_record_ids=tuple(dict.fromkeys(universe_record_ids)),
    )


__all__ = [
    "LIVE_EXTERNAL_PHYSICAL_NET_WALL_DUPLICATE_WALL",
    "LIVE_EXTERNAL_PHYSICAL_NET_WALL_GEOMETRY_INVALID",
    "LIVE_EXTERNAL_PHYSICAL_NET_WALL_LINEAGE_MISMATCH",
    "LIVE_EXTERNAL_PHYSICAL_NET_WALL_NO_EXTERNAL_WALLS",
    "LIVE_EXTERNAL_PHYSICAL_NET_WALL_RESOLVED",
    "LIVE_EXTERNAL_PHYSICAL_NET_WALL_ROLE_UNRESOLVED",
    "LIVE_EXTERNAL_PHYSICAL_NET_WALL_SCHEMA_VERSION",
    "LIVE_EXTERNAL_PHYSICAL_NET_WALL_UPSTREAM_INCOMPLETE",
    "LIVE_EXTERNAL_PHYSICAL_NET_WALL_VOID_UNRESOLVED",
    "CANONICAL_WALL_OBJECT_SCHEMA_VERSION",
    "PERIMETER_WALLING_SEMANTIC_KEY",
    "CanonicalOpeningVoidGeometry",
    "CanonicalWallPlanMember",
    "LiveCanonicalWallObject",
    "LiveExternalPhysicalNetWallPublication",
    "compose_live_external_physical_net_wall_publication",
]
